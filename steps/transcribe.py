#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Transcribe audio to Spanish SRT using faster-whisper."""
from __future__ import annotations

from pathlib import Path

from faster_whisper import WhisperModel

from config import Config
from srt_parser import SRTEntry, serialize_srt

_model: WhisperModel | None = None
_model_key: tuple[str, str, str] | None = None


def _get_model(config: Config) -> WhisperModel:
    global _model, _model_key
    key = (config.whisper_model, config.whisper_device, config.whisper_compute_type)
    if _model is None or _model_key != key:
        print(
            f"[WHISPER] Model yukleniyor: {config.whisper_model} "
            f"({config.whisper_device}/{config.whisper_compute_type})"
        )
        _model = WhisperModel(
            config.whisper_model,
            device=config.whisper_device,
            compute_type=config.whisper_compute_type,
        )
        _model_key = key
    return _model


def _format_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def transcribe_to_srt(audio_path: Path, output_path: Path, config: Config) -> Path:
    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path

    model = _get_model(config)
    segments, info = model.transcribe(
        str(audio_path),
        language="es",
        task="transcribe",
        vad_filter=True,
        beam_size=5,
        best_of=5,
        condition_on_previous_text=True,
        temperature=0,
        no_speech_threshold=0.6,
    )
    print(f"[WHISPER] Algilanan dil: {info.language} (olasilik={info.language_probability:.2f})")

    entries: list[SRTEntry] = []
    for idx, segment in enumerate(segments, start=1):
        text = (segment.text or "").strip()
        if not text:
            continue
        entries.append(
            SRTEntry(
                index=idx,
                start=_format_timestamp(segment.start),
                end=_format_timestamp(segment.end),
                text=text,
            )
        )

    if not entries:
        raise RuntimeError("Whisper hic altyazi satiri uretmedi.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialize_srt(entries), encoding="utf-8")
    print(f"[WHISPER] {len(entries)} satir yazildi: {output_path.name}")
    return output_path
