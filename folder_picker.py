#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Yerel klasör seçimi (tkinter — masaüstü / exe)."""
from __future__ import annotations


def pick_folder(initial_dir: str | None = None) -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(
            title="Video klasörünü seçin",
            initialdir=initial_dir or "",
            mustexist=True,
        )
        root.destroy()
        if path:
            return str(path)
        return None
    except Exception:
        return None
