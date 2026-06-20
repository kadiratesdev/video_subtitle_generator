#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JSON state management with resume support."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STEP_NAMES = ("download", "extract", "transcribe", "translate", "embed")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_steps() -> dict[str, str]:
    return {name: "pending" for name in STEP_NAMES}


def _rel(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path.resolve())


class PipelineState:
    def __init__(self, state_file: Path, output_dir: Path):
        self.state_file = state_file.resolve()
        self.output_dir = output_dir.resolve()
        self.data: dict[str, Any] = self._load()
        self._save_lock = threading.Lock()
        self._last_progress_save = 0.0

    def _default_data(self) -> dict[str, Any]:
        return {
            "version": 2,
            "outputDir": str(self.output_dir),
            "lastUpdated": _utc_now(),
            "episodes": {},
        }

    def _load(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return self._default_data()
        with open(self.state_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return self._default_data()
        data.setdefault("version", 2)
        data.setdefault("episodes", {})
        return data

    def save(self, *, force: bool = False) -> None:
        with self._save_lock:
            self.data["lastUpdated"] = _utc_now()
            self.data["outputDir"] = str(self.output_dir)
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.state_file.with_suffix(".json.tmp")

            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())

            last_err: OSError | None = None
            for attempt in range(8):
                try:
                    if self.state_file.exists():
                        os.replace(tmp_path, self.state_file)
                    else:
                        tmp_path.rename(self.state_file)
                    return
                except PermissionError as exc:
                    last_err = exc
                    time.sleep(0.15 * (attempt + 1))
                except OSError as exc:
                    if getattr(exc, "winerror", None) == 5 or exc.errno in (13, 16):
                        last_err = exc
                        time.sleep(0.15 * (attempt + 1))
                        continue
                    raise

            # Son çare: doğrudan üzerine yaz (Windows kilitlerinde daha toleranslı)
            try:
                with open(self.state_file, "w", encoding="utf-8") as fh:
                    json.dump(self.data, fh, ensure_ascii=False, indent=2)
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
                return
            except OSError:
                if last_err:
                    raise last_err
                raise

    def _new_episode(self) -> dict[str, Any]:
        return {
            "status": "pending",
            "steps": _empty_steps(),
            "paths": {},
            "error": None,
            "progress": 0,
            "progressMessage": "",
            "startedAt": None,
            "completedAt": None,
        }

    def get_episode(self, video_name: str) -> dict[str, Any]:
        episodes = self.data.setdefault("episodes", {})
        if video_name not in episodes:
            episodes[video_name] = self._new_episode()
        episode = episodes[video_name]
        episode.setdefault("steps", _empty_steps())
        episode.setdefault("paths", {})
        episode.setdefault("error", None)
        episode.setdefault("progress", 0)
        episode.setdefault("progressMessage", "")
        return episode

    def read_episode(self, video_name: str) -> dict[str, Any]:
        """Liste/izleme için — state dosyasına yeni kayıt eklemez."""
        episode = self.data.get("episodes", {}).get(video_name)
        if episode is None:
            return self._new_episode()
        return episode

    def set_progress(self, video_name: str, progress: float, message: str = "") -> None:
        episode = self.get_episode(video_name)
        episode["progress"] = max(0.0, min(1.0, progress))
        if message:
            episode["progressMessage"] = message

        now = time.monotonic()
        done = progress >= 1.0
        if not done and (now - self._last_progress_save) < 1.0:
            return
        self._last_progress_save = now
        self.save(force=done)

    def mark_step(self, video_name: str, step: str, status: str = "done") -> None:
        episode = self.get_episode(video_name)
        episode["steps"][step] = status
        if episode.get("startedAt") is None:
            episode["startedAt"] = _utc_now()
        self.save()

    def mark_processing(self, video_name: str) -> None:
        episode = self.get_episode(video_name)
        episode["status"] = "processing"
        episode["error"] = None
        if episode.get("startedAt") is None:
            episode["startedAt"] = _utc_now()
        self.save()

    def mark_completed(self, video_name: str, paths: dict[str, Path]) -> None:
        episode = self.get_episode(video_name)
        episode["status"] = "ready"
        episode["error"] = None
        episode["progress"] = 1.0
        episode["progressMessage"] = "Hazır"
        episode["completedAt"] = _utc_now()
        episode["paths"] = {
            key: _rel(path, self.output_dir.parent)
            for key, path in paths.items()
        }
        for step in STEP_NAMES:
            if step in episode["steps"]:
                episode["steps"][step] = "done"
        self.save()

    def mark_failed(self, video_name: str, error: str) -> None:
        episode = self.get_episode(video_name)
        episode["status"] = "failed"
        episode["error"] = str(error)
        self.save()

    def is_ready(self, video_name: str, paths: dict[str, Path]) -> bool:
        episode = self.get_episode(video_name)
        if paths["srt_tr"].exists() and paths["video"].exists():
            return True
        return episode.get("status") == "ready"

    def infer_resume_step(
        self,
        paths: dict[str, Path],
        *,
        embed: bool,
        source_lang: str = "es",
    ) -> str | None:
        from config import find_existing_source_srt
        from steps.translate_groq import is_srt_untranslated

        srt_source = paths.get("srt_source")
        if not srt_source or not srt_source.exists():
            found = find_existing_source_srt(paths["dir"], source_lang)
            if found:
                srt_source = found

        if embed and not paths["output_video"].exists():
            if paths["srt_tr"].exists():
                return "embed"
        if not paths["srt_tr"].exists() or (
            srt_source
            and srt_source.exists()
            and is_srt_untranslated(srt_source, paths["srt_tr"])
        ):
            if not srt_source or not srt_source.exists():
                if not paths["audio"].exists():
                    if not paths["video"].exists():
                        return "download"
                    return "extract"
                return "transcribe"
            return "translate"
        if not paths["srt_tr"].exists():
            if not paths["audio"].exists():
                if not paths["video"].exists():
                    return "download"
                return "extract"
            return "transcribe"
        return None

    def recover_stale_processing(self) -> int:
        """Çökme sonrası takılı 'processing' durumlarını sıfırlar."""
        episodes = self.data.get("episodes", {})
        recovered = 0
        for episode in episodes.values():
            if episode.get("status") != "processing":
                continue
            episode["status"] = "pending"
            episode["progress"] = 0
            episode["progressMessage"] = ""
            recovered += 1
        if recovered:
            self.save()
        return recovered

    def prune_untracked_episodes(self, *, keep: set[str]) -> int:
        """Sadece işlenmiş / takip edilen bölümleri state'te tut."""
        episodes = self.data.get("episodes", {})
        removed = [name for name in episodes if name not in keep]
        for name in removed:
            del episodes[name]
        if removed:
            self.save()
        return len(removed)

    def clear_episode(self, video_name: str) -> None:
        """Bölüm state kaydını sıfırlar."""
        episodes = self.data.get("episodes", {})
        if video_name in episodes:
            del episodes[video_name]
            self.save()

    def episode_public(self, video_name: str, *, episode_id: str, title: str) -> dict[str, Any]:
        episode = self.read_episode(video_name)
        return {
            "id": episode_id,
            "videoName": video_name,
            "title": title,
            "status": episode.get("status", "pending"),
            "steps": episode.get("steps", {}),
            "error": episode.get("error"),
            "progress": episode.get("progress", 0),
            "progressMessage": episode.get("progressMessage", ""),
            "paths": episode.get("paths", {}),
            "completedAt": episode.get("completedAt"),
        }
