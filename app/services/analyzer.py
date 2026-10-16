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


def _topic_from_title(source_title: str) -> str:
    raw = re.findall(r"\b[\wÀ-ÿ]{3,}\b", re.sub(r"[_-]+", " ", source_title or ""))
    stop = {
        "video", "vídeo", "official", "oficial", "full", "1080p", "720p", "2160p", "h264", "h265",
        "music", "audio", "football", "soccer", "compilation", "highlights", "performance", "performances",
        "greatest", "iconic", "king", "the", "and", "com", "para", "dos", "das"
    }
    words = []
    for word in raw:
        if word.lower() not in stop and word.lower() not in {w.lower() for w in words}:
            words.append(word)
        if len(words) >= 2:
            break
    return " ".join(words)


def _visual_title(stats: dict[str, float], source_title: str) -> tuple[str, str]:
    topic = _topic_from_title(source_title)
    if stats["peak"] >= 0.78 and stats["motion"] >= 0.58:
        label = "Sequência de alta intensidade"
        hook = "Pico de ação e movimento"
    elif stats["scene_density"] >= 0.58 and stats["motion"] >= 0.45:
        label = "Sequência dinâmica de cenas"
        hook = "Ritmo visual forte"
    elif stats["audio"] >= 0.65 and stats["peak"] >= 0.62:
        label = "Momento de alta energia"
        hook = "Pico visual e sonoro"
    elif stats["motion"] >= 0.62:
        label = "Movimento intenso em destaque"
        hook = "Ação acima da média"
    elif stats["peak"] >= 0.68:
        label = "Pico visual do vídeo"
        hook = "Momento de maior intensidade"
    else:
        label = "Trecho de ritmo crescente"
        hook = "Boa combinação de movimento e ritmo"
    title = f"{topic} · {label}" if topic else label
    return title[:110], hook


def _calibrate_scores(candidates: list[Candidate]) -> list[Candidate]:
    if not candidates:
        return candidates
    raw = [float(c.score) for c in candidates]
    lo, hi = min(raw), max(raw)
    spread = hi - lo
    for candidate in candidates:
        if spread >= 7.0:
            relative = max(0.0, min(1.0, (candidate.score - lo) / spread))
            calibrated = 48.0 + 47.0 * (relative ** 0.82)
        else:
            calibrated = 56.0 + max(0.0, min(34.0, candidate.score * 0.42))
        candidate.score = round(max(45.0, min(96.0, calibrated)), 1)
    return candidates


def _quality_ceiling(duration: float) -> int:
    if duration <= 90:
        return 1
    if duration <= 4 * 60:
        return 3
    if duration <= 8 * 60:
        return 5
    if duration <= 15 * 60:
        return 7
    if duration <= 25 * 60:
        return 9
    return 10


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
    for window in windows:
        stats = window["stats"]
        resolution = float(window.get("resolution", 0.0))
        title, hook = _visual_title(stats, source_title)
        breakdown = {
            "intensidade": round(stats["activity"] * 22, 1),
            "pico": round(stats["peak"] * 26, 1),
            "movimento": round(stats["motion"] * 18, 1),
            "áudio": round(stats["audio"] * 10, 1),
            "transições": round(stats["scene_density"] * 9, 1),
            "fechamento": round((7.0 if window["end_natural"] else 1.5) + resolution * 5, 1),
        }
        reasons = []
        if stats["peak"] >= .70:
            reasons.append("pico forte de atividade")
        if stats["motion"] >= .55:
            reasons.append("movimento acima da média")
        if stats["audio"] >= .58:
            reasons.append("energia sonora elevada")
        if stats["scene_density"] >= .48:
            reasons.append("boa dinâmica de cenas")
        if window["end_natural"] and resolution >= .45:
            reasons.append("a ação desacelera antes do encerramento")
        elif window["end_natural"]:
            reasons.append("encerramento alinhado a uma transição natural")
        if not reasons:
            reasons.append("melhor combinação local de ritmo visual e áudio")
        result.append(Candidate(
            window["start"],
            window["end"],
            window["score"],
            title,
            hook,
            ", ".join(reasons).capitalize(),
            "",
            breakdown,
            "audiovisual",
            bool(window["end_natural"]),
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
    semantic = build_semantic_candidates(
        segments, av.duration, min_duration, max_duration
    ) if transcribe_enabled and segments else []

    pool: list[Candidate] = []
    for candidate in semantic:
        bonus, av_breakdown = _av_bonus(av, candidate.start, candidate.end)
        candidate.score = round(min(100.0, candidate.score * 0.82 + bonus), 1)
        candidate.score_breakdown = {**(candidate.score_breakdown or {}), **av_breakdown}
        candidate.analysis_mode = "híbrido"
        pool.append(candidate)

    pool.extend(visual)
    if not pool:
        return []

    _calibrate_scores(pool)
    pool.sort(key=lambda candidate: candidate.score, reverse=True)

    # Quantidade editorial: qualidade primeiro, duração apenas define um teto de segurança.
    top_score = pool[0].score
    quality_floor = max(64.0, top_score - 18.0)
    ceiling = min(MAX_CLIPS, _quality_ceiling(av.duration))

    selected: list[Candidate] = []
    for candidate in pool:
        if candidate.score < quality_floor and selected:
            continue
        overlap = any(
            max(candidate.start, existing.start) <
            min(candidate.end, existing.end) - min_duration * 0.35
            for existing in selected
        )
        if overlap:
            continue

        if len(selected) >= 2:
            previous_score = selected[-1].score
            if previous_score - candidate.score >= 9.0:
                break

        selected.append(candidate)
        if len(selected) >= ceiling:
            break

    if not selected:
        selected = pool[:1]

    # Mantém ordem cronológica na interface, mas os scores continuam refletindo o ranking.
    selected.sort(key=lambda candidate: candidate.start)
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
