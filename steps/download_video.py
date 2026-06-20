#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Download video from remote URL with resume support."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import httpx

ProgressCb = Optional[Callable[[float, int, int], None]]


def download_video(
    url: str,
    output_path: Path,
    *,
    progress_cb: ProgressCb = None,
    chunk_size: int = 1024 * 256,
) -> Path:
    if output_path.exists() and output_path.stat().st_size > 0:
        if progress_cb:
            size = output_path.stat().st_size
            progress_cb(1.0, size, size)
        return output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".part")

    headers: dict[str, str] = {}
    mode = "wb"
    downloaded = 0

    if tmp_path.exists():
        downloaded = tmp_path.stat().st_size
        headers["Range"] = f"bytes={downloaded}-"
        mode = "ab"

    with httpx.stream("GET", url, headers=headers, follow_redirects=True, timeout=None) as response:
        response.raise_for_status()
        total_header = response.headers.get("content-length")
        if response.status_code == 206 and tmp_path.exists():
            total = downloaded + int(total_header or 0)
        else:
            total = int(total_header or 0)
            if response.status_code != 206:
                downloaded = 0
                mode = "wb"

        with open(tmp_path, mode) as fh:
            for chunk in response.iter_bytes(chunk_size):
                if not chunk:
                    continue
                fh.write(chunk)
                downloaded += len(chunk)
                if progress_cb and total > 0:
                    progress_cb(min(downloaded / total, 1.0), downloaded, total)

    tmp_path.replace(output_path)
    if progress_cb:
        final_size = output_path.stat().st_size
        progress_cb(1.0, final_size, final_size)
    return output_path
