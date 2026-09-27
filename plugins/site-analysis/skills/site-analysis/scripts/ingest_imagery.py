#!/usr/bin/env python3
"""Inventory user imagery and extract geolocation from EXIF where present.

Map/navigation screenshots usually have no GPS, but camera/phone site photos often
do. This helper writes a manifest that the analysis workflow can use to place photo
viewpoints, and copies images into a stable output folder for reference.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

try:
    from PIL import Image, ExifTags
except ImportError:
    raise SystemExit("Pillow is required. Run the main analyzer once or install Pillow.")


IMG_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".webp"}


def _to_decimal(value, ref) -> float | None:
    try:
        parts = [float(v) for v in value]
    except Exception:
        return None
    if len(parts) < 2:
        return None
    degrees, minutes = parts[0], parts[1]
    seconds = parts[2] if len(parts) > 2 else 0.0
    decimal = degrees + minutes / 60.0 + seconds / 3600.0
    if ref in {"S", "W"}:
        decimal = -decimal
    return decimal


def extract_image_meta(path: Path) -> dict:
    meta = {
        "path": str(path),
        "name": path.name,
        "gps": None,
        "datetime": None,
        "make": None,
        "model": None,
    }
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if exif:
                for tag_id, value in exif.items():
                    tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                    if tag_name == "DateTimeOriginal":
                        meta["datetime"] = str(value)
                    elif tag_name == "Make":
                        meta["make"] = str(value)
                    elif tag_name == "Model":
                        meta["model"] = str(value)
            gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo) if exif else None
            if gps_ifd:
                lat = _to_decimal(gps_ifd.get(2), gps_ifd.get(1))
                lon = _to_decimal(gps_ifd.get(4), gps_ifd.get(3))
                alt = gps_ifd.get(6)
                if lat is not None and lon is not None:
                    meta["gps"] = {
                        "lat": lat,
                        "lon": lon,
                        "altitude_m": float(alt) if isinstance(alt, (int, float)) else None,
                    }
    except Exception as exc:
        meta["error"] = str(exc)
    return meta


def main() -> int:
    p = argparse.ArgumentParser(description="Inventory site imagery and extract EXIF GPS.")
    p.add_argument("--input-dir", required=True)
    p.add_argument("--out-dir", default="site-analysis-output")
    p.add_argument("--copy", action="store_true", help="Copy images into out-dir/photos")
    args = p.parse_args()

    input_dir = Path(args.input_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    items = []
    files = sorted(input_dir.rglob("*"))
    for f in files:
        if f.is_file() and f.suffix.lower() in IMG_EXTS:
            meta = extract_image_meta(f)
            items.append(meta)

    if args.copy:
        photos = out_dir / "photos"
        photos.mkdir(parents=True, exist_ok=True)
        for i, meta in enumerate(items, 1):
            src = Path(meta["path"])
            ext = src.suffix.lower() or ".img"
            dst = photos / f"{i:03d}_{src.stem}{ext}"
            try:
                shutil.copy2(src, dst)
                meta["copied_to"] = str(dst)
            except Exception as exc:
                meta["copy_error"] = str(exc)

    manifest = out_dir / "imagery_manifest.json"
    manifest.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[site-analysis] Indexed {len(items)} images -> {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
