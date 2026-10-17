#!/usr/bin/env python3
"""Deterministic MUJI-inspired color grade for genuine renovation photos.

No object detection, generation, masking, geometry operations, inpainting, or
invented sunbeams. The optional directional change is only a *gentle diffuse*
brightness transition and must be anchored to a visibly confirmed real window.
"""

import argparse
import json
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageOps, ImageDraw, ImageFont
except ImportError as exc:
    raise SystemExit("Missing dependency. Run: python -m pip install Pillow numpy") from exc


SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}


def grade_rgb(rgb: np.ndarray, light: str, window_side: str, strength: float) -> np.ndarray:
    """Only modify RGB values at identical (x,y) positions."""
    p = rgb.astype(np.float32) / 255.0
    y = np.tensordot(p, np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axes=([-1], [0]))

    # Conservative exposure lift; less lift when the room's light is unknown.
    exposure = {"window": 0.115, "no-window": 0.090, "unknown": 0.070}[light]
    p *= 2.0 ** (exposure * strength)
    # Raise near-shadow information without flattening the entire scene.
    p += (0.055 * strength * np.power(1.0 - y, 2.2))[..., None]
    # Gently compress intense whites to avoid a chalky window/wall look.
    highlight = np.clip((y - 0.70) / 0.30, 0.0, 1.0) ** 2
    p -= (0.020 * strength * highlight)[..., None]

    # Neutral-warm, near invisible white balance; no tint/wood reconstruction.
    mid = np.clip(1.0 - np.abs(y - 0.50) * 1.5, 0.2, 1.0)
    warmth = 0.0060 * strength * mid
    p[..., 0] += warmth
    p[..., 2] -= warmth * 0.62

    # Fine, low-key desaturation, not a grey or yellow filter.
    yi = np.sum(p * [0.2126, 0.7152, 0.0722], axis=-1, keepdims=True)
    p = yi + (p - yi) * (1.0 - 0.065 * strength)

    # Only when an actual window side was confirmed by a person/vision analysis:
    # a smooth ambient transition without beams, highlights, shadows or shapes.
    if light == "window" and window_side != "none":
        h, w, _ = p.shape
        if window_side in ("left", "right"):
            dist = np.linspace(0, 1, w, dtype=np.float32)[None, :]
            if window_side == "right":
                dist = 1 - dist
            dist = np.broadcast_to(dist, (h, w))
        else:
            dist = np.linspace(0, 1, h, dtype=np.float32)[:, None]
            if window_side == "bottom":
                dist = 1 - dist
            dist = np.broadcast_to(dist, (h, w))
        diffuse = ((1.0 - dist) ** 2)[..., None]
        p += diffuse * (0.019 * strength) * (0.50 + 0.50 * (1.0 - y[..., None]))

    return np.rint(np.clip(p, 0.0, 1.0) * 255.0).astype(np.uint8)


def compare_image(before: Image.Image, after: Image.Image, filename: Path) -> None:
    # Diagnostic only. Final photo is saved separately at identical resolution.
    a = before.convert("RGB")
    b = after.convert("RGB")
    max_w = 900
    scale = min(1.0, max_w / max(1, a.width))
    newsize = (max(1, round(a.width * scale)), max(1, round(a.height * scale)))
    if newsize != a.size:
        a = a.resize(newsize, Image.Resampling.LANCZOS)
        b = b.resize(newsize, Image.Resampling.LANCZOS)
    margin, label_h = 12, 36
    canvas = Image.new("RGB", (a.width * 2 + margin * 3, a.height + label_h + margin * 2), "#f2f0ec")
    canvas.paste(a, (margin, label_h + margin))
    canvas.paste(b, (a.width + margin * 2, label_h + margin))
    d = ImageDraw.Draw(canvas)
    d.text((margin + 2, 12), "ORIGINAL", fill="#333333")
    d.text((a.width + margin * 2 + 2, 12), "RETOUCHED (NON-GENERATIVE)", fill="#333333")
    canvas.save(filename, quality=90)


def process_one(src: Path, dest: Path, light: str, side: str, strength: float) -> None:
    if src.resolve() == dest.resolve():
        raise ValueError("Never overwrite the original image. Choose a new output filename.")
    with Image.open(src) as raw:
        original = ImageOps.exif_transpose(raw)
        # Preserve the already-composited alpha mask if any. Convert to RGB for grading.
        is_alpha = "A" in original.getbands() or "transparency" in original.info
        normalized = original.convert("RGBA" if is_alpha else "RGB")
        raw_arr = np.asarray(normalized).copy()
        before_rgb = raw_arr[..., :3]
        output_rgb = grade_rgb(before_rgb, light, side, strength)
        if is_alpha:
            output_rgba = np.dstack((output_rgb, raw_arr[..., 3]))
            result = Image.fromarray(output_rgba, "RGBA")
        else:
            result = Image.fromarray(output_rgb, "RGB")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.suffix.lower() in (".jpg", ".jpeg") and is_alpha:
            raise ValueError("Source image has transparency. Use PNG output to preserve alpha.")
        if dest.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"):
            raise ValueError("Output must be PNG, JPEG, WEBP or TIFF.")
        # Output in RGB/sRGB-like channel values; avoid copying inconsistent ICC profiles.
        save_options = {"quality": 94, "subsampling": 0} if dest.suffix.lower() in (".jpg", ".jpeg") else {}
        result.save(dest, **save_options)
        stem = dest.with_suffix("")
        compare_path = Path(f"{stem}_compare.jpg")
        report_path = Path(f"{stem}_report.json")
        compare_image(normalized, result, compare_path)
        report = {
            "original": str(src), "retouched": str(dest),
            "comparison": str(compare_path),
            "method": "non-generative per-pixel RGB grading (no geometry changes)",
            "pixel_size_before": [original.width, original.height],
            "pixel_size_after": [result.width, result.height],
            "light_source_classification": light,
            "confirmed_window_side": side if light == "window" else "none",
            "strength": strength,
            "imagined_sunbeams_or_objects_added": False,
            "checks_required": "Visual before/after comparison: white balance, materials, clipping, daylight realism; pixel script does not replace inspection.",
            "note": "Original preserved; EXIF/ICC may not be retained. Exports are 8-bit RGB(A); preserve originals for archival use."
        }
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"result": str(dest), "compare": str(compare_path), "report": str(report_path)}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="Faithful MUJI-inspired color grading, no invented objects or sunlight.")
    parser.add_argument("input", type=Path, help="File or directory of photos")
    parser.add_argument("output", type=Path, help="New file or output directory. Original never overwritten.")
    parser.add_argument("--light", choices=["window", "no-window", "unknown"], default="unknown",
                        help="Only use window when a real window is visually confirmed")
    parser.add_argument("--window-side", choices=["none", "left", "right", "top", "bottom"], default="none",
                        help="Position of REAL confirmed window light; defaults to none")
    parser.add_argument("--strength", type=float, default=0.55, help="Adjustment intensity, 0..1")
    args = parser.parse_args()
    if not (0 <= args.strength <= 1):
        parser.error("--strength must be between 0 and 1")
    if args.light != "window" and args.window_side != "none":
        parser.error("--window-side requires --light window")
    if not args.input.exists():
        parser.error(f"No such input: {args.input}")
    if args.input.is_file():
        if args.output.is_dir() or args.output.suffix == "":
            args.output.mkdir(parents=True, exist_ok=True)
            dest = args.output / f"{args.input.stem}_muji.png"
        else:
            dest = args.output
        process_one(args.input, dest, args.light, args.window_side, args.strength)
    else:
        # Batch defaults to no window-side assumptions: apply only values user confirmed.
        if args.output.resolve() == args.input.resolve():
            parser.error("Output directory must differ from source directory")
        args.output.mkdir(parents=True, exist_ok=True)
        photos = sorted(p for p in args.input.iterdir() if p.is_file() and p.suffix.lower() in SUFFIXES)
        if not photos:
            parser.error("No supported photos found")
        failures = []
        for p in photos:
            try:
                process_one(p, args.output / f"{p.stem}_muji.png", args.light, args.window_side, args.strength)
            except Exception as exc:
                failures.append(f"{p.name}: {exc}")
        if failures:
            raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
