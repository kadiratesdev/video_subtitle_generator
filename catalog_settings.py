#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Video kaynağı ve kaynak dil ayarları (kalıcı)."""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from config import Config, ROOT

SourceMode = Literal["remote", "local"]
SourceLang = Literal["es", "en"]

SUPPORTED_LANGS: tuple[SourceLang, ...] = ("es", "en")
LANG_LABELS = {"es": "İspanyolca", "en": "İngilizce"}


@dataclass
class CatalogSettings:
    mode: SourceMode = "local"
    remote_url: str = ""
    local_path: str = ""
    source_lang: SourceLang = "es"

    def normalized_remote_url(self) -> str:
        url = (self.remote_url or "").strip()
        if not url:
            return ""
        return url if url.endswith("/") else f"{url}/"

    def local_dir(self) -> Path | None:
        raw = (self.local_path or "").strip()
        if not raw:
            return None
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = ROOT / p
        return p.resolve()

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "remoteUrl": self.normalized_remote_url(),
            "localPath": self.local_path,
            "sourceLang": self.source_lang,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, config: Config) -> "CatalogSettings":
        mode = data.get("mode", "local")
        if mode not in ("remote", "local"):
            mode = "local"
        lang = data.get("sourceLang", data.get("source_lang", "es"))
        if lang not in SUPPORTED_LANGS:
            lang = "es"
        default_local = str(config.local_video_dir or config.videos_dir)
        remote = data.get("remoteUrl") or data.get("remote_url") or config.video_base_url or ""
        local = data.get("localPath") or data.get("local_path") or default_local
        return cls(mode=mode, remote_url=remote, local_path=local, source_lang=lang)

    @classmethod
    def from_config(cls, config: Config) -> "CatalogSettings":
        mode: SourceMode = "local" if config.video_source == "local" else "remote"
        lang = config.source_lang if config.source_lang in SUPPORTED_LANGS else "es"
        default_local = str(config.local_video_dir or config.videos_dir)
        return cls(
            mode=mode,
            remote_url=config.video_base_url or "",
            local_path=default_local,
            source_lang=lang,
        )


class CatalogSettingsStore:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self._lock = threading.Lock()

    def load(self, config: Config) -> CatalogSettings:
        if not self.path.is_file():
            return CatalogSettings.from_config(config)
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return CatalogSettings.from_dict(data, config=config)
        except (OSError, json.JSONDecodeError):
            pass
        return CatalogSettings.from_config(config)

    def save(self, settings: CatalogSettings) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(settings.to_dict(), fh, ensure_ascii=False, indent=2)
            tmp.replace(self.path)
