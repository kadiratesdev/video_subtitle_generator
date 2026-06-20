#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SRT parse and serialize utilities."""
from __future__ import annotations

import re
from dataclasses import dataclass

TIMESTAMP_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


@dataclass
class SRTEntry:
    index: int
    start: str
    end: str
    text: str

    @property
    def timestamp_line(self) -> str:
        return f"{self.start} --> {self.end}"


def parse_srt(content: str) -> list[SRTEntry]:
    content = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not content:
        return []

    blocks = re.split(r"\n\s*\n", content)
    entries: list[SRTEntry] = []

    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.split("\n") if line.strip()]
        if len(lines) < 2:
            continue

        index = 0
        ts_line_idx = 0
        if TIMESTAMP_RE.search(lines[0]):
            ts_line_idx = 0
        elif len(lines) >= 2 and TIMESTAMP_RE.search(lines[1]):
            try:
                index = int(lines[0])
            except ValueError:
                index = len(entries) + 1
            ts_line_idx = 1
        else:
            continue

        match = TIMESTAMP_RE.search(lines[ts_line_idx])
        if not match:
            continue

        start = _normalize_ts(*match.group(1, 2, 3, 4))
        end = _normalize_ts(*match.group(5, 6, 7, 8))
        text = "\n".join(lines[ts_line_idx + 1 :]).strip()
        if not text:
            continue

        if not index:
            index = len(entries) + 1
        entries.append(SRTEntry(index=index, start=start, end=end, text=text))

    return entries


def _normalize_ts(h: str, m: str, s: str, ms: str) -> str:
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms}"


def serialize_srt(entries: list[SRTEntry]) -> str:
    blocks: list[str] = []
    for idx, entry in enumerate(entries, start=1):
        blocks.append(
            "\n".join(
                [
                    str(idx),
                    entry.timestamp_line,
                    entry.text,
                ]
            )
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def srt_to_vtt(content: str) -> str:
    entries = parse_srt(content)
    lines = ["WEBVTT", ""]
    for entry in entries:
        start = entry.start.replace(",", ".")
        end = entry.end.replace(",", ".")
        lines.append(f"{start} --> {end}")
        lines.append(entry.text)
        lines.append("")
    return "\n".join(lines)
