#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Background job queue for episode processing."""
from __future__ import annotations

import threading
import traceback
from dataclasses import replace
from typing import Any

from catalog import Episode, fetch_episodes
from catalog_settings import CatalogSettings, CatalogSettingsStore, LANG_LABELS
from config import Config, find_existing_source_srt
from episode_cleanup import clear_episode_artifacts
from pipeline import process_episode
from state import PipelineState
from steps.translate_groq import is_srt_untranslated


def _episode_is_ready(paths: dict, source_lang: str) -> bool:
    srt_source = paths["srt_source"]
    if not srt_source.exists():
        found = find_existing_source_srt(paths["dir"], source_lang)
        if found:
            srt_source = found
    return (
        paths["video"].exists()
        and paths["srt_tr"].exists()
        and srt_source.exists()
        and not is_srt_untranslated(srt_source, paths["srt_tr"])
    )


def _completed_path_dict(paths: dict) -> dict[str, Any]:
    return {
        "video": paths["video"],
        "srtSource": paths["srt_source"],
        "srtEs": paths.get("srt_es") or paths["srt_source"],
        "srtTr": paths["srt_tr"],
        "outputVideo": paths["output_video"],
    }


class JobManager:
    def __init__(self, config: Config):
        self.config = config
        self.state = PipelineState(config.state_file, config.output_dir)
        self.settings_store = CatalogSettingsStore(config.catalog_settings_file)
        self.settings = self.settings_store.load(config)
        self._sync_episodes_from_disk()
        self.state.recover_stale_processing()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._current: str | None = None
        self._stop = False
        self._catalog: list[Episode] = []
        self._catalog_lock = threading.Lock()

    def get_settings(self) -> CatalogSettings:
        return self.settings

    def update_groq_api_key(self, api_key: str) -> None:
        self.config = replace(self.config, groq_api_key=api_key.strip())

    def update_settings(
        self,
        *,
        mode: str | None = None,
        remote_url: str | None = None,
        local_path: str | None = None,
        source_lang: str | None = None,
    ) -> CatalogSettings:
        current = self.settings
        new_mode = mode if mode in ("remote", "local") else current.mode
        new_lang = source_lang if source_lang in ("es", "en") else current.source_lang
        new_remote = remote_url if remote_url is not None else current.remote_url
        new_local = local_path if local_path is not None else current.local_path
        self.settings = CatalogSettings(
            mode=new_mode,
            remote_url=new_remote,
            local_path=new_local,
            source_lang=new_lang,
        )
        self.settings_store.save(self.settings)
        self.refresh_catalog()
        return self.settings

    def settings_public(self) -> dict[str, Any]:
        s = self.settings
        folder = s.local_dir()
        return {
            "mode": s.mode,
            "remoteUrl": s.normalized_remote_url(),
            "localPath": s.local_path,
            "localPathExists": bool(folder and folder.is_dir()),
            "sourceLang": s.source_lang,
            "sourceLangLabel": LANG_LABELS.get(s.source_lang, s.source_lang),
        }

    def _paths_for(self, episode: Episode) -> dict:
        return self.config.resolve_episode_paths(
            episode.filename,
            source_lang=self.settings.source_lang,
            local_video=episode.local_path,
        )

    def _sync_episodes_from_disk(self) -> None:
        keep: set[str] = set()
        lang = self.settings.source_lang
        output_dir = self.config.output_dir
        if output_dir.is_dir():
            for ep_dir in output_dir.iterdir():
                if not ep_dir.is_dir():
                    continue
                video_name = f"{ep_dir.name}.mp4"
                paths = self.config.episode_paths(video_name, source_lang=lang)
                if _episode_is_ready(paths, lang):
                    keep.add(video_name)
                    self.state.mark_completed(video_name, _completed_path_dict(paths))

        videos_dir = self.config.videos_dir
        if videos_dir.is_dir():
            for video_path in videos_dir.glob("*.mp4"):
                video_name = video_path.name
                paths = self.config.episode_paths(video_name, source_lang=lang)
                if _episode_is_ready(paths, lang):
                    keep.add(video_name)
                    self.state.mark_completed(video_name, _completed_path_dict(paths))

        tracked = {
            name
            for name, ep in self.state.data.get("episodes", {}).items()
            if ep.get("status") in ("ready", "failed", "processing")
            or ep.get("completedAt")
            or ep.get("startedAt")
        }
        keep |= tracked
        self.state.prune_untracked_episodes(keep=keep)

    def refresh_catalog(self) -> list[Episode]:
        episodes = fetch_episodes(self.config, self.settings)
        with self._catalog_lock:
            self._catalog = episodes
        return episodes

    def get_catalog(self) -> list[Episode]:
        with self._catalog_lock:
            if self._catalog:
                return list(self._catalog)
        return self.refresh_catalog()

    def find_episode(self, episode_id: str) -> Episode | None:
        for ep in self.get_catalog():
            if ep.id == episode_id or ep.filename == episode_id:
                return ep
        return None

    def is_busy(self) -> bool:
        with self._lock:
            return self._worker is not None and self._worker.is_alive()

    def current_job(self) -> str | None:
        with self._lock:
            return self._current

    def _start_worker(self, episode: Episode) -> dict[str, Any]:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                if self._current == episode.filename:
                    return {"ok": True, "status": "processing", "message": "Zaten işleniyor"}
                return {
                    "ok": False,
                    "error": f"Başka bölüm işleniyor: {self._current}",
                }
            self._current = episode.filename
            self._worker = threading.Thread(
                target=self._run_job,
                args=(episode,),
                daemon=True,
                name=f"job-{episode.id}",
            )
            self._worker.start()
        return {"ok": True, "status": "processing", "message": "İşlem başlatıldı"}

    def rebuild_episode(
        self,
        episode_id: str,
        *,
        keep_video: bool = False,
        auto_start: bool = True,
    ) -> dict[str, Any]:
        episode = self.find_episode(episode_id)
        if not episode:
            return {"ok": False, "error": "Bölüm bulunamadı"}

        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                if self._current == episode.filename:
                    return {
                        "ok": False,
                        "error": "Bölüm işleniyor — bitene kadar bekleyin",
                    }
                return {
                    "ok": False,
                    "error": f"Başka bölüm işleniyor: {self._current}",
                }

        paths = self._paths_for(episode)
        removed = clear_episode_artifacts(
            paths,
            episode,
            delete_staged_video=not keep_video,
        )
        self.state.clear_episode(episode.filename)

        if not auto_start:
            return {
                "ok": True,
                "status": "pending",
                "message": "Çıktılar temizlendi",
                "removedCount": len(removed),
            }

        result = self._start_worker(episode)
        if result.get("ok"):
            result["message"] = "Yeniden oluşturuluyor"
            result["removedCount"] = len(removed)
        return result

    def enqueue(self, episode_id: str) -> dict[str, Any]:
        episode = self.find_episode(episode_id)
        if not episode:
            return {"ok": False, "error": "Bölüm bulunamadı"}

        paths = self._paths_for(episode)
        lang = self.settings.source_lang
        if _episode_is_ready(paths, lang):
            self.state.mark_completed(episode.filename, _completed_path_dict(paths))
            return {"ok": True, "status": "ready", "message": "Zaten hazır"}

        return self._start_worker(episode)

    def _run_job(self, episode: Episode) -> None:
        try:
            process_episode(
                episode,
                self.config,
                self.state,
                source_lang=self.settings.source_lang,
            )
        except Exception:
            traceback.print_exc()
        finally:
            with self._lock:
                self._current = None

    def _public_episode(self, ep: Episode) -> dict[str, Any]:
        paths = self._paths_for(ep)
        lang = self.settings.source_lang
        srt_source = paths["srt_source"]
        if not srt_source.exists():
            found = find_existing_source_srt(paths["dir"], lang)
            if found:
                srt_source = found

        data = self.state.episode_public(
            ep.filename,
            episode_id=ep.id,
            title=ep.display_title,
        )
        data["remoteUrl"] = ep.remote_url
        data["isLocal"] = ep.is_local
        data["sourceLang"] = lang
        data["hasVideo"] = paths["video"].exists() or ep.is_local
        data["hasSubtitles"] = _episode_is_ready(paths, lang)
        if data["hasSubtitles"]:
            data["status"] = "ready"
        elif (
            paths["srt_tr"].exists()
            and srt_source.exists()
            and is_srt_untranslated(srt_source, paths["srt_tr"])
            and data.get("status") == "ready"
        ):
            data["status"] = "pending"
        return data

    def list_episodes(self) -> list[dict[str, Any]]:
        return [self._public_episode(ep) for ep in self.get_catalog()]

    def get_episode_detail(self, episode_id: str) -> dict[str, Any] | None:
        episode = self.find_episode(episode_id)
        if not episode:
            return None
        return self._public_episode(episode)

    def summary(self) -> dict[str, int]:
        episodes = self.list_episodes()
        counts = {
            "total": len(episodes),
            "ready": 0,
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }
        for ep in episodes:
            status = ep.get("status", "pending")
            if status == "ready":
                counts["ready"] += 1
            elif status == "processing":
                counts["processing"] += 1
            elif status == "failed":
                counts["failed"] += 1
            else:
                counts["pending"] += 1
        return counts

    def resolve_media_path(self, episode_id: str) -> Any:
        episode = self.find_episode(episode_id)
        if not episode:
            return None
        paths = self._paths_for(episode)
        if self.config.embed_subtitles and paths["output_video"].is_file():
            return paths["output_video"]
        if paths["video"].is_file():
            return paths["video"]
        return None
