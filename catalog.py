#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Uzak ve yerel video katalogları."""
from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import httpx

from catalog_settings import CatalogSettings
from config import Config

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".wmv"}
EPISODE_RE = re.compile(r"el-clon-(\d+)\.mp4", re.IGNORECASE)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(value)


@dataclass(frozen=True)
class Episode:
    filename: str
    title: str
    remote_url: str | None = None
    local_path: str | None = None
    sort_key: int = 0

    @property
    def id(self) -> str:
        return Path(self.filename).stem

    @property
    def display_title(self) -> str:
        return self.title

    @property
    def is_local(self) -> bool:
        return bool(self.local_path)


def _fallback_remote(remote_url: str) -> list[Episode]:
    items: list[Episode] = []
    for n in range(1, 251):
        name = f"el-clon-{n:03d}.mp4"
        items.append(
            Episode(
                filename=name,
                title=f"Bölüm {n:03d}",
                remote_url=urljoin(remote_url, name),
                sort_key=n,
            )
        )
    return items


def fetch_remote_episodes(
    remote_url: str,
    *,
    timeout: float = 30.0,
) -> list[Episode]:
    base = (remote_url or "").strip()
    if not base:
        return []
    base = base if base.endswith("/") else f"{base}/"
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(base)
            response.raise_for_status()
            html = response.text
    except Exception:
        return _fallback_remote(base)

    parser = _LinkParser()
    parser.feed(html)

    seen: set[str] = set()
    episodes: list[Episode] = []

    for href in parser.links:
        name = href.split("/")[-1].strip()
        match = EPISODE_RE.fullmatch(name)
        if not match or name in seen:
            continue
        seen.add(name)
        num = int(match.group(1))
        episodes.append(
            Episode(
                filename=name,
                title=f"Bölüm {num:03d}",
                remote_url=urljoin(base, name),
                sort_key=num,
            )
        )

    if not episodes:
        return _fallback_remote(base)

    episodes.sort(key=lambda ep: ep.sort_key)
    return episodes


def _natural_sort_key(name: str) -> tuple:
    parts = re.split(r"(\d+)", name.lower())
    key: list = []
    for part in parts:
        if part.isdigit():
            key.append(int(part))
        else:
            key.append(part)
    return key


def scan_local_folder(folder: Path) -> list[Episode]:
    if not folder.is_dir():
        return []

    episodes: list[Episode] = []
    for path in sorted(folder.iterdir(), key=lambda p: _natural_sort_key(p.name)):
        if not path.is_file():
            continue
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        resolved = str(path.resolve())
        episodes.append(
            Episode(
                filename=path.name,
                title=path.stem,
                local_path=resolved,
                sort_key=0,
            )
        )
    return episodes


def fetch_episodes(config: Config, settings: CatalogSettings) -> list[Episode]:
    if settings.mode == "local":
        folder = settings.local_dir()
        if folder is None:
            return []
        return scan_local_folder(folder)
    return fetch_remote_episodes(settings.normalized_remote_url())
