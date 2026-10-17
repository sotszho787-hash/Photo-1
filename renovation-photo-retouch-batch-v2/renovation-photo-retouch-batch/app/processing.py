"""Conservative non-generative color-only photo grading; no geometry, inpainting, objects, or AI.

It is intentionally unable to discover the location of a physical window.
Directional daylight is NEVER applied without an explicit per-file confirmation.
"""
from __future__ import annotations

import io
import json
import math
import os
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
from PIL import Image, ImageOps, ImageDraw, ImageFont, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 48_000_000
EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.tif', '.tiff'}


def utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def metrics(im: Image.Image) -> dict:
    # Sampling a thumbnail keeps memory low for high resolution photos.
    sample = im.copy()
    sample.thumbnail((720, 720), Image.Resampling.LANCZOS)
    a = np.asarray(sample.convert('RGB'), dtype=np.float32) / 255.0
    y = a[..., 0] * .2126 + a[..., 1] * .7152 + a[..., 2] * .0722
    # Estimate neutral surfaces, not white balance from colorful furniture.
    chroma = a.max(axis=2) - a.min(axis=2)
    neutral = (chroma < .09) & (y > .24) & (y < .84)
    neutrals = a[neutral]
    neutral_count = len(neutrals)
    cast = list(np.round(np.median(neutrals, axis=0), 4)) if neutral_count >= 250 else None
    # NOT a true window recognizer; any bright border may be a lamp/white wall.
    h, w = y.shape
    edges = {
        'left': float(y[:, :max(1,w//6)].mean()),
        'right': float(y[:, -max(1,w//6):].mean()),
        'top': float(y[:max(1,h//6), :].mean()),
        'bottom': float(y[-max(1,h//6):, :].mean())
    }
    brightest_side = max(edges, key=edges.get)
    mean_others = float(np.mean([v for k,v in edges.items() if k != brightest_side]))
    hint = brightest_side if edges[brightest_side] > .72 and edges[brightest_side] - mean_others > .12 else 'none'
    return {
        'median_luminance': float(np.median(y)),
        'mean_luminance': float(np.mean(y)),
        'dark_fraction_luma_lt_0_08': float(np.mean(y < .08)),
        'highlight_fraction_luma_gt_0_98': float(np.mean(y > .98)),
        'clipped_rgb_fraction_any_ge_0_995': float(np.mean(np.any(a >= .995, axis=2))),
        'neutral_sample_count': neutral_count,
        'neutral_rgb_medians': [float(v) for v in cast] if cast is not None else None,
        'brightest_border_hint_unverified': hint,
        'border_brightness': {k: round(v, 4) for k,v in edges.items()}
    }


def grade_tile(src: np.ndarray, cfg: dict, wb: np.ndarray, ev: float, light: str, side: str,
               left: int, top: int, full_size: tuple[int,int]) -> np.ndarray:
    """Map each RGB pixel to a new RGB value in same xy position; alpha handled separately."""
    strength = float(cfg['strength'])
    a = src[..., :3].astype(np.float32) / 255.0
    y = a[..., 0] * .2126 + a[..., 1] * .7152 + a[..., 2] * .0722
    # Gentle exposure biased towards low/midtones, suppress highlight blowout.
    protect = np.clip((y - .64) / .30, 0, 1)**2
    a *= np.exp2(ev * (1 - protect))[..., None]
    a += ((.042 * strength) * (1 - y)**2.1)[..., None]
    # Neutral-aware AWB of limited range plus barely warm MUJI tint.
    tone = np.clip(1 - np.abs(y - .50) * 1.3, .25, 1)
    a *= (1 + (wb[None, None, :] - 1) * tone[..., None] * strength)
    a[..., 0] += .0020 * strength * tone
    a[..., 2] -= .0013 * strength * tone
    # Mild saturation reduction without collapsing wood grain or losing material colors.
    lum = a[..., 0] * .2126 + a[..., 1] * .7152 + a[..., 2] * .0722
    a = lum[..., None] + (a - lum[..., None]) * (1 - .056 * strength)
    # ONLY a confirmed actual window side can trigger a minimal ambient lift.
    # No beams, directional shadows, gradients with hard edges, or synthetic light sources.
    if light == 'window' and side != 'none':
        width, height = full_size
        if side in ('left','right'):
            axis = (np.arange(left, left+a.shape[1], dtype=np.float32) / max(1,width-1))[None, :, None]
            if side == 'right': axis = 1 - axis
        else:
            axis = (np.arange(top, top+a.shape[0], dtype=np.float32) / max(1,height-1))[:, None, None]
            if side == 'bottom': axis = 1 - axis
        a += .012 * strength * (1-axis)**2 * (1-lum[...,None])
    out = np.rint(np.clip(a,0,1)*255).astype(np.uint8)
    if src.shape[-1] == 4:
        return np.concatenate((out, src[...,3:4]), axis=-1)
    return out


def make_compare(before: Image.Image, after: Image.Image, out: Path, max_w=800) -> None:
    a = before.copy().convert('RGB')
    b = after.copy().convert('RGB')
    ratio = min(1.0, max_w/max(1,a.width))
    size = (max(1,round(a.width*ratio)), max(1,round(a.height*ratio)))
    a.thumbnail(size, Image.Resampling.LANCZOS)
    b.thumbnail(size, Image.Resampling.LANCZOS)
    margin=16; text_h=42
    canvas=Image.new('RGB',(a.width*2 + margin*3, a.height + text_h+margin*2), '#eeeae3')
    canvas.paste(a,(margin,text_h+margin))
    canvas.paste(b,(a.width + margin*2,text_h+margin))
    draw=ImageDraw.Draw(canvas)
    draw.text((margin,12),'BEFORE / ORIGINAL',fill='#333333')
    draw.text((a.width+margin*2,12),'AFTER / MUJI COLOR ONLY',fill='#333333')
    canvas.save(out,quality=93,subsampling=0)


def process(src:Path, dest:Path, compare:Path, report_path:Path, cfg:dict, light:str, side:str, source_sha:str) ->dict:
    """Produces files via atomic replaces; source is never opened for writing."""
    if light != 'window' and side != 'none':
        raise ValueError('Directional adjustment requires a verified actual window.')
    if src.resolve() in {dest.resolve(), compare.resolve(), report_path.resolve()}:
        raise ValueError('Source and output cannot be the same location')
    # Images are processed one at a time; tiles bound per-step peak NumPy memory.
    with Image.open(src) as raw:
        if raw.width*raw.height > int(cfg['max_megapixels']*1e6):
            raise ValueError('Image exceeds safety megapixel limit')
        if getattr(raw,'n_frames',1)>1:
            raise ValueError('Multi-frame TIFF/GIF is not supported: no pages will be silently dropped')
        if raw.mode not in ('RGB','RGBA','P','L','LA'):
            raise ValueError('Unsupported color mode (e.g. CMYK or 16-bit). Convert with a color-managed tool first: '+raw.mode)
        original=ImageOps.exif_transpose(raw)
        if original.mode not in ('RGB','RGBA'):
            mode = 'RGBA' if ('A' in original.getbands() or 'transparency' in original.info) else 'RGB'
            original=original.convert(mode)
        alpha = 'A' in original.getbands()
        size=original.size
        before=metrics(original)
        strength=float(cfg['strength'])
        if not (0 <= strength <= 1): raise ValueError('strength must be between 0 and 1')
        neutral=before['neutral_rgb_medians']
        if neutral is not None:
            med=np.array(neutral, dtype=np.float32)
            target=float(np.mean(med))
            wb=np.clip(target / np.maximum(med,.04),.972,1.028)
        else:
            wb=np.ones(3,dtype=np.float32)
        ev=float(np.clip((.43 - before['median_luminance'])*.53,-.08,.17)) * strength/.55
        ev=float(np.clip(ev,-.08,.17))
        result=Image.new('RGBA' if alpha else 'RGB',size)
        for top in range(0,size[1],512):
            for left in range(0,size[0],512):
                box=(left,top,min(left+512,size[0]),min(top+512,size[1]))
                tile=np.asarray(original.crop(box)).copy()
                graded=grade_tile(tile,cfg,wb,ev,light,side,left,top,size)
                result.paste(Image.fromarray(graded, mode='RGBA' if alpha else 'RGB'),box[:2])
        after=metrics(result)
        warnings=[]
        if light=='unknown': warnings.append('Light/window direction unverified: global color corrections only.')
        if light=='window' and side=='none': warnings.append('Window confirmed but location not set: no directional brightness added.')
        if before['brightest_border_hint_unverified']!='none' and side=='none':
            warnings.append('Bright border could be a real window OR bright wall/lamp. Visual confirmation required.')
        if before['neutral_sample_count']<250: warnings.append('Insufficient neutral surfaces for white balance estimation.')
        if after['highlight_fraction_luma_gt_0_98'] > max(.04,before['highlight_fraction_luma_gt_0_98']+.015):
            warnings.append('High highlight clipping; inspect window/outside view and white cabinets.')
        if before['dark_fraction_luma_lt_0_08'] > .15:
            warnings.append('Deep shadows may have noise; inspect at 100%.')
        if abs(after['mean_luminance']-before['mean_luminance'])>.09:
            warnings.append('Overall brightness changed materially; review against real scene.')
        if not warnings:
            warnings.append('Auto checks passed; human final inspection still recommended.')
        if alpha and dest.suffix.lower() in {'.jpg','.jpeg'}:
            raise ValueError('Cannot save transparent source to JPEG')
        dest.parent.mkdir(parents=True,exist_ok=True)
        compare.parent.mkdir(parents=True,exist_ok=True)
        report_path.parent.mkdir(parents=True,exist_ok=True)
        tmp_dest=dest.with_name(dest.stem+'.temp'+dest.suffix)
        tmp_cmp=compare.with_name(compare.stem+'.temp'+compare.suffix)
        tmp_report=report_path.with_suffix('.temp.json')
        save_kw={}
        if dest.suffix.lower() in {'.jpg','.jpeg'}: save_kw={'quality':int(cfg['jpeg_quality']),'subsampling':0}
        if dest.suffix.lower()=='.webp': save_kw={'lossless':alpha,'quality':int(cfg['jpeg_quality'])}
        if original.info.get('icc_profile'):
            save_kw['icc_profile']=original.info['icc_profile']
        report={
            'source':str(src), 'source_sha256':source_sha,
            'retouched':str(dest),'comparison':str(compare),
            'date_utc':utc(), 'mode':'strict non-generative per-pixel RGB color corrections',
            'geometry_and_objects':'unchanged by the algorithm; requires visual QA',
            'display_pixel_size_before':list(size),'pixel_size_after':list(result.size),
            'alpha_preserved':alpha,'metadata':'EXIF is not copied; embedded ICC retained when supported',
            'light_mode':light,'confirmed_window_side':side,'window_detection':'NOT available; user override required to add directional ambient correction',
            'light_position_hint_unverified':before['brightest_border_hint_unverified'],
            'exposure_ev':round(ev,4),'white_balance_factors':list(map(lambda x: round(float(x),4),wb)),
            'strength':strength, 'before':before,'after':after,
            'warnings':warnings,'manual_review_needed':any('inspect' in w.lower() or 'required' in w.lower() or 'unverified' in w.lower() for w in warnings),
            'original_untouched':True
        }
        try:
            result.save(tmp_dest,**save_kw)
            with Image.open(tmp_dest) as check:
                if check.size!=size:
                    raise ValueError('Generated file has wrong dimensions')
            make_compare(original,result,tmp_cmp,int(cfg['comparison_max_width']))
            tmp_report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            os.replace(tmp_dest,dest)
            os.replace(tmp_cmp,compare)
            os.replace(tmp_report,report_path)
        finally:
            for t in (tmp_dest,tmp_cmp,tmp_report):
                try: t.unlink(missing_ok=True)
                except OSError: pass
        return report
