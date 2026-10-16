from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import BASE_DIR, JOBS_DIR, MAX_UPLOAD_MB
from .db import create_job, delete_job, get_job, init_db, list_jobs, update_job
from .models import ClipEditRequest, JobOptions, UrlJobRequest
from .services.jobs import enqueue_upload_job, enqueue_url_job, job_dir, remove_job_files, rerender_clip
from .services.media import MediaError, probe

app = FastAPI(title="CutFlow Studio", version="3.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")


@app.on_event("startup")
def startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/health")
def health():
    return {"ok": True, "service": "CutFlow Studio", "version": "3.0.0", "queue": "celery+redis"}


@app.get("/api/jobs")
def jobs():
    return {"items": list_jobs()}


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    item = get_job(job_id)
    if not item:
        raise HTTPException(404, "Projeto não encontrado")
    return item


@app.post("/api/jobs/url", status_code=202)
def create_url_job(payload: UrlJobRequest):
    job_id = uuid.uuid4().hex
    item = create_job(job_id, "url", source_url=str(payload.url))
    options = JobOptions(**payload.model_dump(exclude={"url", "authorization_confirmed"})).model_dump()
    enqueue_url_job(job_id, str(payload.url), options)
    return item


@app.post("/api/jobs/upload", status_code=202)
async def create_upload_job(
    file: UploadFile = File(...),
    min_duration: int = Form(20),
    max_duration: int = Form(60),
    transcribe: bool = Form(True),
    subtitle_style: str = Form("viral"),
    preset: str = Form("tiktok"),
    framing: str = Form("auto"),
    authorization_confirmed: bool = Form(False),
):
    if not authorization_confirmed:
        raise HTTPException(400, "Confirme que possui autorização para processar o conteúdo.")
    try:
        options = JobOptions(
            min_duration=min_duration,
            max_duration=max_duration,
            transcribe=transcribe,
            subtitle_style=subtitle_style,
            preset=preset,
            framing=framing,
        )
    except Exception as exc:
        raise HTTPException(422, str(exc))

    original = file.filename or "video.mp4"
    ext = Path(original).suffix.lower()
    if ext not in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}:
        raise HTTPException(415, "Formato não suportado. Use MP4, MOV, MKV, WEBM ou M4V.")
    if file.content_type and not (file.content_type.startswith("video/") or file.content_type in {"application/octet-stream", "application/x-matroska"}):
        raise HTTPException(415, "O arquivo enviado não foi reconhecido como vídeo.")

    job_id = uuid.uuid4().hex
    workdir = job_dir(job_id)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(original).name)[:120]
    upload_path = workdir / f"source-upload-{safe}"
    size = 0
    with upload_path.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_MB * 1024 * 1024:
                upload_path.unlink(missing_ok=True)
                raise HTTPException(413, f"Arquivo excede {MAX_UPLOAD_MB} MB.")
            out.write(chunk)
    try:
        probe(upload_path)
    except MediaError as exc:
        upload_path.unlink(missing_ok=True)
        raise HTTPException(422, str(exc))

    item = create_job(job_id, "upload", original_name=original)
    enqueue_upload_job(job_id, upload_path, options.model_dump())
    return item


@app.patch("/api/jobs/{job_id}/clips/{clip_id}", status_code=202)
def edit_clip(job_id: str, clip_id: str, payload: ClipEditRequest):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Projeto não encontrado")
    clips = job.get("clips", [])
    pos = next((i for i, c in enumerate(clips) if c.get("id") == clip_id), None)
    if pos is None:
        raise HTTPException(404, "Corte não encontrado")
    clips[pos] = {**clips[pos], "status": "queued"}
    update_job(job_id, clips_json=clips, message=f"Edição de {clips[pos].get('title', 'corte')} na fila")
    rerender_clip.delay(job_id, clip_id, payload.model_dump(exclude_none=True))
    return {"ok": True, "message": "Rerenderização adicionada à fila"}


@app.delete("/api/jobs/{job_id}", status_code=204)
def remove_job(job_id: str):
    if not get_job(job_id):
        raise HTTPException(404, "Projeto não encontrado")
    delete_job(job_id)
    remove_job_files(job_id)


@app.get("/media/{job_id}/{path:path}")
def media(job_id: str, path: str):
    root = (JOBS_DIR / job_id).resolve()
    target = (root / path).resolve()
    if root not in target.parents and target != root:
        raise HTTPException(403, "Caminho inválido")
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "Arquivo não encontrado")
    return FileResponse(target, headers={"Cache-Control": "no-store"})
