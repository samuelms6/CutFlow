from __future__ import annotations

from pathlib import Path
from typing import Any


def _smooth_samples(samples: list[dict[str, Any]], alpha: float = 0.42) -> list[dict[str, Any]]:
    if not samples:
        return []
    out: list[dict[str, Any]] = []
    sx = float(samples[0]["cx"]); sy = float(samples[0]["cy"])
    for sample in samples:
        sx = sx * (1.0 - alpha) + float(sample["cx"]) * alpha
        sy = sy * (1.0 - alpha) + float(sample["cy"]) * alpha
        out.append({"t": float(sample["t"]), "cx": round(sx, 4), "cy": round(sy, 4)})
    return out


def detect_face_track(source: Path, start: float, end: float, width: int, height: int, max_samples: int = 20) -> dict[str, Any]:
    """Amostra rosto/pessoa ao longo do corte para crop vertical."""
    try:
        import cv2
    except Exception:
        return {"mode": "center", "confidence": 0.0, "samples": [], "subject": "none"}

    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        return {"mode": "center", "confidence": 0.0, "samples": [], "subject": "none"}

    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    duration = max(end - start, 0.1)
    count = min(max_samples, max(4, int(duration / 2.5)))
    samples: list[dict[str, Any]] = []
    face_hits = 0
    person_hits = 0
    last = None

    for i in range(count):
        t = start + duration * (i / max(count - 1, 1))
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        fh, fw = frame.shape[:2]
        scale = min(1.0, 640.0 / max(fw, 1))
        small = cv2.resize(frame, (int(fw * scale), int(fh * scale))) if scale < 1 else frame
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, 1.12, 5, minSize=(36, 36))
        subject = None
        if len(faces):
            face_hits += 1
            boxes = [(x / scale, y / scale, w / scale, h / scale) for x, y, w, h in faces]
            subject = max(boxes, key=lambda r: r[2] * r[3]) if last is None else min(
                boxes,
                key=lambda r: abs((r[0] + r[2] / 2) - last[0]) + abs((r[1] + r[3] / 2) - last[1]),
            )
        else:
            rects, _weights = hog.detectMultiScale(small, winStride=(8, 8), padding=(8, 8), scale=1.08)
            if len(rects):
                person_hits += 1
                boxes = [(x / scale, y / scale, w / scale, h / scale) for x, y, w, h in rects]
                subject = max(boxes, key=lambda r: r[2] * r[3]) if last is None else min(
                    boxes,
                    key=lambda r: abs((r[0] + r[2] / 2) - last[0]) + abs((r[1] + r[3] / 2) - last[1]),
                )
        if subject is not None:
            x, y, w, h = [float(v) for v in subject]
            cx = x + w / 2
            cy = y + h / 2
            last = (cx, cy)
            samples.append({
                "t": round(t - start, 2),
                "cx": round(cx / max(width, 1), 4),
                "cy": round(cy / max(height, 1), 4),
            })

    cap.release()
    confidence = min(1.0, len(samples) / max(count, 1))
    dominant = "face" if face_hits >= person_hits and face_hits else ("person" if person_hits else "none")
    return {
        "mode": "subject" if confidence >= 0.25 else "center",
        "confidence": round(confidence, 2),
        "samples": _smooth_samples(samples),
        "subject": dominant,
        "face_hits": face_hits,
        "person_hits": person_hits,
    }


def detect_action_track(source: Path, start: float, end: float, width: int, height: int, max_samples: int = 28) -> dict[str, Any]:
    """Rastreia a região de maior movimento para crop full-bleed.

    É o fallback do modo automático para esportes, gameplay e montagens onde
    rosto/pessoa não representa bem a ação principal.
    """
    try:
        import cv2
        import numpy as np
    except Exception:
        return {"mode": "center", "confidence": 0.0, "samples": [], "subject": "action"}

    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        return {"mode": "center", "confidence": 0.0, "samples": [], "subject": "action"}

    duration = max(end - start, 0.1)
    count = min(max_samples, max(8, int(duration / 1.5)))
    prev = None
    samples: list[dict[str, Any]] = []
    hits = 0

    for i in range(count):
        t = start + duration * (i / max(count - 1, 1))
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        fh, fw = frame.shape[:2]
        scale = min(1.0, 640.0 / max(fw, 1))
        small = cv2.resize(frame, (max(2, int(fw * scale)), max(2, int(fh * scale)))) if scale < 1 else frame
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (9, 9), 0)

        cx = small.shape[1] / 2
        cy = small.shape[0] / 2
        if prev is not None and prev.shape == gray.shape:
            diff = cv2.absdiff(prev, gray)
            _thr, mask = cv2.threshold(diff, 18, 255, cv2.THRESH_BINARY)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            mask = cv2.dilate(mask, None, iterations=2)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            min_area = max(40.0, mask.shape[0] * mask.shape[1] * 0.002)
            valid = [c for c in contours if cv2.contourArea(c) >= min_area]
            if valid:
                valid = sorted(valid, key=cv2.contourArea, reverse=True)[:5]
                total_area = sum(cv2.contourArea(c) for c in valid)
                if total_area > 0:
                    weighted_x = 0.0
                    weighted_y = 0.0
                    for contour in valid:
                        area = cv2.contourArea(contour)
                        m = cv2.moments(contour)
                        if m["m00"]:
                            weighted_x += (m["m10"] / m["m00"]) * area
                            weighted_y += (m["m01"] / m["m00"]) * area
                    cx = weighted_x / total_area
                    cy = weighted_y / total_area
                    hits += 1
        prev = gray
        samples.append({
            "t": round(t - start, 2),
            "cx": round((cx / max(small.shape[1], 1)), 4),
            "cy": round((cy / max(small.shape[0], 1)), 4),
        })

    cap.release()
    confidence = min(1.0, hits / max(count - 1, 1))
    return {
        "mode": "action" if confidence >= 0.18 else "center",
        "confidence": round(confidence, 2),
        "samples": _smooth_samples(samples, alpha=0.34),
        "subject": "action",
        "action_hits": hits,
    }


def crop_expression(track: dict[str, Any], src_w: int, src_h: int) -> tuple[int, int, str, str]:
    crop_h = src_h
    crop_w = int(round(src_h * 9 / 16))
    if crop_w > src_w:
        crop_w = src_w
        crop_h = int(round(src_w * 16 / 9))
    max_x = max(src_w - crop_w, 0)
    max_y = max(src_h - crop_h, 0)
    samples = track.get("samples") or []
    if not samples:
        return crop_w, crop_h, str(max_x // 2), str(max_y // 2)
    x_expr = str(max_x // 2)
    y_expr = str(max_y // 2)
    for sample in reversed(samples):
        cx = min(max(float(sample["cx"]) * src_w - crop_w / 2, 0), max_x)
        cy = min(max(float(sample["cy"]) * src_h - crop_h / 2, 0), max_y)
        t = float(sample["t"])
        x_expr = f"if(gte(t,{t:.2f}),{cx:.2f},{x_expr})"
        y_expr = f"if(gte(t,{t:.2f}),{cy:.2f},{y_expr})"
    return crop_w, crop_h, x_expr, y_expr
