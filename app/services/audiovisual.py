from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .media import MediaError, require_binary


@dataclass
class AVPoint:
    t: float
    scene: float = 0.0
    motion: float = 0.0
    audio: float = 0.0
    activity: float = 0.0


@dataclass
class AVMap:
    duration: float
    sample_interval: float
    points: list[AVPoint]
    scene_changes: list[float]
    natural_boundaries: list[float]
    audio_present: bool
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration": self.duration,
            "sample_interval": self.sample_interval,
            "points": [asdict(p) for p in self.points],
            "scene_changes": self.scene_changes,
            "natural_boundaries": self.natural_boundaries,
            "audio_present": self.audio_present,
            "summary": self.summary,
        }


def _finite(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    return np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)


def _norm(values: np.ndarray) -> np.ndarray:
    values = _finite(values)
    if values.size == 0:
        return values
    lo = float(np.percentile(values, 10))
    hi = float(np.percentile(values, 95))
    if not math.isfinite(lo) or not math.isfinite(hi) or hi - lo < 1e-9:
        return np.zeros_like(values, dtype=float)
    return _finite(np.clip((values - lo) / (hi - lo), 0.0, 1.0))


def _smooth(values: np.ndarray, radius: int = 2) -> np.ndarray:
    if values.size == 0 or radius <= 0:
        return values
    k = radius * 2 + 1
    kernel = np.ones(k, dtype=float) / k
    return np.convolve(values, kernel, mode="same")


def _sample_video(source: Path, duration: float, interval: float, progress_cb=None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    try:
        import cv2
    except Exception as exc:
        raise MediaError("OpenCV não está disponível para a análise visual.") from exc

    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise MediaError("Não foi possível abrir o vídeo para análise visual.")

    times: list[float] = []
    scene_scores: list[float] = []
    motion_scores: list[float] = []
    prev_hist = None
    prev_gray = None
    total = max(1, int(math.ceil(duration / interval)))

    for idx in range(total + 1):
        t = min(duration, idx * interval)
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        scale = min(1.0, 480.0 / max(w, 1))
        if scale < 1:
            frame = cv2.resize(frame, (max(2, int(w * scale)), max(2, int(h * scale))))
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [24, 24], [0, 180, 0, 256])
        cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)

        scene = 0.0 if prev_hist is None else float(cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA))
        if not math.isfinite(scene):
            scene = 0.0
        motion = 0.0
        if prev_gray is not None:
            diff = cv2.absdiff(prev_gray, gray)
            motion = float(np.mean(diff) / 255.0)
            if not math.isfinite(motion):
                motion = 0.0
        times.append(float(t))
        scene_scores.append(scene)
        motion_scores.append(motion)
        prev_hist = hist
        prev_gray = gray
        if progress_cb and idx % max(1, total // 12) == 0:
            progress_cb(idx / max(total, 1), "Mapeando cenas e movimento")

    cap.release()
    return np.asarray(times, dtype=float), np.asarray(scene_scores, dtype=float), np.asarray(motion_scores, dtype=float)


def _sample_audio(source: Path, duration: float, interval: float, has_audio: bool) -> tuple[np.ndarray, np.ndarray]:
    if not has_audio:
        return np.arange(0, duration + interval, interval), np.zeros(max(1, int(math.ceil(duration / interval)) + 1), dtype=float)
    require_binary("ffmpeg")
    rate = 8000
    try:
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "pipe:1"],
            capture_output=True,
            check=True,
            timeout=max(180, int(duration * 1.5)),
        )
    except Exception:
        return np.arange(0, duration + interval, interval), np.zeros(max(1, int(math.ceil(duration / interval)) + 1), dtype=float)
    samples = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    window = max(1, int(rate * interval))
    rms: list[float] = []
    for i in range(0, len(samples), window):
        chunk = samples[i:i + window]
        if chunk.size:
            rms.append(float(np.sqrt(np.mean(chunk * chunk) + 1e-12)))
    times = np.arange(len(rms), dtype=float) * interval
    return times, np.asarray(rms, dtype=float)


def analyze_audiovisual(
    source: Path,
    duration: float,
    has_audio: bool,
    progress_cb: Callable[[float, str], None] | None = None,
) -> AVMap:
    # Sampling adapts to long videos to keep CPU bounded while preserving useful boundaries.
    interval = 0.75 if duration <= 12 * 60 else 1.0 if duration <= 35 * 60 else 1.5
    times, scenes, motions = _sample_video(source, duration, interval, progress_cb)
    if times.size == 0:
        raise MediaError("A análise visual não conseguiu ler quadros do vídeo.")
    atimes, audio = _sample_audio(source, duration, interval, has_audio)
    if audio.size:
        audio_interp = np.interp(times, atimes, _finite(audio), left=float(_finite(audio)[0]), right=float(_finite(audio)[-1]))
    else:
        audio_interp = np.zeros_like(times)
    scenes = _finite(scenes)
    motions = _finite(motions)
    audio_interp = _finite(audio_interp)

    scene_n = _norm(scenes)
    motion_n = _norm(motions)
    audio_n = _norm(audio_interp)
    activity = _finite(_smooth(scene_n * 0.38 + motion_n * 0.37 + audio_n * 0.25, radius=2))

    # Scene changes are strong visual discontinuities, ideal candidates for starts/ends.
    scene_threshold = max(0.32, float(np.percentile(scenes, 88))) if scenes.size >= 5 else 0.35
    scene_changes = [round(float(t), 2) for t, s in zip(times, scenes) if s >= scene_threshold]

    # Audio valleys often correspond to beat/phrase transitions or pauses. They are useful even in music-only videos.
    audio_s = _finite(_smooth(audio_n, radius=2))
    audio_valleys: list[float] = []
    for i in range(2, len(audio_s) - 2):
        if audio_s[i] <= audio_s[i - 1] and audio_s[i] <= audio_s[i + 1] and audio_s[i] <= 0.35:
            audio_valleys.append(float(times[i]))

    boundaries = [0.0, float(duration)] + scene_changes + [round(v, 2) for v in audio_valleys]
    boundaries = sorted({round(max(0.0, min(duration, b)), 2) for b in boundaries})
    # Collapse boundaries that are too close so snapping remains stable.
    collapsed: list[float] = []
    for b in boundaries:
        if not collapsed or b - collapsed[-1] >= 1.2:
            collapsed.append(b)
        elif b in scene_changes:
            collapsed[-1] = b

    points = [AVPoint(round(float(t), 2), round(float(s), 4), round(float(m), 4), round(float(a), 4), round(float(ac), 4))
              for t, s, m, a, ac in zip(times, scene_n, motion_n, audio_n, activity)]
    summary = {
        "mean_activity": round(float(np.mean(activity)), 3),
        "peak_activity": round(float(np.max(activity)), 3),
        "scene_changes": len(scene_changes),
        "audio_dynamic": round(float(np.std(audio_n)), 3),
        "motion_dynamic": round(float(np.std(motion_n)), 3),
    }
    return AVMap(round(duration, 2), interval, points, scene_changes, collapsed, bool(has_audio), summary)


def _nearest_boundary(boundaries: list[float], target: float, radius: float, prefer_before: bool | None = None) -> tuple[float, bool]:
    possible = [b for b in boundaries if abs(b - target) <= radius]
    if prefer_before is True:
        preferred = [b for b in possible if b <= target]
        if preferred:
            possible = preferred
    elif prefer_before is False:
        preferred = [b for b in possible if b >= target]
        if preferred:
            possible = preferred
    if not possible:
        return target, False
    value = min(possible, key=lambda b: abs(b - target))
    return value, True


def activity_stats(av: AVMap, start: float, end: float) -> dict[str, float]:
    pts = [p for p in av.points if start <= p.t <= end]
    if not pts:
        return {"activity": 0.0, "peak": 0.0, "motion": 0.0, "audio": 0.0, "scene_density": 0.0}
    scenes = sum(1 for t in av.scene_changes if start <= t <= end)
    duration = max(end - start, 1.0)
    return {
        "activity": float(np.mean([p.activity for p in pts])),
        "peak": float(max(p.activity for p in pts)),
        "motion": float(np.mean([p.motion for p in pts])),
        "audio": float(np.mean([p.audio for p in pts])),
        "scene_density": min(1.0, scenes / max(1.0, duration / 12.0)),
    }


def auto_clip_budget(duration: float) -> int:
    # Duration defines an upper budget; quality filters may return fewer clips.
    if duration <= 75:
        return 1
    if duration <= 3 * 60:
        return 3
    if duration <= 6 * 60:
        return 5
    if duration <= 10 * 60:
        return 7
    if duration <= 20 * 60:
        return 10
    return 12


def _mean_activity_near(av: AVMap, center: float, radius: float = 2.5) -> float:
    pts = [p.activity for p in av.points if center - radius <= p.t <= center + radius]
    return float(np.mean(pts)) if pts else 0.0


def _refine_visual_end(av: AVMap, start: float, peak_t: float, end: float, max_duration: int) -> tuple[float, bool, float]:
    """Evita encerrar enquanto a ação ainda está em alta.

    Procura a próxima transição natural depois do pico e prefere um ponto onde
    a atividade cai, o que funciona melhor para jogadas esportivas e montagens.
    """
    max_end = min(av.duration, start + max_duration)
    end = min(max_end, max(end, peak_t + 4.0))
    snapped = any(abs(b - end) <= 0.15 for b in av.natural_boundaries)
    tail_activity = _mean_activity_near(av, end - 1.5, 2.0)
    candidates = [b for b in av.natural_boundaries if end + 0.6 <= b <= max_end]

    if end < peak_t + 5.0 or tail_activity >= 0.48:
        for boundary in candidates[:4]:
            before = _mean_activity_near(av, boundary - 1.5, 1.7)
            after = _mean_activity_near(av, boundary + 1.5, 1.7)
            end = boundary
            snapped = True
            tail_activity = after
            if after <= 0.44 or after <= before * 0.82:
                break

    return round(float(end), 2), snapped, float(tail_activity)


def build_visual_windows(av: AVMap, min_duration: int, max_duration: int) -> list[dict[str, Any]]:
    if not av.points:
        return []

    activity = _finite(np.asarray([p.activity for p in av.points], dtype=float))
    times = _finite(np.asarray([p.t for p in av.points], dtype=float))
    radius_samples = max(2, int((min_duration * 0.50) / max(av.sample_interval, 0.1)))

    peaks: list[tuple[float, int]] = []
    for i in range(1, len(activity) - 1):
        if activity[i] >= activity[i - 1] and activity[i] >= activity[i + 1]:
            left = max(0, i - radius_samples)
            right = min(len(activity), i + radius_samples + 1)
            local = activity[left:right]
            prominence = activity[i] - float(np.percentile(local, 35))
            if activity[i] >= 0.38 and prominence >= 0.045:
                peaks.append((float(activity[i] + prominence * 0.45), i))

    candidate_cap = min(48, max(8, auto_clip_budget(av.duration) * 4))
    if not peaks:
        peaks = sorted([(float(v), i) for i, v in enumerate(activity)], reverse=True)[:candidate_cap * 2]
    peaks.sort(reverse=True)

    target = max(min_duration, min(max_duration, int((min_duration + max_duration) * 0.60)))
    windows: list[dict[str, Any]] = []

    for _, idx in peaks[: candidate_cap * 3]:
        peak_t = float(times[idx])
        raw_start = max(0.0, peak_t - target * 0.35)
        raw_end = min(av.duration, peak_t + target * 0.65)

        if raw_end - raw_start < min_duration:
            raw_start = max(0.0, raw_end - min_duration)

        start, start_snapped = _nearest_boundary(
            av.natural_boundaries, raw_start, 6.5, prefer_before=True
        )
        end_target = min(av.duration, max(start + min_duration, raw_end, peak_t + 4.0))
        end, end_snapped = _nearest_boundary(
            av.natural_boundaries, end_target, 9.0, prefer_before=False
        )

        if end - start < min_duration:
            end = min(av.duration, start + min_duration)
            end, extra = _nearest_boundary(
                av.natural_boundaries, end, 6.0, prefer_before=False
            )
            end_snapped = end_snapped or extra

        end, refined, tail_activity = _refine_visual_end(
            av, start, peak_t, end, max_duration
        )
        end_snapped = end_snapped or refined

        if end - start > max_duration:
            end = min(av.duration, start + max_duration)
            end, extra = _nearest_boundary(
                av.natural_boundaries, end, 4.5, prefer_before=True
            )
            end_snapped = end_snapped or extra

        if end - start < max(8.0, min_duration * 0.75):
            continue

        stats = activity_stats(av, start, end)
        resolution = max(0.0, min(1.0, 1.0 - tail_activity))
        score = (
            stats["activity"] * 22
            + stats["peak"] * 26
            + stats["motion"] * 18
            + stats["audio"] * 10
            + stats["scene_density"] * 9
            + (3.0 if start_snapped else 0.0)
            + (7.0 if end_snapped else 1.5)
            + resolution * 5
        )
        score = max(0.0, min(100.0, score))

        windows.append({
            "start": round(float(start), 2),
            "end": round(float(end), 2),
            "peak_t": round(peak_t, 2),
            "score": round(score, 1),
            "stats": stats,
            "start_natural": start_snapped,
            "end_natural": end_snapped,
            "tail_activity": round(tail_activity, 3),
            "resolution": round(resolution, 3),
        })

    windows.sort(key=lambda w: w["score"], reverse=True)
    selected: list[dict[str, Any]] = []
    for window in windows:
        if window["score"] < 34 and selected:
            continue
        duplicate = any(
            max(window["start"], other["start"]) < min(window["end"], other["end"])
            - min_duration * 0.55
            for other in selected
        )
        if duplicate:
            continue
        selected.append(window)
        if len(selected) >= candidate_cap:
            break

    if not selected and windows:
        selected = windows[:1]
    selected.sort(key=lambda w: w["start"])
    return selected
