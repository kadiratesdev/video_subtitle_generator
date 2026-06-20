#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FFmpeg helper. Prefers system ffmpeg (installed), falls back to imageio bundle."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg


class NoAudioStreamError(RuntimeError):
    """Video dosyasında ses kanalı bulunamadı."""


def ffmpeg_path() -> str:
    bundled = imageio_ffmpeg.get_ffmpeg_exe()
    if getattr(sys, "frozen", False):
        return bundled
    # Geliştirmede sistem ffmpeg daha hızlı olabilir; yoksa paket içindekine düş
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        return sys_ffmpeg
    return bundled


def ffprobe_path() -> str | None:
    ffmpeg = Path(ffmpeg_path())
    for name in ("ffprobe.exe", "ffprobe"):
        candidate = ffmpeg.with_name(name)
        if candidate.is_file():
            return str(candidate)
    return shutil.which("ffprobe")


def _format_ffmpeg_error(stderr: str) -> str:
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    important = [
        line
        for line in lines
        if re.search(
            r"(?i)error|invalid|failed|does not contain|no such file|permission denied",
            line,
        )
    ]
    if important:
        return "\n".join(important[-6:])
    return "\n".join(lines[-8:])


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
        stderr = _format_ffmpeg_error(result.stderr or "")
        raise RuntimeError(f"ffmpeg failed ({result.returncode}): {stderr}")
    return result


def _probe_with_ffprobe(video_path: Path) -> tuple[bool | None, float | None]:
    probe = ffprobe_path()
    if not probe:
        return None, None

    result = subprocess.run(
        [
            probe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type",
            "-of",
            "json",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return None, None

    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None, None

    streams = data.get("streams") or []
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    duration_raw = (data.get("format") or {}).get("duration")
    duration = float(duration_raw) if duration_raw else None
    return has_audio, duration


def _probe_with_ffmpeg(video_path: Path) -> tuple[bool, float | None]:
    result = run_ffmpeg(
        ["-hide_banner", "-i", str(video_path)],
        check=False,
    )
    text = f"{result.stderr or ''}\n{result.stdout or ''}"
    has_audio = bool(re.search(r"Stream #\d+:\d+.*\bAudio:", text))
    duration = None
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if match:
        hours, minutes, seconds = match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return has_audio, duration


def video_has_audio(video_path: Path) -> bool:
    has_audio, _ = _probe_with_ffprobe(video_path)
    if has_audio is not None:
        return has_audio
    has_audio_fb, _ = _probe_with_ffmpeg(video_path)
    return has_audio_fb


def video_duration_seconds(video_path: Path) -> float | None:
    _, duration = _probe_with_ffprobe(video_path)
    if duration is not None:
        return duration
    _, duration = _probe_with_ffmpeg(video_path)
    return duration


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
