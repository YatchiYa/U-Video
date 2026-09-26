"""HTTP API (FastAPI): everything the CLI does, for the web app and integrations.

Run: `ugc serve` (API + embedded worker, in-memory jobs) or, with Docker, `api` + `worker` containers sharing Redis
(REDIS_URL). Long work (render, mix, create, export, QA, website analysis) becomes a background job: poll
GET /api/jobs/{id} or stream GET /api/jobs/{id}/events (Server-Sent Events). Interactive docs: /docs.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from ugc_studio import config, jobs, service

app = FastAPI(title="UGC Studio API", version="1.0",
              description="Local AI video production: projects, renders, voice, timeline, fixes, exports.")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in os.environ.get(
    "UGC_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()],
    allow_methods=["*"], allow_headers=["*"])

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")


def _uploads() -> Path:
    return config.OUTPUTS_DIR / "_uploads"

MEDIA_EXT = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".mp4", ".mov", ".webm", ".m4v", ".wav", ".mp3", ".m4a",
             ".aac", ".ogg", ".flac", ".svg", ".gif", ".avif"}


# ====================================================================== helpers
def _folder(pid: str) -> Path:
    if not ID.match(pid) or pid.startswith("_"):
        raise HTTPException(400, "invalid project id")
    f = config.OUTPUTS_DIR / pid
    if not (f / "project.yaml").is_file():
        raise HTTPException(404, f"project {pid!r} not found")
    return f


def _call(fn, *a, **kw):
    """Service errors -> 400 with the readable message."""
    try:
        return fn(*a, **kw)
    except service.ServiceError as e:
        raise HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e)) from e


def _url(pid: str, path: str | Path | None) -> str | None:
    """A project file as a URL served by GET /api/projects/{pid}/files/..."""
    if not path:
        return None
    p = Path(path).resolve()
    root = (config.OUTPUTS_DIR / pid).resolve()
    if not p.is_relative_to(root):
        return None
    return f"/api/projects/{pid}/files/{p.relative_to(root).as_posix()}?v={int(p.stat().st_mtime) if p.exists() else 0}"


def _save_upload(up: UploadFile, dest_dir: Path) -> Path:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(up.filename or "file").name)[-80:] or "file"
    if Path(name).suffix.lower() not in MEDIA_EXT:
        raise HTTPException(400, f"unsupported file type: {Path(name).suffix or 'none'}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{uuid.uuid4().hex[:8]}_{name}"
    with out.open("wb") as f:
        shutil.copyfileobj(up.file, f)
    return out


def _upload_path(ref: str) -> str:
    """An upload reference returned by POST /api/uploads -> its path (never an arbitrary server path)."""
    p = (_uploads() / Path(ref).name).resolve()
    if not p.is_file() or not p.is_relative_to(_uploads().resolve()):
        raise HTTPException(400, f"unknown upload {ref!r}: upload the file first (POST /api/uploads)")
    return str(p)


# ====================================================================== system
@app.get("/api/health")
def health() -> dict:
    s = jobs.store()
    info = s.worker_info()  # the worker renders: its GPU is what matters (the api container has none)
    return {"ok": True, "store": type(s).__name__, "store_ok": s.ping(), "worker": s.worker_alive(), "gpu": info.get("gpu"),
            "outputs": str(config.OUTPUTS_DIR), "time": time.time()}


@app.get("/api/catalog")
def catalog() -> dict:
    """Everything a form needs: modes, styles, formats, qualities, languages, transitions, icons."""
    from ugc_studio.director import ICONS
    from ugc_studio.schema import Style, TransitionType
    from ugc_studio.voice import CHATTERBOX_LANGS, TTS_LANGUAGES

    return {"modes": [{"id": k, "description": v} for k, v in service.MODES.items()],
            "styles": list(Style.__args__),
            "aspects": ["9:16", "16:9", "1:1", "4:5"], "qualities": ["draft", "standard", "high", "tv"],
            "languages": sorted({x.title() for x in TTS_LANGUAGES} | {x.title() for x in CHATTERBOX_LANGS}),
            "dialects": ["MSA", "ALG", "EGY", "IRQ", "MAR"],
            "transitions": list(TransitionType.__args__), "icons": sorted(ICONS),
            "export_formats": list(service.EXPORT_FORMATS)}


@app.get("/api/providers")
def providers_view() -> list[dict]:
    from ugc_studio import providers

    return providers.describe(None)


# ====================================================================== uploads, personas, website
@app.post("/api/uploads")
def upload(file: UploadFile = File(...)) -> dict:
    out = _save_upload(file, _uploads())
    return {"ref": out.name, "name": file.filename, "size": out.stat().st_size}


@app.get("/api/personas")
def personas_list() -> list[dict]:
    from ugc_studio import personas

    return [{"name": p.name, "description": p.description, "language": p.language, "images": p.images,
             "image_urls": [f"/api/personas/{p.folder.name}/files/{i}" for i in p.images]}
            for p in personas.list_personas()]


@app.get("/api/personas/{name}/files/{file}")
def persona_file(name: str, file: str):
    from ugc_studio import personas

    root = personas.PERSONAS_DIR.resolve()
    f = (root / name / file).resolve()
    if not ID.match(name) or not f.is_relative_to(root) or not f.is_file() or f.suffix.lower() not in MEDIA_EXT:
        raise HTTPException(404, "file not found")
    return FileResponse(f)


class PersonaIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=5)
    uploads: list[str] = []
    voice_style: str = ""
    language: str = "English"


@app.post("/api/personas", status_code=202)
def personas_create(body: PersonaIn) -> dict:
    return jobs.submit("persona", None, {"name": body.name, "description": body.description,
                                         "images": [_upload_path(u) for u in body.uploads],
                                         "voice_style": body.voice_style, "language": body.language})


class SiteIn(BaseModel):
    url: str = Field(pattern=r"^https?://")


@app.post("/api/site", status_code=202)
def site_analyze(body: SiteIn) -> dict:
    return jobs.submit("site", None, {"url": body.url})


# ====================================================================== projects
@app.get("/api/projects")
def projects() -> list[dict]:
    out = []
    for p in service.list_projects():
        if p["id"].startswith("_"):
            continue
        p["video_url"] = _url(p["id"], p.get("video"))  # the main render (<slug>_web.mp4), never an export
        out.append(p)
    return out


class CreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    mode: Literal["ugc", "influencer", "faceless", "promo"]
    brief: str = Field(min_length=3)
    seconds: float = Field(20.0, ge=5, le=600)
    aspect: Literal["9:16", "16:9", "1:1", "4:5"] = "9:16"
    quality: Literal["draft", "standard", "high", "tv"] = "standard"
    language: str = "English"
    url: str | None = None
    persona: str | None = None
    face_uploads: list[str] = []
    product: str | None = None
    product_uploads: list[str] = []
    style: str | None = None
    seed: int = 42


@app.post("/api/projects", status_code=202)
def project_create(body: CreateIn) -> dict:
    name = _call(service.slug, body.name)
    if (config.OUTPUTS_DIR / name / "project.yaml").is_file():
        raise HTTPException(409, f"a project named {name!r} already exists")
    params = body.model_dump(exclude={"face_uploads", "product_uploads"})
    params["name"] = name
    params["faces"] = [_upload_path(u) for u in body.face_uploads]
    params["product_images"] = [_upload_path(u) for u in body.product_uploads]
    return jobs.submit("create", name, params)


class ImportIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    project: dict[str, Any]


@app.post("/api/projects/import", status_code=201)
def project_import(body: ImportIn) -> dict:
    """Create a project directly from a project definition (e.g. a template or an edited copy)."""
    name = _call(service.slug, body.name)
    folder = config.OUTPUTS_DIR / name
    if (folder / "project.yaml").is_file():
        raise HTTPException(409, f"a project named {name!r} already exists")
    _call(service.replace_project, folder, body.project)
    return {"id": name}


@app.get("/api/projects/{pid}")
def project_get(pid: str) -> dict:
    folder = _folder(pid)
    p = _call(service.load, folder)
    data = p.model_dump(mode="json")
    root = str(folder.resolve()) + "/"
    raw = json.dumps(data).replace(root, "")  # paths inside the project are shown relative to it
    return {"id": pid, "project": json.loads(raw), "status": _call(service.status, folder)}


@app.put("/api/projects/{pid}")
def project_put(pid: str, body: dict[str, Any]) -> dict:
    folder = _folder(pid)
    p = _call(service.replace_project, folder, body)
    p = _call(service.load, folder)  # re-read: relative paths resolved against the project folder
    return {"id": pid, "title": p.title, "scenes": len(p.scenes)}


@app.delete("/api/projects/{pid}")
def project_delete(pid: str) -> dict:
    """Moves the project to outputs/_trash (recoverable), never deletes files."""
    folder = _folder(pid)
    trash = config.OUTPUTS_DIR / "_trash"
    trash.mkdir(exist_ok=True)
    dst = trash / f"{pid}_{int(time.time())}"
    folder.rename(dst)
    return {"id": pid, "moved_to": str(dst)}


@app.get("/api/projects/{pid}/plan")
def project_plan(pid: str) -> dict:
    return _call(service.plan, _folder(pid))


@app.get("/api/projects/{pid}/status")
def project_status(pid: str) -> dict:
    return _call(service.status, _folder(pid))


@app.get("/api/projects/{pid}/media")
def project_media(pid: str) -> dict:
    """URLs of what the UI shows: final videos, cover, contact sheet, per-scene thumbnails and keyframes."""
    folder = _folder(pid)
    out = sorted((folder / "out").glob("*"))
    thumbs = _call(service.scene_thumbnails, folder)
    keyframes = {f.stem.replace("_start", ""): _url(pid, f) for f in sorted((folder / "frames").glob("*_start.png"))}
    return {"outputs": [{"name": f.name, "url": _url(pid, f), "size": f.stat().st_size} for f in out],
            "thumbnails": {k: _url(pid, v) for k, v in thumbs.items()}, "keyframes": keyframes,
            "contact_sheet": _url(pid, folder / "render" / "contact.png") if (folder / "render" / "contact.png").is_file() else None}


@app.get("/api/projects/{pid}/files/{path:path}")
def project_file(pid: str, path: str):
    folder = _folder(pid).resolve()
    f = (folder / path).resolve()
    if not f.is_relative_to(folder) or not f.is_file() or f.name == ".env":
        raise HTTPException(404, "file not found")
    return FileResponse(f)  # supports Range requests (video seeking)


@app.get("/api/projects/{pid}/providers")
def project_providers(pid: str) -> list[dict]:
    from ugc_studio import providers

    return providers.describe(_call(service.load, _folder(pid)))


# ---------------------------------------------------------------------- jobs on a project
class RenderIn(BaseModel):
    deliveries: list[Literal["web", "tv"]] = ["web"]
    only: list[str] | None = None
    qa: bool = True


@app.post("/api/projects/{pid}/render", status_code=202)
def project_render(pid: str, body: RenderIn | None = None) -> dict:
    _folder(pid)
    b = body or RenderIn()
    return jobs.submit("render", pid, b.model_dump())


@app.post("/api/projects/{pid}/mix", status_code=202)
def project_mix(pid: str) -> dict:
    """Narration + mix only (after voice or timeline edits): never re-renders video."""
    _folder(pid)
    return jobs.submit("mix", pid, {})


class ExportIn(BaseModel):
    format: Literal["tv", "web", "vertical", "square", "portrait", "cover"] = "tv"
    at: float = Field(0.0, ge=0)


@app.post("/api/projects/{pid}/export", status_code=202)
def project_export(pid: str, body: ExportIn) -> dict:
    _folder(pid)
    return jobs.submit("export", pid, body.model_dump())


@app.post("/api/projects/{pid}/qa", status_code=202)
def project_qa(pid: str) -> dict:
    _folder(pid)
    return jobs.submit("qa", pid, {})


@app.post("/api/projects/{pid}/preview", status_code=202)
def project_preview(pid: str) -> dict:
    _folder(pid)
    return jobs.submit("preview", pid, {})


# ---------------------------------------------------------------------- voice-over
@app.get("/api/projects/{pid}/voice")
def voice_get(pid: str) -> dict:
    return _call(service.voice_lines, _folder(pid))


class TextIn(BaseModel):
    text: str = Field(min_length=1)


@app.put("/api/projects/{pid}/voice/{sid}")
def voice_put(pid: str, sid: str, body: TextIn) -> dict:
    _call(service.voice_set, _folder(pid), sid, body.text)
    return {"ok": True, "next": "POST /mix to hear it"}


class ScenesIn(BaseModel):
    scenes: list[str] = Field(min_length=1)


@app.post("/api/projects/{pid}/voice/redo")
def voice_redo(pid: str, body: ScenesIn) -> dict:
    _call(service.voice_redo, _folder(pid), body.scenes)
    return {"ok": True}


class EngineIn(BaseModel):
    engine: Literal["auto", "qwen", "chatterbox", "habibi", "elevenlabs", "openai", "gemini"]
    voice_id: str | None = None
    model: str | None = None
    dialect: Literal["MSA", "ALG", "EGY", "IRQ", "MAR"] | None = None


@app.put("/api/projects/{pid}/voice-engine")
def voice_engine(pid: str, body: EngineIn) -> dict:
    _call(service.voice_engine, _folder(pid), body.engine, body.voice_id, body.model, body.dialect)
    return {"ok": True}


@app.post("/api/projects/{pid}/voice-file")
def voice_file(pid: str, file: UploadFile = File(...)) -> dict:
    folder = _folder(pid)
    tmp = _save_upload(file, _uploads())
    _call(service.voice_file, folder, tmp)
    return {"ok": True}


# ---------------------------------------------------------------------- timeline
@app.get("/api/projects/{pid}/timeline")
def timeline_get(pid: str) -> dict:
    """Tracks and clips; extra sounds also get a playable `url` and their file's real length (`file_seconds`)."""
    from ugc_studio.media import probe

    view = _call(service.timeline_view, _folder(pid))
    for tr in view["tracks"]:
        for cl in tr["clips"]:
            if tr["id"] == "audio":
                cl["url"] = _url(pid, cl["file"])
                try:
                    cl["file_seconds"] = round(probe(cl["file"])["seconds"], 3)
                except Exception:  # noqa: BLE001 - unreadable file: the build reports it
                    cl["file_seconds"] = None
    return view


class PlaceIn(BaseModel):
    at: float | None = Field(None, ge=0)  # null = automatic placement
    gain_db: float | None = Field(None, ge=-30, le=12)


@app.put("/api/projects/{pid}/timeline/voice/{sid}")
def timeline_voice(pid: str, sid: str, body: PlaceIn) -> dict:
    _call(service.move_voice, _folder(pid), sid, body.at, body.gain_db)
    return timeline_get(pid)


@app.post("/api/projects/{pid}/timeline/audio", status_code=201)
def timeline_audio_add(pid: str, file: UploadFile = File(...), at: float = Form(0.0), gain_db: float = Form(0.0),
                       fade_in: float = Form(0.0), fade_out: float = Form(0.0), duck: bool = Form(False)) -> dict:
    folder = _folder(pid)
    tmp = _save_upload(file, _uploads())
    name = re.sub(r"^[0-9a-f]{8}_", "", tmp.name)
    renamed = tmp.with_name(name) if not tmp.with_name(name).exists() else tmp
    tmp.rename(renamed)
    clip = _call(service.add_audio, folder, renamed, at, None, gain_db=gain_db, fade_in=fade_in, fade_out=fade_out,
                 duck=duck)
    renamed.unlink(missing_ok=True)
    return clip.model_dump()


class AudioPatch(BaseModel):
    at: float | None = Field(None, ge=0)
    trim_start: float | None = Field(None, ge=0)
    duration: float | None = Field(None, gt=0)
    gain_db: float | None = Field(None, ge=-40, le=12)
    fade_in: float | None = Field(None, ge=0)
    fade_out: float | None = Field(None, ge=0)
    duck: bool | None = None


@app.patch("/api/projects/{pid}/timeline/audio/{cid}")
def timeline_audio_patch(pid: str, cid: str, body: AudioPatch) -> dict:
    _call(service.update_audio, _folder(pid), cid, **body.model_dump(exclude_unset=True))  # null = reset
    return timeline_get(pid)


@app.delete("/api/projects/{pid}/timeline/audio/{cid}")
def timeline_audio_delete(pid: str, cid: str) -> dict:
    _call(service.remove_audio, _folder(pid), cid)
    return timeline_get(pid)


class MusicIn(BaseModel):
    start: float | None = Field(None, ge=0)
    offset: float | None = Field(None, ge=0)
    gain_db: float | None = Field(None, ge=-30, le=12)
    fade_in: float | None = Field(None, ge=0)
    fade_out: float | None = Field(None, ge=0)


@app.put("/api/projects/{pid}/timeline/music")
def timeline_music(pid: str, body: MusicIn) -> dict:
    _call(service.set_music, _folder(pid), **body.model_dump())
    return timeline_get(pid)


# ---------------------------------------------------------------------- fixes
class FixIn(BaseModel):
    at: float | None = Field(None, ge=0)
    duration: float = Field(0.1, gt=0, le=10)
    mode: Literal["auto", "interpolate", "freeze", "retake", "reshoot"] = "auto"
    prompt: str | None = None
    seed: int | None = None
    scene: str | None = None


@app.post("/api/projects/{pid}/fixes")
def fix_add(pid: str, body: FixIn) -> dict:
    return _call(service.add_fix, _folder(pid), body.at, body.duration, body.mode, body.prompt, body.seed, body.scene)


@app.delete("/api/projects/{pid}/fixes/{sid}")
def fix_undo(pid: str, sid: str) -> dict:
    return _call(service.undo_fix, _folder(pid), sid)


# ====================================================================== jobs
@app.get("/api/jobs")
def jobs_list(project: str | None = None, limit: int = 50) -> list[dict]:
    return jobs.list_jobs(project, min(200, max(1, limit)))


@app.get("/api/jobs/{jid}")
def job_get(jid: str) -> dict:
    job = jobs.get(jid)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@app.post("/api/jobs/{jid}/cancel")
def job_cancel(jid: str) -> dict:
    try:
        return jobs.cancel(jid)
    except KeyError:
        raise HTTPException(404, "job not found") from None


@app.get("/api/jobs/{jid}/events")
async def job_events(jid: str, request: Request, since: int = 0):
    """Server-Sent Events: every progress line, then the final job record (event: end). A browser reconnect resumes
    after the last event it received (Last-Event-ID)."""
    if not jobs.get(jid):
        raise HTTPException(404, "job not found")
    last = request.headers.get("last-event-id", "")
    if last.isdigit():
        since = max(since, int(last))

    async def stream():
        n = since
        last_ping = time.time()
        while True:
            evs = await asyncio.to_thread(jobs.store().events, jid, n)
            for ev in evs:
                n += 1
                yield f"id: {n}\nevent: {ev.get('event', 'message')}\ndata: {json.dumps(ev, default=str)}\n\n"
            job = await asyncio.to_thread(jobs.get, jid)
            if job and job["status"] in jobs.TERMINAL and not evs:
                yield f"event: end\ndata: {json.dumps(job, default=str)}\n\n"
                return
            if time.time() - last_ping > 15:
                last_ping = time.time()
                yield ": ping\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
