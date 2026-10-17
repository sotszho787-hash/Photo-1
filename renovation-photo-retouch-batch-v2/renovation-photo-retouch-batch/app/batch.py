"""One-shot, local, no-LLM, faithful renovation photograph batch color grader.

CLI: python -m app.batch [--input FOLDER_OR_ZIP] [--output OUTPUT_DIR]
Every run is an isolated dated directory and an individual delivery ZIP.
Originals are opened read-only. Neither source photos nor original ZIP are modified.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile
from datetime import datetime, timezone

from .processing import EXTENSIONS, process

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / 'workspace' / 'INPUT'
DEFAULT_OUTPUT = ROOT / 'workspace' / 'OUTPUT'
CONFIG = ROOT / 'config.json'
OVERRIDES = ROOT / 'lighting_overrides.csv'
LOGGER = logging.getLogger('muji_batch')


def json_safe(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def is_below(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def validate_options(cfg):
    required = ['faithful_strength', 'aesthetic_strength', 'jpeg_quality',
                'comparison_max_width', 'max_megapixels', 'max_archive_files',
                'max_archive_uncompressed_mb', 'default_light']
    for key in required:
        if key not in cfg: raise ValueError(f'config.json missing {key}')
    a = float(cfg['faithful_strength'])
    b = float(cfg['aesthetic_strength'])
    if not (0 <= a < b <= 1):
        raise ValueError('Expected 0 <= faithful_strength < aesthetic_strength <= 1')
    if cfg['default_light'] not in ('unknown', 'no-window'):
        raise ValueError('Default must be unknown/no-window, never assume window direction.')
    if not 1 <= int(cfg['jpeg_quality']) <= 100: raise ValueError('jpeg_quality must be 1-100')
    if not 50 <= int(cfg['comparison_max_width']) <= 2000: raise ValueError('Bad comparison_max_width')
    if not 1 <= int(cfg['max_megapixels']) <= 48: raise ValueError('max_megapixels must be 1-48')
    if not 1 <= int(cfg['max_archive_files']) <= 10000: raise ValueError('max_archive_files must be 1-10000')
    if not 1 <= int(cfg['max_archive_uncompressed_mb']) <= 50000:
        raise ValueError('Bad max_archive_uncompressed_mb')


def load_overrides(path: Path):
    rules = {}
    if not path.is_file(): return rules
    with path.open('r', encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(filter(lambda line: not line.lstrip().startswith('#'), stream)):
            name = (row.get('filename') or '').strip().replace('\\', '/')
            if not name: continue
            light = (row.get('light') or 'unknown').strip().lower()
            side = (row.get('window_side') or 'none').strip().lower()
            if light not in ('unknown', 'no-window', 'window') or side not in ('none','left','right','top','bottom'):
                raise ValueError(f'Invalid override for {name}: {light}, {side}')
            if light != 'window' and side != 'none':
                raise ValueError(f'Window direction must be confirmed on a real window: {name}')
            rules[name] = (light, side)
    return rules


def supported_photos(where: Path, recursive: bool):
    candidates = where.rglob('*') if recursive else where.iterdir()
    photos = [p for p in candidates if p.is_file() and not p.is_symlink() and p.suffix.lower() in EXTENSIONS]
    return sorted(photos, key=lambda p: p.relative_to(where).as_posix().casefold())


def extract_zip_safely(archive: Path, destination: Path, cfg: dict):
    """Reject path traversal, links, duplicate names and archive bombs; extract photos only."""
    seen = set()
    total = 0
    photo_count = 0
    limit = int(cfg['max_archive_uncompressed_mb']) * 1024 * 1024
    with ZipFile(archive) as z:
        for info in z.infolist():
            if info.is_dir(): continue
            name = info.filename.replace('\\', '/')
            q = PurePosixPath(name)
            win = PureWindowsPath(info.filename)
            if (q.is_absolute() or win.is_absolute() or win.drive or
                not name or any(p in ('..', '.', '') for p in q.parts) or
                any(ord(c) < 32 for c in name)):
                raise ValueError(f'Unsafe ZIP entry: {info.filename!r}')
            # UNIX symlink is a non-regular file; reject to avoid linked directory traversal.
            mode = (info.external_attr >> 16) & 0o170000
            if mode not in (0, 0o100000):
                raise ValueError(f'ZIP contains non-regular file: {name}')
            if Path(name).suffix.lower() not in EXTENSIONS: continue
            key = name.casefold()
            if key in seen: raise ValueError(f'Duplicate path in ZIP: {name}')
            seen.add(key)
            photo_count += 1
            total += info.file_size
            if photo_count > int(cfg['max_archive_files']) or total > limit:
                raise ValueError('ZIP exceeded file count or uncompressed size safety limit')
        # Scan complete before writing anything.
        for info in z.infolist():
            if info.is_dir(): continue
            name = info.filename.replace('\\', '/')
            if Path(name).suffix.lower() not in EXTENSIONS: continue
            output = destination.joinpath(*PurePosixPath(name).parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as source, output.open('wb') as dest:
                copied = 0
                while True:
                    buf = source.read(1024 * 1024)
                    if not buf: break
                    copied += len(buf)
                    if copied > info.file_size:
                        raise ValueError('ZIP entry streamed more bytes than declared')
                    dest.write(buf)
    return photo_count


def new_run_folder(parent: Path) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        # Random identifier avoids collisions even when two batches launch within one second.
        dest = parent / (datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6])
        try:
            dest.mkdir()
            return dest
        except FileExistsError:
            pass
    raise RuntimeError('Cannot create unique output directory')


def setup_logging(where: Path):
    LOGGER.setLevel(logging.INFO)
    for handler in LOGGER.handlers[:]:
        LOGGER.removeHandler(handler)
        handler.close()
    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
    for handler in (logging.FileHandler(where / 'process.log', encoding='utf-8'),):
        handler.setFormatter(formatter)
        LOGGER.addHandler(handler)


def package_batch(run: Path, zip_path: Path):
    tmp = zip_path.with_suffix('.partial.zip')
    try:
        with ZipFile(tmp, 'w', ZIP_DEFLATED, compresslevel=4, allowZip64=True) as z:
            for f in sorted(run.rglob('*')):
                if f.is_file() and f != tmp and '__pycache__' not in f.parts:
                    z.write(f, arcname=f.relative_to(run).as_posix())
        os.replace(tmp,zip_path)
    finally:
        tmp.unlink(missing_ok=True)


def perform(input_path: Path, output_root: Path, cfg: dict, overrides: dict) -> tuple[Path, Path, dict]:
    """Run full batch. Leaves originals intact, saves errors and summary even with bad individual photos."""
    validate_options(cfg)
    input_path = input_path.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    if not input_path.exists(): raise FileNotFoundError(f'Input path not found: {input_path}')
    if input_path.is_dir() and is_below(output_root, input_path):
        raise ValueError('Output directory cannot be INSIDE input directory.')
    if input_path.is_file() and input_path.suffix.lower() != '.zip':
        raise ValueError('Input must be a folder or ZIP, not an individual image.')

    temp = tempfile.TemporaryDirectory(prefix='muji_batch_') if input_path.is_file() else None
    run = None
    try:
        src_root = Path(temp.name) if temp else input_path
        if temp: extract_zip_safely(input_path, src_root, cfg)
        photos = supported_photos(src_root, bool(cfg.get('process_subfolders', True)))
        if not photos:
            raise ValueError(f'No supported photo files found in {input_path} (JPG, PNG, WEBP, TIFF)')
        if len(photos) > int(cfg['max_archive_files']):
            raise ValueError('Too many photos for one batch. Increase max_archive_files in config.json if appropriate.')
        run = new_run_folder(output_root)
        setup_logging(run)
        LOGGER.info('Starting batch. Photos=%d; input=%s',len(photos),input_path)
        summary = {
            'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'input': str(input_path), 'total': len(photos), 'successful': 0, 'failed': 0,
            'variants': {'Faithful': cfg['faithful_strength'], 'Aesthetic': cfg['aesthetic_strength']},
            'source_originals': 'untouched (no originals in the delivery ZIP)',
            'window_logic': 'Unverified bright borders are NOT treated as windows; only explicit CSV confirmation may apply subtle directional brightness.',
            'items': []
        }
        for i, src in enumerate(photos, start=1):
            rel = src.relative_to(src_root).as_posix()
            row = {'filename': rel, 'status': 'failed', 'error': '', 'variants': {}}
            outputs_for_photo = []
            LOGGER.info('[%d/%d] %s',i,len(photos),rel)
            try:
                # An image might change while an active file copy is in progress; reject/rollback.
                fingerprint = sha256_file(src)
                key = hashlib.sha256(rel.encode('utf-8')).hexdigest()[:10]
                basename = re.sub(r'[^\w\-\u4e00-\u9fff]+', '_', src.stem, flags=re.UNICODE)[:80].strip('_') or 'image'
                safe = f'{basename}_{key}_{fingerprint[:8]}'
                light, side = overrides.get(rel, overrides.get(src.name, (cfg['default_light'], 'none')))
                out_ext = src.suffix.lower()
                for variant, strength in (('Faithful',cfg['faithful_strength']),('Aesthetic',cfg['aesthetic_strength'])):
                    job_cfg = dict(cfg, strength=float(strength))
                    dest = run / variant / (safe + out_ext)
                    compare = run / 'Before_After' / variant / (safe + '_Before_After.jpg')
                    rep = run / 'Reports' / variant / (safe + '_QA.json')
                    outputs_for_photo.extend([dest,compare,rep])
                    data = process(src,dest,compare,rep,job_cfg,light,side,fingerprint)
                    row['variants'][variant] = {
                        'retouched':dest.relative_to(run).as_posix(),
                        'comparison':compare.relative_to(run).as_posix(),
                        'qa_report':rep.relative_to(run).as_posix(),
                        'warnings':data['warnings'],
                        'manual_review_needed':data['manual_review_needed']
                    }
                if sha256_file(src) != fingerprint:
                    raise RuntimeError('Source changed during batch, output discarded. Retry after copy is complete.')
                row['status'] = 'success'
                summary['successful'] += 1
            except Exception as err:
                row['error'] = f'{type(err).__name__}: {err}'
                row['variants'] = {}
                summary['failed'] += 1
                LOGGER.error('FAILED %s: %s',rel,row['error'])
                for file in outputs_for_photo:
                    file.unlink(missing_ok=True)
            summary['items'].append(row)
        LOGGER.info('FINISHED: success=%d / failed=%d',summary['successful'],summary['failed'])
        (run/'Batch_Report.json').write_text(json_safe(summary),encoding='utf-8')
        with (run/'Batch_Report.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.writer(f)
            writer.writerow(['Original','Status','Error','Faithful QA flags','Aesthetic QA flags'])
            for row in summary['items']:
                writer.writerow([row['filename'],row['status'],row['error'],
                    '; '.join(row['variants'].get('Faithful',{}).get('warnings',[])),
                    '; '.join(row['variants'].get('Aesthetic',{}).get('warnings',[]))])
        zip_path=output_root/(run.name+'_MUJI_Batch.zip')
        package_batch(run,zip_path)
        LOGGER.info('ZIP ready: %s',zip_path)
        for handler in LOGGER.handlers[:]:
            LOGGER.removeHandler(handler)
            handler.close()
        return run,zip_path,summary
    finally:
        if temp: temp.cleanup()


def main(argv=None):
    parser=argparse.ArgumentParser(description='Batch faithful MUJI photo grading. Run locally; images stay on disk.')
    parser.add_argument('--input',type=Path,default=DEFAULT_INPUT,help='Folder or photo ZIP')
    parser.add_argument('--output',type=Path,default=DEFAULT_OUTPUT,help='Output folder outside of input')
    parser.add_argument('--config',type=Path,default=CONFIG)
    parser.add_argument('--lighting-overrides',type=Path,default=OVERRIDES)
    args=parser.parse_args(argv)
    try:
        cfg=json.loads(args.config.read_text(encoding='utf-8-sig'))
        run,archive,summary=perform(args.input,args.output,cfg,load_overrides(args.lighting_overrides))
        print(f'\nRESULT FOLDER: {run}\nDELIVERY ZIP: {archive}\nDONE={summary["successful"]} FAILED={summary["failed"]}')
        return 0 if summary['failed']==0 else 2
    except (ValueError,OSError,BadZipFile,RuntimeError) as e:
        print(f'BATCH ERROR: {type(e).__name__}: {e}',file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
