#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Application launcher — web arayüzünü başlatır ve tarayıcıyı açar."""
from __future__ import annotations

import argparse
import shutil
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from config import ROOT, get_config
from web.server import create_app


def _open_browser(host: str, port: int) -> None:
    time.sleep(1.2)
    url = f"http://127.0.0.1:{port}" if host in ("0.0.0.0", "::") else f"http://{host}:{port}"
    webbrowser.open(url)


def main() -> int:
    parser = argparse.ArgumentParser(description="El Clon Türkçe Altyazı Platformu")
    parser.add_argument("--host", default=None, help="Dinleme adresi")
    parser.add_argument("--port", type=int, default=None, help="Port")
    parser.add_argument("--no-browser", action="store_true", help="Tarayıcıyı otomatik açma")
    args = parser.parse_args()

    config = get_config()
    host = args.host or config.web_host
    port = args.port or config.web_port

    env_path = ROOT / ".env"
    env_example = ROOT / ".env.example"
    if not env_path.is_file() and env_example.is_file():
        shutil.copy2(env_example, env_path)
        print(f"[BILGI] .env oluşturuldu: {env_path}")

    if not config.groq_api_key:
        env_path = ROOT / ".env"
        print("[UYARI] GROQ_API_KEY tanımlı değil.")
        print(f"        {env_path} dosyasına anahtarınızı ekleyin.")
        print("        Hazır bölümler izlenebilir; yeni çeviri başlatılamaz.")

    app = create_app(config)

    print("=" * 52)
    print("  El Clon — Türkçe Altyazı Platformu")
    print("=" * 52)
    print(f"  Video kaynağı: {config.video_base_url}")
    print(f"  Yerel adres:   http://127.0.0.1:{port}")
    if host in ("0.0.0.0", "::"):
        try:
            lan = socket.gethostbyname(socket.gethostname())
            if lan and not lan.startswith("127."):
                print(f"  Ağ adresi:     http://{lan}:{port}")
        except OSError:
            pass
    print("=" * 52)

    if not args.no_browser:
        threading.Thread(target=_open_browser, args=(host, port), daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
