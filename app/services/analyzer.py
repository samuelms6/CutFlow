from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from typing import Any

from ..config import MAX_CLIPS, OPENAI_API_KEY, OPENAI_MODEL
from .audiovisual import AVMap, activity_stats, auto_clip_budget, build_visual_windows

HOOK_WORDS = {
    "segredo", "erro", "nunca", "sempre", "ninguém", "melhor", "pior", "verdade", "motivo", "como", "porque", "por que",
    "atenção", "importante", "incrível", "rápido", "fácil", "difícil", "descobri", "pare", "evite", "secret", "mistake", "never",
    "always", "best", "worst", "truth", "why", "how", "important", "stop", "avoid"
}


@dataclass
class Candidate:
    start: float
    end: float
    score: float
    title: str
    hook: str
    reason: str
    transcript: str = ""
    score_breakdown: dict[str, float] | None = None
    analysis_mode: str = "audiovisual"
    natural_end: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean_title(text: str, index: int) -> str:
    text = re.sub(r"\s+", " ", text).strip(" -–—.,:;!?\n")
    words = text.split()
    return (" ".join(words[:11])[:90] if words else f"Destaque {index}")


def _sentence_boundary(text: str) -> bool:
    return bool(re.search(r"[.!?…][\"')\]]?$", text.strip()))


def _semantic_score(parts: list[dict[str, Any]], start: float, end: float) -> tuple[float, dict[str, float], str, str]:
    transcript = " ".join(str(x.get("text", "")) for x in parts).strip()
    normalized = transcript.lower()
    words = re.findall(r"\b[\wÀ-ÿ'-]+\b", normalized)
    seconds = max(end - start, 1.0)
    wps = len(words) / seconds
    hook = min(18.0, sum(1 for token in HOOK_WORDS if token in normalized) * 4.5)
    opening = str(parts[0].get("text", "")).lower() if parts else ""
    opening_hook = 8.0 if any(k in opening for k in HOOK_WORDS) else 0.0
    question = 7.0 if "?" in transcript else 0.0
    density = max(0.0, 16.0 - abs(wps - 2.4) * 8.0)
    closure = 14.0 if _sentence_boundary(str(parts[-1].get("text", ""))) else 5.0
    length = 12.0 if 22 <= seconds <= 65 else max(2.0, 12.0 - abs(seconds - 45) * 0.3)
    completeness = min(16.0, closure + (4.0 if len(parts) >= 2 else 0.0))
    score = min(100.0, 24.0 + hook + opening_hook + question + density + length + completeness)
    breakdown = {
        "gancho": round(min(25.0, hook + opening_hook + question), 1),
        "ritmo": round(min(22.0, density + length * 0.45), 1),
        "completude": round(completeness, 1),
        "semântica": round(min(22.0, 8.0 + len(parts) * 1.5), 1),
    }
    reasons = []
    if breakdown["gancho"] >= 12: reasons.append("gancho forte")
    if density >= 11: reasons.append("bom ritmo de fala")
    if completeness >= 13: reasons.append("fecha uma ideia completa")
    if not reasons: reasons.append("trecho coerente e autocontido")
    hook_text = _clean_title(str(parts[0].get("text", "")), 1) if parts else "Trecho com início natural"
    return score, breakdown, ", ".join(reasons).capitalize(), hook_text


def build_semantic_candidates(segments: list[dict[str, Any]], duration: float, min_duration: int, max_duration: int) -> list[Candidate]:
    if not segments:
        return []
    candidates: list[Candidate] = []
    for i, seg in enumerate(segments):
        start = float(seg["start"])
        if start >= duration - min_duration:
            continue
        parts: list[dict[str, Any]] = []
        end = start
        for nxt in segments[i:]:
            nstart, nend = float(nxt["start"]), float(nxt["end"])
            if nstart - end > 3.2 and parts:
                break
            if nend - start > max_duration + 4:
                break
            parts.append(nxt)
            end = nend
            elapsed = end - start
            if elapsed >= min_duration and (_sentence_boundary(str(nxt.get("text", ""))) or elapsed >= max_duration * 0.9):
                score, breakdown, reason, hook = _semantic_score(parts, start, end)
                transcript = " ".join(str(x.get("text", "")) for x in parts).strip()
                candidates.append(Candidate(start, min(end, duration), round(score, 1), "", hook, reason, transcript, breakdown, "transcript", True))
                if elapsed >= max_duration * 0.72:
                    break
    candidates.sort(key=lambda c: c.score, reverse=True)
    selected: list[Candidate] = []
    for cand in candidates:
        if cand.score < 59 and selected:
            continue
        overlaps = any(max(cand.start, s.start) < min(cand.end, s.end) - 4 for s in selected)
        if overlaps:
            continue
        selected.append(cand)
        if len(selected) >= auto_clip_budget(duration) * 2:
            break
    for idx, cand in enumerate(selected, 1):
        cand.title = _clean_title(cand.transcript, idx)
    return selected


def build_audiovisual_candidates(av: AVMap, min_duration: int, max_duration: int, source_title: str) -> list[Candidate]:
    windows = build_visual_windows(av, min_duration, max_duration)
    result: list[Candidate] = []
    clean_source = re.sub(r"[_-]+", " ", source_title or "Vídeo").strip()
    clean_source = re.sub(r"\s+", " ", clean_source)[:72]
    for idx, w in enumerate(windows, 1):
        s = w["stats"]
        breakdown = {
            "intensidade": round(s["activity"] * 28, 1),
            "pico": round(s["peak"] * 24, 1),
            "movimento": round(s["motion"] * 18, 1),
            "áudio": round(s["audio"] * 14, 1),
            "transições": round(s["scene_density"] * 8, 1),
            "fechamento": 8.0 if w["end_natural"] else 3.0,
        }
        reasons = []
        if s["peak"] >= .65: reasons.append("pico forte de atividade")
        if s["motion"] >= .55: reasons.append("movimento acima da média")
        if s["audio"] >= .55: reasons.append("energia sonora elevada")
        if s["scene_density"] >= .45: reasons.append("boa dinâmica de cenas")
        if w["end_natural"]: reasons.append("encerramento alinhado a uma transição natural")
        if not reasons: reasons.append("melhor combinação local de ritmo visual e áudio")
        title = f"{clean_source} — destaque {idx}" if clean_source else f"Destaque {idx}"
        hook = "Sequência de alta intensidade" if s["peak"] >= .65 else "Momento de maior destaque do vídeo"
        result.append(Candidate(
            w["start"], w["end"], w["score"], title[:110], hook,
            ", ".join(reasons).capitalize(), "", breakdown, "audiovisual", bool(w["end_natural"])
        ))
    return result


def _av_bonus(av: AVMap, start: float, end: float) -> tuple[float, dict[str, float]]:
    s = activity_stats(av, start, end)
    bonus = s["activity"] * 10 + s["peak"] * 6 + s["scene_density"] * 3
    return bonus, {
        "visual": round(s["activity"] * 12, 1),
        "pico visual": round(s["peak"] * 8, 1),
    }


def select_best_candidates(
    av: AVMap,
    segments: list[dict[str, Any]],
    min_duration: int,
    max_duration: int,
    source_title: str,
    transcribe_enabled: bool,
) -> list[Candidate]:
    visual = build_audiovisual_candidates(av, min_duration, max_duration, source_title)
    semantic = build_semantic_candidates(segments, av.duration, min_duration, max_duration) if transcribe_enabled and segments else []

    pool: list[Candidate] = []
    for c in semantic:
        bonus, av_breakdown = _av_bonus(av, c.start, c.end)
        c.score = round(min(100.0, c.score * 0.82 + bonus), 1)
        c.score_breakdown = {**(c.score_breakdown or {}), **av_breakdown}
        c.analysis_mode = "híbrido"
        pool.append(c)
    # Visual candidates stay in the pool so action/music moments are not missed just because speech exists.
    pool.extend(visual)
    pool.sort(key=lambda c: c.score, reverse=True)

    selected: list[Candidate] = []
    budget = min(MAX_CLIPS, auto_clip_budget(av.duration))
    threshold = 57.0
    for cand in pool:
        if cand.score < threshold and selected:
            continue
        overlap = any(max(cand.start, s.start) < min(cand.end, s.end) - min_duration * .35 for s in selected)
        if overlap:
            continue
        selected.append(cand)
        if len(selected) >= budget:
            break
    if not selected and pool:
        selected = pool[:1]
    selected.sort(key=lambda c: c.start)

    # Rename generic audiovisual titles after final chronological order.
    for idx, c in enumerate(selected, 1):
        if c.analysis_mode == "audiovisual":
            clean_source = re.sub(r"[_-]+", " ", source_title or "Vídeo").strip()
            c.title = f"{clean_source[:70]} — momento {idx}" if clean_source else f"Momento {idx}"
    return selected


def enrich_with_openai(candidates: list[Candidate]) -> list[Candidate]:
    if not OPENAI_API_KEY or not OPENAI_MODEL or not candidates:
        return candidates
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        payload = [{
            "index": i, "start": c.start, "end": c.end, "score_local": c.score,
            "analysis_mode": c.analysis_mode, "reason": c.reason,
            "transcript": c.transcript[:5000], "title": c.title,
        } for i, c in enumerate(candidates[:MAX_CLIPS])]
        response = client.responses.create(
            model=OPENAI_MODEL,
            input=(
                "Você é um editor profissional de vídeos curtos. Reordene apenas se necessário, refine score, título, gancho, motivo, descrição e hashtags. "
                "Não invente fatos que não estejam no texto/título disponível. Em cortes sem transcrição, seja descritivo e não invente falas. "
                f"Candidatos={json.dumps(payload, ensure_ascii=False)}"
            ),
            text={"format": {"type": "json_schema", "name": "clip_ranking", "strict": True, "schema": {
                "type": "object", "properties": {"clips": {"type": "array", "items": {"type": "object", "properties": {
                    "index": {"type": "integer"}, "score": {"type": "number"}, "title": {"type": "string"}, "hook": {"type": "string"},
                    "reason": {"type": "string"}, "description": {"type": "string"}, "hashtags": {"type": "array", "items": {"type": "string"}},
                    "title_options": {"type": "array", "items": {"type": "string"}}
                }, "required": ["index", "score", "title", "hook", "reason", "description", "hashtags", "title_options"], "additionalProperties": False}}},
                "required": ["clips"], "additionalProperties": False
            }}},
        )
        parsed = json.loads(response.output_text)
        result: list[Candidate] = []
        for item in parsed.get("clips", []):
            idx = int(item["index"])
            if 0 <= idx < len(candidates):
                c = candidates[idx]
                c.score = max(0, min(100, float(item["score"])))
                c.title = str(item["title"])[:120]
                c.hook = str(item["hook"])[:180]
                c.reason = str(item["reason"])[:350]
                setattr(c, "social", {"description": str(item["description"])[:500], "hashtags": item["hashtags"][:15], "title_options": item["title_options"][:3]})
                result.append(c)
        return result or candidates
    except Exception:
        return candidates


def _keywords_from_title(source_title: str) -> list[str]:
    raw = re.findall(r"\b[\wÀ-ÿ]{3,}\b", source_title.lower())
    stop = {"video", "vídeo", "official", "oficial", "full", "hd", "1080p", "music", "audio", "com", "para", "the", "and", "uma", "dos", "das"}
    out=[]
    for w in raw:
        if w not in stop and w not in out:
            out.append(w)
    return out


def local_social_copy(candidate: Candidate, source_title: str = "") -> dict[str, Any]:
    transcript_keywords = re.findall(r"\b[\wÀ-ÿ]{5,}\b", candidate.transcript.lower()) if candidate.transcript else []
    keywords = transcript_keywords + _keywords_from_title(source_title)
    stop = {"porque", "quando", "muito", "sobre", "também", "entre", "depois", "assim", "então", "there", "about", "would", "could"}
    uniq=[]
    for w in keywords:
        if w not in stop and w not in uniq:
            uniq.append(w)
    tags=["#" + re.sub(r"[^\wÀ-ÿ]", "", w) for w in uniq[:6]]
    tags += ["#cortes", "#shorts"]
    title = candidate.title or "Momento em destaque"
    if candidate.transcript:
        description = candidate.transcript[:220].rstrip() + ("…" if len(candidate.transcript) > 220 else "")
    else:
        description = f"{candidate.hook}. {candidate.reason}."
    return {
        "title_options": [title, candidate.hook[:120], f"Destaque: {title}"[:120]],
        "description": description[:500],
        "hashtags": tags[:8],
    }
