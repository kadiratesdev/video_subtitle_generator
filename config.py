#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pipeline configuration loaded from environment variables."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _app_root() -> Path:
    """PyInstaller onefile/onedir uyumlu kök dizin."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = _app_root()
load_dotenv(ROOT / ".env", override=True)


def resource_path(*parts: str) -> Path:
    """PyInstaller paketinde gömülü dosyalar (_MEIPASS) veya geliştirme kökü."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", ROOT))
    else:
        base = ROOT
    return base.joinpath(*parts)


def _path(value: str, default: Path) -> Path:
    raw = (value or "").strip()
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = ROOT / p
        return p.expanduser().resolve()
    return default.resolve()


@dataclass(frozen=True)
class Config:
    video_base_url: str
    video_source: str
    local_video_dir: Path | None
    source_lang: str
    videos_dir: Path
    output_dir: Path
    state_file: Path
    catalog_settings_file: Path
    groq_api_key: str
    groq_model: str
    groq_fallback_model: str
    groq_whisper_model: str
    groq_lines_per_call: int
    web_host: str
    web_port: int
    use_local_whisper: bool
    whisper_model: str
    whisper_device: str
    whisper_compute_type: str
    embed_subtitles: bool

    @classmethod
    def from_env(cls) -> "Config":
        output_dir = _path(os.getenv("OUTPUT_DIR", ""), ROOT / "output")
        videos_dir = _path(os.getenv("VIDEOS_DIR", ""), ROOT / "videos")
        base_url = os.getenv("VIDEO_BASE_URL", "").strip()
        if base_url and not base_url.endswith("/"):
            base_url += "/"

        source_raw = os.getenv("VIDEO_SOURCE", "local").strip().lower()
        video_source = "local" if source_raw == "local" else "remote"
        lang_raw = os.getenv("SOURCE_LANG", "es").strip().lower()
        source_lang = lang_raw if lang_raw in ("es", "en") else "es"
        local_dir_raw = os.getenv("LOCAL_VIDEO_DIR", "").strip()
        local_video_dir = _path(local_dir_raw, videos_dir)

        return cls(
            video_base_url=base_url,
            video_source=video_source,
            local_video_dir=local_video_dir,
            source_lang=source_lang,
            videos_dir=videos_dir,
            output_dir=output_dir,
            state_file=_path(
                os.getenv("STATE_FILE", ""),
                output_dir / "pipeline-state.json",
            ),
            catalog_settings_file=output_dir / "catalog-settings.json",
            groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
            or "llama-3.3-70b-versatile",
            groq_fallback_model=os.getenv("GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant").strip()
            or "llama-3.1-8b-instant",
            groq_whisper_model=os.getenv(
                "GROQ_WHISPER_MODEL", "whisper-large-v3"
            ).strip()
            or "whisper-large-v3",
            groq_lines_per_call=max(5, int(os.getenv("GROQ_LINES_PER_CALL", "15"))),
            web_host=os.getenv("WEB_HOST", "127.0.0.1").strip() or "127.0.0.1",
            web_port=max(1, int(os.getenv("WEB_PORT", "8765"))),
            use_local_whisper=os.getenv("USE_LOCAL_WHISPER", "0").strip().lower()
            in ("1", "true", "yes"),
            whisper_model=os.getenv("WHISPER_MODEL", "large-v3").strip() or "large-v3",
            whisper_device=os.getenv("WHISPER_DEVICE", "cpu").strip() or "cpu",
            whisper_compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8").strip()
            or "int8",
            embed_subtitles=os.getenv("EMBED_SUBTITLES", "0").strip().lower()
            in ("1", "true", "yes"),
        )

    def remote_video_url(self, filename: str) -> str:
        return f"{self.video_base_url}{filename}"

    def local_video_path(self, video_name: str) -> Path:
        return self.videos_dir / video_name

    def episode_dir(self, stem: str) -> Path:
        return self.output_dir / stem

    def episode_paths(
        self,
        video_name: str,
        *,
        source_lang: str | None = None,
    ) -> dict[str, Path]:
        lang = source_lang or self.source_lang
        if lang not in ("es", "en"):
            lang = "es"
        stem = Path(video_name).stem
        ep_dir = self.episode_dir(stem)
        srt_source = ep_dir / f"{lang}.srt"
        return {
            "dir": ep_dir,
            "video": self.local_video_path(video_name),
            "audio": ep_dir / "audio.mp3",
            "srt_source": srt_source,
            "srt_es": ep_dir / "es.srt",
            "srt_tr": ep_dir / "tr.srt",
            "output_video": ep_dir / f"{stem}_tr.mp4",
            "source_lang": lang,
        }

    def resolve_episode_paths(
        self,
        episode_filename: str,
        *,
        source_lang: str,
        local_video: str | None = None,
    ) -> dict[str, Path]:
        paths = self.episode_paths(episode_filename, source_lang=source_lang)
        if local_video:
            paths["video"] = Path(local_video).expanduser().resolve()
        return paths


def find_existing_source_srt(ep_dir: Path, source_lang: str) -> Path | None:
    """Kaynak altyazı dosyasını bul (geriye dönük uyumluluk)."""
    candidates = [
        ep_dir / f"{source_lang}.srt",
        ep_dir / "es.srt",
        ep_dir / "en.srt",
    ]
    for path in candidates:
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def get_config() -> Config:
    return Config.from_env()
