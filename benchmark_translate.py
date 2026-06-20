#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Benchmark: compare OLD vs FAST translator on RTX 3080 Ti.

Usage:
    python benchmark_translate.py                 # uses existing es.srt
    python benchmark_translate.py --lines 100     # random subset
    python benchmark_translate.py --ep 3_3       # specific episode
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from config import get_config


def load_test_lines(config, episode: str | None = None, max_lines: int | None = None):
    """Load Spanish subtitle lines for benchmarking."""
    if episode:
        ep_dir = config.output_dir / episode
        srt_path = ep_dir / "es.srt"
    else:
        # Find any es.srt
        srt_path = None
        for d in config.output_dir.iterdir():
            candidate = d / "es.srt"
            if candidate.exists():
                srt_path = candidate
                break

    if not srt_path or not srt_path.exists():
        print("[BENCH] Hata: es.srt bulunamadi. Once bir bolum isleyin.")
        sys.exit(1)

    from srt_parser import parse_srt
    entries = parse_srt(srt_path.read_text(encoding="utf-8"))
    texts = [e.text for e in entries]

    if max_lines and max_lines < len(texts):
        random.seed(42)
        texts = random.sample(texts, max_lines)

    print(f"[BENCH] {srt_path.name}: {len(texts)} satir yuklendi")
    return texts


def benchmark_old(texts: list[str], config) -> dict:
    """Benchmark original NLLBTranslator (batch=4, beam=4)."""
    print("\n" + "=" * 60)
    print("[BENCH] MEVCUT (eski) mod: NLLBTranslator batch=4, beam=4")
    print("=" * 60)

    from steps.translate_srt import NLLBTranslator

    t_load = time.perf_counter()
    old = NLLBTranslator(
        model_name=config.translator_model,
        device=config.translator_device,
        batch_size=4,
    )
    load_time = time.perf_counter() - t_load

    # Warm up
    _ = old._translate_texts(["Hola"], "Spanish", "Turkish")

    t0 = time.perf_counter()
    result = old.translate_with_context(texts, context_lines=3)
    elapsed = time.perf_counter() - t0

    return {
        "label": "Eski (batch=4, beam=4)",
        "load_time": load_time,
        "translate_time": elapsed,
        "lines": len(texts),
        "lines_per_sec": len(texts) / max(elapsed, 0.001),
        "sample": result[:5] if result else [],
    }


def benchmark_fast(texts: list[str], config) -> dict:
    """Benchmark FastNLLBTranslator (batch=32, greedy, BT, compile)."""
    print("\n" + "=" * 60)
    print("[BENCH] HIZLI (yeni) mod: FastNLLBTranslator batch=32, greedy, BT")
    print("=" * 60)

    from steps.translate_srt_fast import FastNLLBTranslator

    t_load = time.perf_counter()
    fast = FastNLLBTranslator(
        model_name=config.translator_model,
        device=config.translator_device,
        batch_size=48,
        use_bettertransformer=True,
        use_compile=False,
    )
    load_time = time.perf_counter() - t_load

    # Warm up already done in __init__

    t0 = time.perf_counter()
    result = fast.translate_with_context(texts, context_lines=3)
    elapsed = time.perf_counter() - t0

    return {
        "label": "Hizli (batch=32, greedy, BT, compile)",
        "load_time": load_time,
        "translate_time": elapsed,
        "lines": len(texts),
        "lines_per_sec": len(texts) / max(elapsed, 0.001),
        "sample": result[:5] if result else [],
    }


def print_comparison(old: dict, new: dict, test_texts: list[str]):
    """Print formatted comparison table."""
    print("\n" + "=" * 60)
    print("BENCHMARK SONUCLARI")
    print("=" * 60)

    print(f"\n  Test verisi:    {len(test_texts)} satir")
    print(f"  GPU:             RTX 3080 Ti (12 GB)")
    print()

    # Header
    print(f"  {'Metrik':<25} {'Eski':>14} {'Yeni (Hizli)':>14} {'Fark':>10}")
    print(f"  {'-'*25} {'-'*14} {'-'*14} {'-'*10}")

    # Rows
    rows = [
        ("Model Yuklenme", f"{old['load_time']:.1f}s", f"{new['load_time']:.1f}s", ""),
        ("Ceviri Suresi", f"{old['translate_time']:.1f}s", f"{new['translate_time']:.1f}s",
         f"{(1 - new['translate_time']/max(old['translate_time'],0.001))*100:+.0f}%"),
        ("Satir/sn", f"{old['lines_per_sec']:.0f}", f"{new['lines_per_sec']:.0f}",
         f"{(new['lines_per_sec']/max(old['lines_per_sec'],0.001)-1)*100:+.0f}%"),
    ]

    for label, old_val, new_val, diff in rows:
        print(f"  {label:<25} {old_val:>14} {new_val:>14} {diff:>10}")

    # Time estimate for full episode
    typical_lines = 575
    old_ep = typical_lines / max(old['lines_per_sec'], 0.001)
    new_ep = typical_lines / max(new['lines_per_sec'], 0.001)

    print(f"\n  Tahmini sure (575 satirlik bolum):")
    print(f"    Eski:  {old_ep/60:.1f} dakika")
    print(f"    Yeni:  {new_ep/60:.1f} dakika")
    print(f"    Tasarruf: {(1 - new_ep/max(old_ep, 0.001))*100:.0f}%")

    # Sample quality check
    print(f"\n  --- Kalite Ornegi (ilk 5 satir) ---")
    for i, (src, old_tr, new_tr) in enumerate(
        zip(test_texts[:5], old.get("sample", []), new.get("sample", []))
    ):
        print(f"\n  [{i+1}] ES: {src[:80]}")
        print(f"      ESKI:  {old_tr[:80]}")
        print(f"      YENI:  {new_tr[:80]}")

    print()


def main():
    parser = argparse.ArgumentParser(description="Translator benchmark")
    parser.add_argument("--lines", type=int, default=50, help="Test satir sayisi (default: 50)")
    parser.add_argument("--ep", type=str, default=None, help="Bolum adi (or. 3_3)")
    parser.add_argument("--fast-only", action="store_true", help="Sadece hizli mod")
    parser.add_argument("--old-only", action="store_true", help="Sadece eski mod")
    args = parser.parse_args()

    config = get_config()
    texts = load_test_lines(config, args.ep, args.lines)

    old_result = None
    new_result = None

    if not args.fast_only:
        old_result = benchmark_old(texts, config)

    if not args.old_only:
        new_result = benchmark_fast(texts, config)

    if old_result and new_result:
        print_comparison(old_result, new_result, texts)
    elif new_result:
        print(f"\n[HIZLI] {new_result['translate_time']:.1f}s  =  "
              f"{new_result['lines_per_sec']:.0f} satir/sn")
    elif old_result:
        print(f"\n[ESKI] {old_result['translate_time']:.1f}s  =  "
              f"{old_result['lines_per_sec']:.0f} satir/sn")


if __name__ == "__main__":
    main()
