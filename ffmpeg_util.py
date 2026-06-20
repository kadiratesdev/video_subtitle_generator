#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FFmpeg helper. Prefers system ffmpeg (installed), falls back to imageio bundle."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg


def ffmpeg_path() -> str:
    bundled = imageio_ffmpeg.get_ffmpeg_exe()
    if getattr(sys, "frozen", False):
        return bundled
    # Geliştirmede sistem ffmpeg daha hızlı olabilir; yoksa paket içindekine düş
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        return sys_ffmpeg
    return bundled


def run_ffmpeg(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = [ffmpeg_path(), *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(f"ffmpeg failed ({result.returncode}): {stderr[-2000:]}")
    return result


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
