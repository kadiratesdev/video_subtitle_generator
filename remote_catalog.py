#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Remote video directory catalog."""
from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import httpx

from config import Config

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
class RemoteEpisode:
    filename: str
    number: int
    title: str
    url: str

    @property
    def id(self) -> str:
        return Path(self.filename).stem

    @property
    def display_title(self) -> str:
        return f"Bölüm {self.number:03d}"


def _fallback_episodes(config: Config) -> list[RemoteEpisode]:
    """Sunucu yanıt vermezse 001–250 arası varsayılan liste."""
    items: list[RemoteEpisode] = []
    for n in range(1, 251):
        name = f"el-clon-{n:03d}.mp4"
        items.append(
            RemoteEpisode(
                filename=name,
                number=n,
                title=f"Bölüm {n:03d}",
                url=config.remote_video_url(name),
            )
        )
    return items


def fetch_remote_episodes(config: Config, *, timeout: float = 30.0) -> list[RemoteEpisode]:
    """HTTP dizin listesinden bölümleri çeker."""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(config.video_base_url)
            response.raise_for_status()
            html = response.text
    except Exception:
        return _fallback_episodes(config)

    parser = _LinkParser()
    parser.feed(html)

    seen: set[str] = set()
    episodes: list[RemoteEpisode] = []

    for href in parser.links:
        name = href.split("/")[-1].strip()
        match = EPISODE_RE.fullmatch(name)
        if not match or name in seen:
            continue
        seen.add(name)
        num = int(match.group(1))
        episodes.append(
            RemoteEpisode(
                filename=name,
                number=num,
                title=f"Bölüm {num:03d}",
                url=urljoin(config.video_base_url, name),
            )
        )

    if not episodes:
        return _fallback_episodes(config)

    episodes.sort(key=lambda ep: ep.number)
    return episodes
