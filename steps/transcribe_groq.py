#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Transcribe audio to Spanish SRT using Groq Whisper API."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Callable, Optional

try:
    from groq import Groq
except ImportError:
    Groq = None  # type: ignore

from config import Config
from ffmpeg_util import run_ffmpeg
from srt_parser import SRTEntry, serialize_srt

ProgressCb = Optional[Callable[[float, str], None]]
MAX_BYTES = 24 * 1024 * 1024  # Groq ~25MB limit
CHUNK_SECONDS = 600  # 10 dakika


def _get_client(api_key: str) -> "Groq":
    if Groq is None:
        raise RuntimeError("groq paketi yüklü değil. pip install groq")
    return Groq(api_key=api_key)


def _format_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _split_audio(audio_path: Path, out_dir: Path) -> list[tuple[Path, float]]:
    """Uzun dosyaları parçalara böler; (path, offset_seconds) döner."""
    if audio_path.stat().st_size <= MAX_BYTES:
        return [(audio_path, 0.0)]

    pattern = out_dir / "chunk_%03d.mp3"
    run_ffmpeg(
        [
            "-y",
            "-i",
            str(audio_path),
            "-f",
            "segment",
            "-segment_time",
            str(CHUNK_SECONDS),
            "-acodec",
            "copy",
            str(pattern),
        ]
    )
    chunks = sorted(out_dir.glob("chunk_*.mp3"))
    if not chunks:
        return [(audio_path, 0.0)]

    result: list[tuple[Path, float]] = []
    for idx, chunk in enumerate(chunks):
        result.append((chunk, idx * CHUNK_SECONDS))
    return result


def _transcribe_file(
    client: Groq,
    audio_path: Path,
    model: str,
    offset: float,
    *,
    language: str,
) -> list[SRTEntry]:
    with open(audio_path, "rb") as fh:
        data = fh.read()

    result = client.audio.transcriptions.create(
        file=(audio_path.name, data),
        model=model,
        language=language,
        response_format="verbose_json",
        temperature=0.0,
    )

    segments: list[dict] = []
    if hasattr(result, "segments") and result.segments:
        segments = list(result.segments)
    elif isinstance(result, dict):
        segments = result.get("segments") or []
    else:
        raw = getattr(result, "model_dump", lambda: None)()
        if raw and isinstance(raw, dict):
            segments = raw.get("segments") or []

    entries: list[SRTEntry] = []
    for seg in segments:
        if isinstance(seg, dict):
            start = float(seg.get("start", 0)) + offset
            end = float(seg.get("end", 0)) + offset
            text = (seg.get("text") or "").strip()
        else:
            start = float(getattr(seg, "start", 0)) + offset
            end = float(getattr(seg, "end", 0)) + offset
            text = (getattr(seg, "text", "") or "").strip()
        if not text:
            continue
        entries.append(
            SRTEntry(
                index=len(entries) + 1,
                start=_format_timestamp(start),
                end=_format_timestamp(end),
                text=text,
            )
        )

    if not entries:
        text = ""
        if hasattr(result, "text"):
            text = (result.text or "").strip()
        elif isinstance(result, dict):
            text = (result.get("text") or "").strip()
        if text:
            entries.append(
                SRTEntry(
                    index=1,
                    start=_format_timestamp(offset),
                    end=_format_timestamp(offset + 5),
                    text=text,
                )
            )
    return entries


def transcribe_to_srt(
    audio_path: Path,
    output_path: Path,
    config: Config,
    progress_cb: ProgressCb = None,
    *,
    language: str | None = None,
) -> Path:
    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path

    if not config.groq_api_key:
        raise RuntimeError("GROQ_API_KEY tanımlı değil.")

    client = _get_client(config.groq_api_key)
    model = config.groq_whisper_model
    lang = (language or config.source_lang or "es").strip().lower()
    if lang not in ("es", "en"):
        lang = "es"

    with tempfile.TemporaryDirectory(prefix="groq_chunks_") as tmp:
        tmp_dir = Path(tmp)
        chunks = _split_audio(audio_path, tmp_dir)
        all_entries: list[SRTEntry] = []

        for idx, (chunk_path, offset) in enumerate(chunks):
            if progress_cb:
                progress_cb((idx + 0.2) / len(chunks), f"Transkripsiyon {idx + 1}/{len(chunks)}")
            chunk_entries = _transcribe_file(
                client, chunk_path, model, offset, language=lang
            )
            all_entries.extend(chunk_entries)
            if progress_cb:
                progress_cb((idx + 1) / len(chunks), f"Transkripsiyon {idx + 1}/{len(chunks)}")

    if not all_entries:
        raise RuntimeError("Groq Whisper hiç altyazı satırı üretmedi.")

    for i, entry in enumerate(all_entries, start=1):
        entry.index = i

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialize_srt(all_entries), encoding="utf-8")
    return output_path
