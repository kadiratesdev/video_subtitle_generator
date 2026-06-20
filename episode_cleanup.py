#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bölüm çıktılarını temizleme (yeniden oluşturma)."""
from __future__ import annotations

from pathlib import Path

from catalog import Episode


def _safe_unlink(path: Path) -> bool:
    try:
        if path.is_file():
            path.unlink()
            return True
    except OSError:
        pass
    return False


def clear_episode_artifacts(
    paths: dict,
    episode: Episode,
    *,
    delete_staged_video: bool = True,
) -> list[str]:
    """İşlem çıktılarını siler. Yerel kaynak dosyasına dokunulmaz."""
    removed: list[str] = []
    ep_dir = paths.get("dir")

    if ep_dir and Path(ep_dir).is_dir():
        ep_path = Path(ep_dir)
        for name in ("audio.mp3", "es.srt", "en.srt", "tr.srt"):
            p = ep_path / name
            if _safe_unlink(p):
                removed.append(str(p))
        for p in ep_path.glob("*_tr.mp4"):
            if _safe_unlink(p):
                removed.append(str(p))
        for p in ep_path.glob("chunk_*.mp3"):
            if _safe_unlink(p):
                removed.append(str(p))

    if delete_staged_video:
        video = Path(paths["video"])
        local_src = Path(episode.local_path).resolve() if episode.local_path else None
        is_original = local_src and video.resolve() == local_src
        if not is_original:
            if _safe_unlink(video):
                removed.append(str(video))
            part = video.with_suffix(video.suffix + ".part")
            if _safe_unlink(part):
                removed.append(str(part))

    return removed
