#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`.env` dosyası oluşturma ve güncelleme."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from dotenv import load_dotenv

from config import ROOT

_ENV_VAR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def env_file_path() -> Path:
    return ROOT / ".env"


def ensure_env_file() -> Path:
    """`.env` yoksa `.env.example` kopyala; o da yoksa minimal şablon oluştur."""
    path = env_file_path()
    if path.is_file():
        return path

    example = ROOT / ".env.example"
    if example.is_file():
        shutil.copy2(example, path)
        return path

    path.write_text(
        "# Groq API anahtarı (https://console.groq.com)\nGROQ_API_KEY=\n",
        encoding="utf-8",
    )
    return path


def _parse_env_lines(text: str) -> list[tuple[str | None, str]]:
    """Satırları (anahtar, ham_satır) veya (None, yorum/boş) olarak ayır."""
    rows: list[tuple[str | None, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            rows.append((None, line))
            continue
        match = _ENV_VAR_RE.match(line)
        if match:
            rows.append((match.group(1), line))
        else:
            rows.append((None, line))
    return rows


def set_env_var(name: str, value: str) -> Path:
    """`.env` içinde değişkeni günceller veya ekler; `os.environ` senkronize edilir."""
    path = ensure_env_file()
    raw = path.read_text(encoding="utf-8") if path.is_file() else ""
    rows = _parse_env_lines(raw)

    new_line = f"{name}={value}"
    updated = False
    out_lines: list[str] = []
    for key, line in rows:
        if key == name:
            out_lines.append(new_line)
            updated = True
        else:
            out_lines.append(line)

    if not updated:
        if out_lines and out_lines[-1].strip():
            out_lines.append("")
        out_lines.append(new_line)

    path.write_text("\n".join(out_lines).rstrip() + "\n", encoding="utf-8")
    os.environ[name] = value
    load_dotenv(path, override=True)
    return path


def save_groq_api_key(api_key: str) -> Path:
    key = api_key.strip()
    if len(key) < 8:
        raise ValueError("API anahtarı çok kısa.")
    return set_env_var("GROQ_API_KEY", key)
