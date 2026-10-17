"""Optional installation: copies the existing skill plus local batch instructions.
No silent modification of an installed skill: previous version is backed up first.
"""
from __future__ import annotations
import argparse
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def install(home=None):
    home = Path(home) if home is not None else Path.home()
    skill_dir = home / '.agents' / 'skills'
    source = ROOT / 'renovation-photo-retouch'
    target = skill_dir / 'renovation-photo-retouch'
    skill_dir.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup = skill_dir / ('renovation-photo-retouch_backup_' + time.strftime('%Y%m%d_%H%M%S'))
        index = 1
        while backup.exists():
            backup = skill_dir / f'renovation-photo-retouch_backup_{int(time.time())}_{index}'
            index += 1
        target.rename(backup)
        print('Existing skill backed up at:', backup)
    shutil.copytree(source, target)
    # Pointer stored in the installed skill so Codex can find the runnable local package.
    (target / 'BATCH_PACKAGE_LOCATION.md').write_text(
        '# Local one-click batch runner\n\n'
        f'Package root: `{ROOT}`\n\n'
        f'From this directory run: `{ROOT / "RUN_BATCH.bat"}` (Windows)\n\n'
        f'Or `cd "{ROOT}"` then `.venv\\Scripts\\python.exe -m app.batch --input "C:\\path\\photos.zip"`.\n\n'
        'Never insert base64 photo contents or verbose logs into the Codex prompt. '\
        'Read summary reports from workspace/OUTPUT and present delivery ZIP path. '\
        'No images are uploaded by this local Python pipeline.\n', encoding='utf-8')
    print('Skill installed:', target)
    return target


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--home',type=Path,help=argparse.SUPPRESS)
    args=p.parse_args()
    install(args.home)
