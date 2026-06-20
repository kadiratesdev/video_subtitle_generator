#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Main pipeline orchestrator with resume support."""
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Callable, Optional

from catalog import Episode
from catalog_settings import LANG_LABELS
from config import Config, find_existing_source_srt
from state import PipelineState
from steps.embed_subs import embed_soft_subs
from steps.extract_audio import extract_audio
from steps.stage_video import stage_video
from steps.translate_groq import is_srt_untranslated, translate_srt as groq_translate_srt

ProgressCb = Optional[Callable[[float, str], None]]


def _transcribe(
    audio_path: Path,
    srt_source: Path,
    config: Config,
    progress_cb: ProgressCb,
    *,
    language: str,
) -> None:
    if config.use_local_whisper:
        from steps.transcribe import transcribe_to_srt

        transcribe_to_srt(audio_path, srt_source, config)
    else:
        from steps.transcribe_groq import transcribe_to_srt

        transcribe_to_srt(
            audio_path,
            srt_source,
            config,
            progress_cb=progress_cb,
            language=language,
        )


def _completed_paths(paths: dict[str, Path]) -> dict[str, Path]:
    return {
        "video": paths["video"],
        "srtSource": paths["srt_source"],
        "srtEs": paths.get("srt_es") or paths["srt_source"],
        "srtTr": paths["srt_tr"],
        "outputVideo": paths["output_video"],
    }


def process_episode(
    episode: Episode,
    config: Config,
    state: PipelineState,
    *,
    source_lang: str,
    progress_cb: ProgressCb = None,
) -> bool:
    video_name = episode.filename
    paths = config.resolve_episode_paths(
        video_name,
        source_lang=source_lang,
        local_video=episode.local_path,
    )
    paths["dir"].mkdir(parents=True, exist_ok=True)
    config.videos_dir.mkdir(parents=True, exist_ok=True)

    lang_label = LANG_LABELS.get(source_lang, source_lang)

    def report(p: float, msg: str) -> None:
        state.set_progress(video_name, p, msg)
        if progress_cb:
            progress_cb(p, msg)

    existing_source = find_existing_source_srt(paths["dir"], source_lang)
    if existing_source and not paths["srt_source"].exists():
        paths["srt_source"] = existing_source

    resume = state.infer_resume_step(
        paths,
        embed=config.embed_subtitles,
        source_lang=source_lang,
    )
    if (
        resume is None
        and paths["srt_tr"].exists()
        and paths["video"].exists()
        and paths["srt_source"].exists()
        and not is_srt_untranslated(paths["srt_source"], paths["srt_tr"])
    ):
        state.mark_completed(video_name, _completed_paths(paths))
        return True

    state.mark_processing(video_name)
    print(f"\n[EPISODE] {video_name} (resume={resume or 'start'}, lang={source_lang})")

    try:
        if resume in (None, "download"):
            action = "Kopyalanıyor" if episode.is_local else "İndiriliyor"
            print(f"[STEP] Video {action.lower()}...")
            report(0.05, f"Video {action.lower()}...")

            def dl_progress(ratio: float, done: int, total: int) -> None:
                pct = 0.05 + ratio * 0.25
                mb = done / (1024 * 1024)
                total_mb = total / (1024 * 1024) if total else 0
                report(pct, f"{action} {mb:.1f}/{total_mb:.1f} MB")

            stage_video(
                remote_url=episode.remote_url,
                local_path=episode.local_path,
                output_path=paths["video"],
                progress_cb=dl_progress,
            )
            state.mark_step(video_name, "download")

        if resume in (None, "download", "extract"):
            print("[STEP] Ses çıkarılıyor...")
            report(0.32, "Ses çıkarılıyor...")
            extract_audio(paths["video"], paths["audio"])
            state.mark_step(video_name, "extract")

        if resume in (None, "download", "extract", "transcribe"):
            print(f"[STEP] {lang_label} transkripsiyon (Groq)...")
            report(0.38, f"{lang_label} transkripsiyon...")

            def tr_progress(ratio: float, msg: str) -> None:
                report(0.38 + ratio * 0.27, msg)

            _transcribe(
                paths["audio"],
                paths["srt_source"],
                config,
                tr_progress,
                language=source_lang,
            )
            state.mark_step(video_name, "transcribe")

        if resume in (None, "download", "extract", "transcribe", "translate"):
            print("[STEP] Türkçe çeviri (Groq)...")
            report(0.68, "Türkçe çeviri...")

            def translate_progress(ratio: float, done: int, total: int) -> None:
                report(0.68 + ratio * 0.28, f"Çeviri {done}/{total} satır")

            groq_translate_srt(
                paths["srt_source"],
                paths["srt_tr"],
                config,
                progress_cb=translate_progress,
                force=is_srt_untranslated(paths["srt_source"], paths["srt_tr"]),
                source_lang=source_lang,
            )
            state.mark_step(video_name, "translate")

        if config.embed_subtitles and resume in (
            None,
            "download",
            "extract",
            "transcribe",
            "translate",
            "embed",
        ):
            print("[STEP] Altyazı videoya gömülüyor...")
            report(0.96, "Altyazı videoya gömülüyor...")
            embed_soft_subs(paths["video"], paths["srt_tr"], paths["output_video"])
            state.mark_step(video_name, "embed")

        state.mark_completed(video_name, _completed_paths(paths))
        report(1.0, "Hazır")
        print(f"[OK] Tamamlandı: {video_name}")
        return True
    except Exception as exc:
        state.mark_failed(video_name, str(exc))
        print(f"[ERROR] {video_name}: {exc}")
        traceback.print_exc()
        return False
