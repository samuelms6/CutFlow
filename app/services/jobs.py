from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from celery import shared_task

from ..db import get_job, update_job
from .analyzer import enrich_with_openai, local_social_copy, select_best_candidates
from .audiovisual import analyze_audiovisual
from .media import MediaError, download_youtube, probe
from .render import render_clip
from .transcript import discover_subtitles, transcribe_with_whisper


def job_dir(job_id: str) -> Path:
    p = Path(__file__).resolve().parents[2] / "data" / "jobs" / job_id
    # Keep compatibility with config-controlled data dir if imported there.
    try:
        from ..config import JOBS_DIR
        p = JOBS_DIR / job_id
    except Exception:
        pass
    p.mkdir(parents=True, exist_ok=True)
    return p


def _set(job_id: str, progress: int, stage: str, message: str, status: str = "processing"):
    update_job(job_id, status=status, progress=max(0, min(100, int(progress))), stage=stage, message=message)


def _segments_path(workdir: Path) -> Path:
    return workdir / "transcript.json"


def _save_segments(workdir: Path, segments: list[dict[str, Any]]):
    _segments_path(workdir).write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")


def _load_segments(workdir: Path) -> list[dict[str, Any]]:
    p = _segments_path(workdir)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def enqueue_url_job(job_id: str, url: str, options: dict[str, Any]):
    process_job.delay(job_id, "url", url, None, options)


def enqueue_upload_job(job_id: str, upload_path: Path, options: dict[str, Any]):
    process_job.delay(job_id, "upload", None, str(upload_path), options)


def _source_for_job(workdir: Path) -> Path | None:
    files = [p for p in workdir.glob("source*") if p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}]
    return max(files, key=lambda p: p.stat().st_size) if files else None


@shared_task(bind=True, autoretry_for=(), name="cutflow.process_job")
def process_job(self, job_id: str, source_type: str, url: str | None, upload_path: str | None, options: dict[str, Any]):
    try:
        workdir = job_dir(job_id)
        _set(job_id, 3, "source", "Preparando fonte e validando parâmetros")
        source_meta: dict[str, Any] = {}
        if source_type == "url":
            source, source_meta = download_youtube(str(url), workdir, lambda p, m: _set(job_id, min(18, 4 + int(p * .6)), "download", m))
        else:
            source = Path(str(upload_path)) if upload_path else None
            if not source or not source.exists():
                raise MediaError("Arquivo enviado não foi encontrado.")

        _set(job_id, 20, "probe", "Validando vídeo, áudio e duração")
        media = probe(source)
        transcribe_enabled = bool(options.get("transcribe", True))
        source_title = source_meta.get("title") or (Path(str(upload_path)).name.removeprefix("source-upload-") if source_type == "upload" and upload_path else source.stem)
        source_title = Path(str(source_title)).stem
        metadata = {
            "title": source_title,
            "channel": source_meta.get("uploader") or source_meta.get("channel"),
            "thumbnail": source_meta.get("thumbnail"),
            "duration": round(media["duration"], 2),
            "width": media.get("width"),
            "height": media.get("height"),
            "video_codec": media.get("video_codec"),
            "audio_codec": media.get("audio_codec"),
            "has_audio": media.get("has_audio"),
            "source_type": source_type,
            "options": options,
        }
        update_job(job_id, metadata_json=metadata)

        _set(job_id, 24, "audiovisual", "Analisando cenas, movimento e energia do áudio")
        av = analyze_audiovisual(
            source,
            float(media["duration"]),
            bool(media.get("has_audio")),
            lambda ratio, msg: _set(job_id, 24 + int(ratio * 20), "audiovisual", f"{msg} · {int(ratio * 100)}%"),
        )
        (workdir / "audiovisual-map.json").write_text(json.dumps(av.to_dict(), ensure_ascii=False), encoding="utf-8")
        metadata["audiovisual"] = av.summary
        metadata["natural_boundaries"] = len(av.natural_boundaries)
        update_job(job_id, metadata_json=metadata)

        segments: list[dict[str, Any]] = []
        transcript_source = "disabled"
        trans_info: dict[str, Any] = {"enabled": transcribe_enabled}
        if transcribe_enabled:
            _set(job_id, 45, "transcript", "Procurando legendas ou transcrevendo fala")
            segments = discover_subtitles(workdir)
            transcript_source = "subtitles" if segments else "none"
            if not segments:
                segments, trans_info = transcribe_with_whisper(source, lambda p, m: _set(job_id, 45 + int((p - 36) / 10 * 14), "transcript", m))
                transcript_source = "whisper" if segments else "none"
        else:
            _set(job_id, 58, "transcript", "Transcrição desativada — usando análise audiovisual")
        _save_segments(workdir, segments)
        metadata.update({
            "transcript_source": transcript_source,
            "transcript_segments": len(segments),
            "transcription": trans_info,
            "analysis_mode": "hybrid" if transcribe_enabled and segments else "audiovisual",
        })
        update_job(job_id, metadata_json=metadata)

        _set(job_id, 61, "analysis", "Escolhendo os melhores momentos e fechamentos naturais")
        selected = select_best_candidates(
            av,
            segments,
            int(options["min_duration"]),
            int(options["max_duration"]),
            str(source_title),
            transcribe_enabled,
        )
        selected = enrich_with_openai(selected)
        if not selected:
            raise MediaError("Nenhum trecho atingiu qualidade suficiente. Tente ampliar a faixa de duração.")

        clips_dir = workdir / "clips"
        clips_dir.mkdir(exist_ok=True)
        clips: list[dict[str, Any]] = []
        total = len(selected)
        _set(job_id, 65, "analysis", f"{total} melhores momentos encontrados")

        for idx, cand in enumerate(selected, 1):
            base = 66 + int((idx - 1) / max(total, 1) * 32)
            span = max(2, int(30 / max(total, 1)))
            _set(job_id, base, "render", f"Gerando corte {idx} de {total}")
            filename = f"corte-{idx:02d}.mp4"
            output = clips_dir / filename
            subtitle_style = str(options.get("subtitle_style", "viral")) if transcribe_enabled and segments else "none"
            render_meta = render_clip(
                source,
                output,
                cand.start,
                cand.end,
                segments,
                subtitle_style,
                str(options.get("preset", "tiktok")),
                str(options.get("framing", "auto")),
                media,
                lambda ratio, b=base, s=span: _set(job_id, b + int(ratio * s), "render", f"Renderizando corte {idx}/{total} · {int(ratio * 100)}%"),
            )
            social = getattr(cand, "social", None) or local_social_copy(cand, str(source_title))
            clip = {
                "id": uuid.uuid4().hex,
                "index": idx,
                "status": "ready",
                "title": cand.title,
                "hook": cand.hook,
                "reason": cand.reason,
                "score": round(cand.score, 1),
                "score_breakdown": cand.score_breakdown or {},
                "analysis_mode": cand.analysis_mode,
                "natural_end": cand.natural_end,
                "start": round(cand.start, 2),
                "end": round(cand.end, 2),
                "duration": round(cand.end - cand.start, 2),
                "filename": filename,
                "url": f"/media/{job_id}/clips/{filename}",
                "subtitle_style": subtitle_style,
                "preset": options.get("preset", "tiktok"),
                "framing": render_meta.get("framing", "auto"),
                "face_confidence": render_meta.get("face_confidence", 0),
                "tracking_subject": render_meta.get("tracking_subject", "none"),
                "description": social.get("description", ""),
                "hashtags": social.get("hashtags", []),
                "title_options": social.get("title_options", []),
            }
            clips.append(clip)
            update_job(job_id, clips_json=clips)

        update_job(job_id, status="completed", progress=100, stage="completed", message=f"{len(clips)} cortes de alta relevância prontos", clips_json=clips, metadata_json=metadata, error=None)
        return {"job_id": job_id, "clips": len(clips)}
    except Exception as exc:
        update_job(job_id, status="failed", stage="failed", message="Falha no processamento", error=str(exc), progress=100)
        raise


@shared_task(bind=True, name="cutflow.rerender_clip")
def rerender_clip(self, job_id: str, clip_id: str, edits: dict[str, Any]):
    job = get_job(job_id)
    if not job:
        raise MediaError("Projeto não encontrado")
    clips = job.get("clips", [])
    pos = next((i for i, c in enumerate(clips) if c.get("id") == clip_id), None)
    if pos is None:
        raise MediaError("Corte não encontrado")
    clip = dict(clips[pos])
    clip.update({k: v for k, v in edits.items() if v is not None})
    clip["status"] = "rendering"
    clips[pos] = clip
    update_job(job_id, clips_json=clips, message=f"Rerenderizando {clip.get('title', 'corte')}")
    workdir = job_dir(job_id)
    source = _source_for_job(workdir)
    if not source:
        raise MediaError("Arquivo-fonte não encontrado")
    metadata = job.get("metadata", {})
    segments = _load_segments(workdir)
    start = float(clip.get("start", 0))
    end = float(clip.get("end", 0))
    if end <= start or end - start < 5:
        raise MediaError("O corte precisa ter pelo menos 5 segundos")
    if end > float(metadata.get("duration") or end):
        raise MediaError("O fim do corte excede a duração do vídeo")
    output = workdir / "clips" / clip["filename"]
    style = str(clip.get("subtitle_style", "none"))
    if metadata.get("transcript_source") in {"disabled", "none"}:
        style = "none"
    render_meta = render_clip(source, output, start, end, segments, style, str(clip.get("preset", "tiktok")), str(clip.get("framing", "auto")), metadata)
    revision = int(clip.get("revision", 0)) + 1
    clip.update({
        "status": "ready",
        "duration": round(end - start, 2),
        "subtitle_style": style,
        "framing": render_meta.get("framing", clip.get("framing")),
        "face_confidence": render_meta.get("face_confidence", 0),
        "tracking_subject": render_meta.get("tracking_subject", "none"),
        "revision": revision,
        "url": f"/media/{job_id}/clips/{clip['filename']}?v={revision}",
    })
    clips[pos] = clip
    update_job(job_id, clips_json=clips, message=f"{len(clips)} cortes prontos")
    return clip


def remove_job_files(job_id: str):
    p = job_dir(job_id)
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
