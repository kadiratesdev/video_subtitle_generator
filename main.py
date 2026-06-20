#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI entry point."""
from __future__ import annotations

import argparse
import sys

from app import main as serve_main
from config import get_config
from catalog import fetch_episodes
from job_manager import JobManager
from pipeline import process_episode


def cmd_serve(args: argparse.Namespace) -> int:
    sys.argv = ["app.py"]
    if args.host:
        sys.argv.extend(["--host", args.host])
    if args.port:
        sys.argv.extend(["--port", str(args.port)])
    if args.no_browser:
        sys.argv.append("--no-browser")
    return serve_main()


def cmd_process(args: argparse.Namespace) -> int:
    config = get_config()
    if not config.groq_api_key:
        print("[HATA] GROQ_API_KEY gerekli.")
        return 1

    jobs = JobManager(config)
    state = jobs.state
    settings = jobs.get_settings()

    targets = fetch_episodes(config, settings)
    if args.episode:
        targets = [ep for ep in catalog if ep.id == args.episode or ep.filename == args.episode]
        if not targets:
            print(f"[HATA] Bölüm bulunamadı: {args.episode}")
            return 1

    if args.limit:
        targets = targets[: args.limit]

    ok = 0
    fail = 0
    for ep in targets:
        if process_episode(ep, config, state, source_lang=settings.source_lang):
            ok += 1
        else:
            fail += 1

    print(f"\n[ÖZET] başarılı={ok} başarısız={fail}")
    return 0 if fail == 0 else 1


def cmd_status(_: argparse.Namespace) -> int:
    config = get_config()
    jobs = JobManager(config)
    summary = jobs.summary()
    settings = jobs.settings_public()
    print("Platform durumu:")
    print(f"  Kaynak:     {settings['mode']} — {settings['remoteUrl'] if settings['mode'] == 'remote' else settings['localPath']}")
    print(f"  Kaynak dil: {settings['sourceLangLabel']}")
    print(f"  Videolar:   {config.videos_dir}")
    print(f"  Çıktı:      {config.output_dir}")
    print(f"  Toplam:     {summary['total']}")
    print(f"  Hazır:      {summary['ready']}")
    print(f"  Bekleyen:   {summary['pending']}")
    print(f"  İşleniyor:  {summary['processing']}")
    print(f"  Başarısız:  {summary['failed']}")
    print(f"  Groq key:   {'evet' if config.groq_api_key else 'HAYIR'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GenSub altyazı platformu")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Web arayüzünü başlat")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--no-browser", action="store_true")
    serve.set_defaults(func=cmd_serve)

    process = sub.add_parser("process", help="CLI ile bölüm işle")
    process.add_argument("--limit", type=int, default=None)
    process.add_argument("--episode", type=str, default=None)
    process.set_defaults(func=cmd_process)

    status = sub.add_parser("status", help="Durum özeti")
    status.set_defaults(func=cmd_status)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
