#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract mono 16kHz audio from video (MP3 for Groq API size limits)."""
from __future__ import annotations

from pathlib import Path

from ffmpeg_util import ensure_parent, run_ffmpeg


def extract_audio(video_path: Path, output_path: Path) -> Path:
    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path

    ensure_parent(output_path)
    suffix = output_path.suffix.lower()

    if suffix == ".wav":
        run_ffmpeg(
            [
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "16000",
                "-ac",
                "1",
                str(output_path),
            ]
        )
    else:
        # MP3 — Groq Whisper 25MB limitine uygun
        run_ffmpeg(
            [
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-acodec",
                "libmp3lame",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-b:a",
                "64k",
                str(output_path),
            ]
        )
    return output_path
