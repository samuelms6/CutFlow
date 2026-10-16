from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from ..config import WHISPER_COMPUTE_TYPE, WHISPER_DEVICE, WHISPER_ENABLED, WHISPER_MODEL


def _ts_to_seconds(value: str) -> float:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    if len(parts) == 3:
        h, m, s = parts
    else:
        h = "0"; m, s = parts
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_srt(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    blocks = re.split(r"\n\s*\n", text.strip())
    segments: list[dict[str, Any]] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        time_idx = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if time_idx is None:
            continue
        left, right = [x.strip() for x in lines[time_idx].split("-->", 1)]
        start = _ts_to_seconds(left); end = _ts_to_seconds(right.split()[0])
        body = re.sub(r"<[^>]+>", "", " ".join(lines[time_idx + 1:])).strip()
        if body and end > start:
            words = []
            tokens = body.split()
            step = (end - start) / max(len(tokens), 1)
            for i, token in enumerate(tokens):
                words.append({"word": token, "start": start + i * step, "end": start + (i + 1) * step})
            segments.append({"start": start, "end": end, "text": body, "words": words})
    return segments


def discover_subtitles(workdir: Path) -> list[dict[str, Any]]:
    srt_files = sorted(workdir.glob("*.srt"), key=lambda p: ("pt" not in p.name.lower(), p.name))
    for path in srt_files:
        segments = parse_srt(path)
        if segments:
            return segments
    return []


def transcribe_with_whisper(video_path: Path, progress_cb=None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not WHISPER_ENABLED:
        return [], {"enabled": False}
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return [], {"enabled": True, "error": "faster-whisper não está instalado"}
    if progress_cb:
        progress_cb(36, "Carregando modelo de transcrição")
    model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE)
    stream, info = model.transcribe(
        str(video_path), vad_filter=True, word_timestamps=True, beam_size=5,
        condition_on_previous_text=False,
    )
    result: list[dict[str, Any]] = []
    for idx, seg in enumerate(stream, 1):
        text = (seg.text or "").strip()
        if not text:
            continue
        words = []
        for word in seg.words or []:
            if word.start is None or word.end is None:
                continue
            words.append({"word": (word.word or "").strip(), "start": float(word.start), "end": float(word.end), "probability": float(word.probability or 0)})
        result.append({"start": float(seg.start), "end": float(seg.end), "text": text, "words": words})
        if progress_cb and idx % 8 == 0:
            progress_cb(min(46, 36 + idx // 8), f"Transcrevendo áudio · {idx} segmentos")
    return result, {"language": getattr(info, "language", None), "language_probability": getattr(info, "language_probability", None), "model": WHISPER_MODEL}
