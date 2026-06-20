#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PyInstaller sonrası dağıtım klasörünü kullanıcıya hazır hale getirir."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "ElClon"

KULLANIM = """
El Clon — Türkçe Altyazı Platformu
==================================

KURULUM GEREKMİYOR
  Python, pip veya ffmpeg kurmanıza gerek yok.
  CUDA da gerekmez (Groq bulut API kullanılır).

İLK ÇALIŞTIRMA
  1. ElClon.exe dosyasını çift tıklayın (veya Calistir.bat)
  2. Tarayıcı otomatik açılır: http://127.0.0.1:8765
  3. .env dosyasına GROQ_API_KEY ekleyin (yeni çeviri için zorunlu)
     Anahtar: https://console.groq.com

KLASÖRLER (exe ile aynı dizinde oluşur)
  videos/   — indirilen videolar
  output/   — altyazılar ve işlem durumu

NOT
  Tüm klasörü (ElClon.exe + _internal) birlikte kopyalayın.
  Sadece exe dosyasını taşımayın.

İSTEĞE BAĞLI — YEREL WHISPER (CUDA)
  Bu paket Groq API ile çalışır. Yerel Whisper için kaynak kodundan
  requirements-gpu.txt kurulumu gerekir; bu exe'ye dahil değildir.
"""


def main() -> int:
    if not DIST.is_dir():
        print(f"[HATA] Dağıtım klasörü bulunamadı: {DIST}")
        return 1

    env_example = ROOT / ".env.example"
    env_target = DIST / ".env"
    if env_example.is_file() and not env_target.is_file():
        shutil.copy2(env_example, env_target)
        print(f"[OK] .env oluşturuldu: {env_target}")

    for folder in ("videos", "output"):
        path = DIST / folder
        path.mkdir(exist_ok=True)
        print(f"[OK] {folder}/")

    kullanim_path = DIST / "KULLANIM.txt"
    kullanim_path.write_text(KULLANIM.strip() + "\n", encoding="utf-8")
    print(f"[OK] {kullanim_path.name}")

    launcher = DIST / "Calistir.bat"
    launcher.write_text(
        "@echo off\n"
        "cd /d \"%~dp0\"\n"
        "start \"\" \"ElClon.exe\"\n",
        encoding="utf-8",
    )
    print(f"[OK] {launcher.name}")

    total_mb = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file()) / (1024 * 1024)
    print(f"\nPaket hazır: {DIST}")
    print(f"Boyut: {total_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
