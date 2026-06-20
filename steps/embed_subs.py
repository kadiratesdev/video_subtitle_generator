#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Embed soft Turkish subtitles into MP4."""
from __future__ import annotations

from pathlib import Path

from ffmpeg_util import ensure_parent, run_ffmpeg


def embed_soft_subs(video_path: Path, srt_path: Path, output_path: Path) -> Path:
    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path

    ensure_parent(output_path)
    run_ffmpeg(
        [
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(srt_path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-map",
            "1:0",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-c:s",
            "mov_text",
            "-metadata:s:s:0",
            "language=tur",
            "-disposition:s:0",
            "default",
            str(output_path),
        ]
    )
    return output_path
