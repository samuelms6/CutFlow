from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable
from ..config import MAX_VIDEO_MINUTES, YTDLP_COOKIES_FILE, YTDLP_PROXY


class MediaError(RuntimeError): pass


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path: raise MediaError(f"Dependência '{name}' não encontrada no sistema.")
    return path


def run(cmd: list[str], cwd: Path | None = None, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    try: return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc: raise MediaError("A operação excedeu o tempo limite. Tente novamente ou use upload de MP4.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        lowered = detail.lower()
        if "private video" in lowered: raise MediaError("O vídeo é privado. Use um arquivo MP4 autorizado ou configure cookies do YouTube.") from exc
        if "sign in" in lowered or "confirm you’re not a bot" in lowered or "confirm you're not a bot" in lowered: raise MediaError("O YouTube solicitou autenticação. Configure YTDLP_COOKIES_FILE ou envie o MP4 diretamente.") from exc
        if "video unavailable" in lowered: raise MediaError("O vídeo não está disponível para download nesta região/conta.") from exc
        raise MediaError(detail[-3500:]) from exc


def validate_youtube_url(url: str) -> None:
    if not re.match(r"^https?://(www\.)?(youtube\.com|youtu\.be|music\.youtube\.com)/", url, re.I):
        raise MediaError("A URL precisa ser um link válido do YouTube.")
    if "list=" in url and "watch?v=" not in url:
        raise MediaError("Cole a URL de um vídeo individual, não de uma playlist.")


def download_youtube(url: str, workdir: Path, progress_cb: Callable[[int, str], None] | None = None) -> tuple[Path, dict[str, Any]]:
    require_binary("yt-dlp"); require_binary("ffmpeg"); validate_youtube_url(url)
    outtmpl = str(workdir / "source.%(ext)s")
    cmd = ["yt-dlp", "--no-playlist", "--newline", "--retries", "5", "--fragment-retries", "5", "--socket-timeout", "20", "--concurrent-fragments", "4",
           "--write-auto-subs", "--write-subs", "--sub-langs", "pt.*,en.*", "--sub-format", "srt/best", "--convert-subs", "srt",
           "--merge-output-format", "mp4", "-f", "bv*[height<=1080]+ba/b[height<=1080]/b", "--print-json", "-o", outtmpl]
    if YTDLP_COOKIES_FILE: cmd += ["--cookies", YTDLP_COOKIES_FILE]
    if YTDLP_PROXY: cmd += ["--proxy", YTDLP_PROXY]
    cmd.append(url)
    if progress_cb: progress_cb(10, "Conectando ao YouTube")
    proc = run(cmd, cwd=workdir, timeout=60 * 60)
    if progress_cb: progress_cb(22, "Download e legendas concluídos")
    metadata: dict[str, Any] = {}
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try: metadata = json.loads(line); break
            except Exception: pass
    candidates = sorted([p for p in workdir.glob("source.*") if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4v"}], key=lambda p: p.stat().st_size, reverse=True)
    if not candidates: raise MediaError("O vídeo não foi baixado. Use o upload de MP4 como alternativa.")
    return candidates[0], metadata


def probe(path: Path) -> dict[str, Any]:
    require_binary("ffprobe")
    proc = run(["ffprobe", "-v", "error", "-show_entries", "format=duration,size,format_name:stream=index,codec_type,codec_name,width,height,r_frame_rate", "-of", "json", str(path)], timeout=120)
    data = json.loads(proc.stdout); duration = float(data.get("format", {}).get("duration") or 0)
    if duration <= 0: raise MediaError("Não foi possível identificar a duração do vídeo.")
    if duration > MAX_VIDEO_MINUTES * 60: raise MediaError(f"O vídeo excede o limite de {MAX_VIDEO_MINUTES} minutos.")
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not v: raise MediaError("O arquivo não contém uma faixa de vídeo válida.")
    return {"duration": duration, "width": v.get("width"), "height": v.get("height"), "video_codec": v.get("codec_name"), "has_audio": bool(a), "audio_codec": a.get("codec_name") if a else None, "format": data.get("format", {}).get("format_name")}
