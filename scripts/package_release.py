#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dist/GenSub klasörünü GitHub Release için zip dosyasına paketler."""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "GenSub"
RELEASE_DIR = ROOT / "dist" / "release"

SKIP_NAMES = {".gitkeep"}


def should_skip(path: Path) -> bool:
    return path.name in SKIP_NAMES


def make_zip(out_path: Path) -> float:
    if not DIST.is_dir():
        raise FileNotFoundError(f"Dağıtım klasörü bulunamadı: {DIST}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file_path in sorted(DIST.rglob("*")):
            if not file_path.is_file() or should_skip(file_path):
                continue
            arcname = Path("GenSub") / file_path.relative_to(DIST)
            zf.write(file_path, arcname.as_posix())

    return out_path.stat().st_size / (1024 * 1024)


def main() -> int:
    parser = argparse.ArgumentParser(description="GenSub Windows dağıtım zip'i oluştur")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=RELEASE_DIR / "GenSub-windows-x64.zip",
        help="Çıktı zip yolu",
    )
    args = parser.parse_args()

    try:
        size_mb = make_zip(args.output.resolve())
    except FileNotFoundError as err:
        print(f"[HATA] {err}")
        print("Önce build.bat ile EXE derleyin.")
        return 1

    print(f"[OK] {args.output}")
    print(f"Boyut: {size_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
