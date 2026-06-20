#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FastAPI web server for GenSub subtitle platform."""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import Config, resource_path
from job_manager import JobManager
from srt_parser import srt_to_vtt

STATIC_DIR = resource_path("web", "static")


class CatalogSettingsBody(BaseModel):
    mode: str | None = None
    remoteUrl: str | None = None
    localPath: str | None = None
    sourceLang: str | None = None


class RebuildBody(BaseModel):
    keepVideo: bool = False
    autoStart: bool = True


class GroqKeyBody(BaseModel):
    apiKey: str


def _candidate_is_under(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def create_app(config: Config) -> FastAPI:
    app = FastAPI(title="GenSub — Türkçe Altyazı", version="2.0.0")
    jobs = JobManager(config)

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def _resolve_data_path(rel_path: str) -> Path:
        candidate = (config.output_dir.parent / rel_path).resolve()
        allowed_roots = (
            config.output_dir.resolve(),
            config.videos_dir.resolve(),
            config.output_dir.parent.resolve(),
        )
        if not any(_candidate_is_under(candidate, root) for root in allowed_roots):
            raise HTTPException(status_code=403, detail="Geçersiz dosya yolu")
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail="Dosya bulunamadı")
        return candidate

    def _has_groq_key() -> bool:
        return bool(jobs.config.groq_api_key)

    @app.on_event("startup")
    async def startup() -> None:
        config.videos_dir.mkdir(parents=True, exist_ok=True)
        config.output_dir.mkdir(parents=True, exist_ok=True)
        jobs.refresh_catalog()

    @app.get("/", response_class=HTMLResponse)
    async def index() -> FileResponse:
        index_path = STATIC_DIR / "index.html"
        if not index_path.is_file():
            raise HTTPException(status_code=404, detail="index.html bulunamadı")
        return FileResponse(index_path)

    @app.get("/api/episodes")
    async def api_episodes():
        return {"episodes": jobs.list_episodes()}

    @app.get("/api/episodes/{episode_id}")
    async def api_episode_detail(episode_id: str):
        detail = jobs.get_episode_detail(episode_id)
        if not detail:
            raise HTTPException(status_code=404, detail="Bölüm bulunamadı")
        return detail

    @app.post("/api/episodes/{episode_id}/process")
    async def api_process_episode(episode_id: str):
        if not _has_groq_key():
            raise HTTPException(
                status_code=503,
                detail="GROQ_API_KEY tanımlı değil. .env dosyasını kontrol edin.",
            )
        result = jobs.enqueue(episode_id)
        if not result.get("ok"):
            raise HTTPException(status_code=409, detail=result.get("error", "İşlem başlatılamadı"))
        return result

    @app.post("/api/episodes/{episode_id}/rebuild")
    async def api_rebuild_episode(episode_id: str, body: RebuildBody | None = None):
        if not _has_groq_key():
            raise HTTPException(
                status_code=503,
                detail="GROQ_API_KEY tanımlı değil. .env dosyasını kontrol edin.",
            )
        opts = body or RebuildBody()
        result = jobs.rebuild_episode(
            episode_id,
            keep_video=opts.keepVideo,
            auto_start=opts.autoStart,
        )
        if not result.get("ok"):
            raise HTTPException(status_code=409, detail=result.get("error", "Yeniden oluşturulamadı"))
        return result

    @app.get("/api/status")
    async def api_status():
        summary = jobs.summary()
        settings = jobs.settings_public()
        return {
            **summary,
            "busy": jobs.is_busy(),
            "currentJob": jobs.current_job(),
            "videoBaseUrl": settings["remoteUrl"],
            "catalog": settings,
            "hasGroqKey": _has_groq_key(),
        }

    @app.post("/api/settings/groq-key")
    async def api_save_groq_key(body: GroqKeyBody):
        from env_settings import save_groq_api_key

        try:
            path = save_groq_api_key(body.apiKey)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f".env yazılamadı: {exc}") from exc

        key = body.apiKey.strip()
        jobs.update_groq_api_key(key)
        return {
            "ok": True,
            "hasGroqKey": True,
            "envPath": str(path),
        }

    @app.get("/api/catalog/settings")
    async def api_catalog_settings():
        return jobs.settings_public()

    @app.post("/api/catalog/settings")
    async def api_update_catalog_settings(body: CatalogSettingsBody):
        settings = jobs.update_settings(
            mode=body.mode,
            remote_url=body.remoteUrl,
            local_path=body.localPath,
            source_lang=body.sourceLang,
        )
        return {
            "ok": True,
            "settings": jobs.settings_public(),
            "count": len(jobs.get_catalog()),
        }

    @app.post("/api/catalog/pick-folder")
    async def api_pick_folder():
        from folder_picker import pick_folder

        initial = jobs.settings.local_path or None
        path = pick_folder(initial)
        if not path:
            return {"ok": False, "error": "Klasör seçilmedi"}
        settings = jobs.update_settings(mode="local", local_path=path)
        return {
            "ok": True,
            "path": path,
            "settings": jobs.settings_public(),
            "count": len(jobs.get_catalog()),
        }

    @app.post("/api/catalog/refresh")
    async def api_refresh_catalog():
        episodes = jobs.refresh_catalog()
        return {"count": len(episodes)}

    @app.get("/watch/{episode_id}", response_class=HTMLResponse)
    async def watch_page(episode_id: str) -> FileResponse:
        watch_path = STATIC_DIR / "watch.html"
        if not watch_path.is_file():
            raise HTTPException(status_code=404, detail="watch.html bulunamadı")
        return FileResponse(watch_path)

    @app.get("/subs/{episode_id}/tr.vtt")
    async def subtitle_vtt(episode_id: str):
        detail = jobs.get_episode_detail(episode_id)
        if not detail:
            raise HTTPException(status_code=404, detail="Bölüm bulunamadı")

        paths = config.resolve_episode_paths(
            detail["videoName"],
            source_lang=detail.get("sourceLang", jobs.settings.source_lang),
        )
        srt_path = paths["srt_tr"]
        if not srt_path.is_file():
            rel = detail.get("paths", {}).get("srtTr")
            if rel:
                srt_path = _resolve_data_path(rel)
            else:
                raise HTTPException(status_code=404, detail="Altyazı dosyası yok")

        vtt = srt_to_vtt(srt_path.read_text(encoding="utf-8"))
        return Response(content=vtt, media_type="text/vtt; charset=utf-8")

    @app.get("/media/{episode_id}")
    async def media_stream(episode_id: str, request: Request):
        detail = jobs.get_episode_detail(episode_id)
        if not detail:
            raise HTTPException(status_code=404, detail="Bölüm bulunamadı")

        file_path = jobs.resolve_media_path(episode_id)
        if not file_path or not file_path.is_file():
            rel = detail.get("paths", {}).get("video") or detail.get("paths", {}).get("outputVideo")
            if not rel:
                raise HTTPException(status_code=404, detail="Video henüz hazır değil")
            file_path = _resolve_data_path(rel)

        file_size = file_path.stat().st_size
        content_type = mimetypes.guess_type(str(file_path))[0] or "video/mp4"
        range_header = request.headers.get("range")

        if not range_header:
            return FileResponse(file_path, media_type=content_type, filename=file_path.name)

        try:
            units = range_header.replace("bytes=", "").split("-")
            start = int(units[0]) if units[0] else 0
            end = int(units[1]) if len(units) > 1 and units[1] else file_size - 1
        except ValueError as exc:
            raise HTTPException(status_code=416, detail="Geçersiz Range başlığı") from exc

        if start >= file_size or end >= file_size or start > end:
            raise HTTPException(status_code=416, detail="Range aralığı geçersiz")

        length = end - start + 1
        with open(file_path, "rb") as fh:
            fh.seek(start)
            data = fh.read(length)

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Type": content_type,
        }
        return Response(content=data, status_code=206, headers=headers)

    return app
