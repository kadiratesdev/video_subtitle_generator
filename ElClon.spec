# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Groq API sürümü (CUDA gerekmez, ffmpeg dahil)."""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None
root = Path(SPECPATH)

datas = [
    (str(root / "web" / "static"), "web/static"),
    (str(root / ".env.example"), "."),
]
binaries = []
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "httpx",
    "httpcore",
    "h11",
    "anyio",
    "sniffio",
    "groq",
    "groq.types",
    "imageio_ffmpeg",
    "multipart",
    "email.mime.multipart",
    "email.mime.text",
]

for pkg in ("groq", "imageio_ffmpeg", "fastapi", "starlette", "pydantic"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        pass

a = Analysis(
    ["app.py"],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch",
        "transformers",
        "faster_whisper",
        "tensorflow",
        "tkinter",
        "matplotlib",
        "scipy",
        "pandas",
        "pytest",
        "IPython",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ElClon",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ElClon",
)
