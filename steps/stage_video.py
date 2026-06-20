#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage video from remote URL or local path into pipeline workspace."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Optional

from steps.download_video import download_video

ProgressCb = Optional[Callable[[float, int, int], None]]


def stage_video(
    *,
    remote_url: str | None,
    local_path: str | None,
    output_path: Path,
    progress_cb: ProgressCb = None,
) -> Path:
    """Videoyu işlem için hedef konuma getirir (indir veya kopyala)."""
    if output_path.exists() and output_path.stat().st_size > 0:
        if progress_cb:
            size = output_path.stat().st_size
            progress_cb(1.0, size, size)
        return output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if local_path:
        src = Path(local_path).expanduser().resolve()
        if not src.is_file():
            raise FileNotFoundError(f"Yerel video bulunamadı: {src}")
        if src.resolve() == output_path.resolve():
            if progress_cb:
                size = src.stat().st_size
                progress_cb(1.0, size, size)
            return output_path
        shutil.copy2(src, output_path)
        if progress_cb:
            size = output_path.stat().st_size
            progress_cb(1.0, size, size)
        return output_path

    if not remote_url:
        raise ValueError("Video kaynağı tanımlı değil (uzak URL veya yerel yol)")

    return download_video(remote_url, output_path, progress_cb=progress_cb)
