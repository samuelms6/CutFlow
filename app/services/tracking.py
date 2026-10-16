from __future__ import annotations

from pathlib import Path
from typing import Any


def detect_face_track(source: Path, start: float, end: float, width: int, height: int, max_samples: int = 20) -> dict[str, Any]:
    """Amostra rosto/pessoa ao longo do corte.

    Rosto é preferido. Se não houver rosto confiável, usa detector HOG de pessoa.
    O retorno usa centros normalizados para o crop dinâmico do FFmpeg.
    """
    try:
        import cv2
    except Exception:
        return {"mode": "center", "confidence": 0.0, "samples": [], "subject": "none"}

    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        return {"mode": "center", "confidence": 0.0, "samples": [], "subject": "none"}

    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    hog = cv2.HOGDescriptor(); hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    duration = max(end - start, 0.1)
    count = min(max_samples, max(4, int(duration / 2.5)))
    samples: list[dict[str, Any]] = []
    face_hits = 0; person_hits = 0; last = None

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
            boxes = [(x/scale, y/scale, w/scale, h/scale) for x,y,w,h in faces]
            subject = max(boxes, key=lambda r: r[2] * r[3]) if last is None else min(boxes, key=lambda r: abs((r[0]+r[2]/2)-last[0]) + abs((r[1]+r[3]/2)-last[1]))
        else:
            # HOG é mais caro, então roda só quando não encontramos rosto no frame amostrado.
            rects, weights = hog.detectMultiScale(small, winStride=(8,8), padding=(8,8), scale=1.08)
            if len(rects):
                person_hits += 1
                boxes = [(x/scale, y/scale, w/scale, h/scale) for x,y,w,h in rects]
                subject = max(boxes, key=lambda r: r[2] * r[3]) if last is None else min(boxes, key=lambda r: abs((r[0]+r[2]/2)-last[0]) + abs((r[1]+r[3]/2)-last[1]))
        if subject is not None:
            x,y,w,h = [float(v) for v in subject]
            cx=x+w/2; cy=y+h/2; last=(cx,cy)
            samples.append({"t":round(t-start,2),"cx":round(cx/max(width,1),4),"cy":round(cy/max(height,1),4)})

    cap.release()
    confidence = min(1.0, len(samples) / max(count,1))
    dominant = "face" if face_hits >= person_hits and face_hits else ("person" if person_hits else "none")
    return {"mode":"subject" if confidence >= 0.25 else "center","confidence":round(confidence,2),"samples":samples,"subject":dominant,"face_hits":face_hits,"person_hits":person_hits}


def crop_expression(track: dict[str, Any], src_w: int, src_h: int) -> tuple[int, int, str, str]:
    crop_h = src_h; crop_w = int(round(src_h * 9 / 16))
    if crop_w > src_w:
        crop_w = src_w; crop_h = int(round(src_w * 16 / 9))
    max_x=max(src_w-crop_w,0); max_y=max(src_h-crop_h,0)
    samples=track.get("samples") or []
    if not samples:
        return crop_w,crop_h,str(max_x//2),str(max_y//2)
    x_expr=str(max_x//2); y_expr=str(max_y//2)
    for s in reversed(samples):
        cx=min(max(float(s["cx"])*src_w-crop_w/2,0),max_x); cy=min(max(float(s["cy"])*src_h-crop_h/2,0),max_y); t=float(s["t"])
        x_expr=f"if(gte(t,{t:.2f}),{cx:.2f},{x_expr})"; y_expr=f"if(gte(t,{t:.2f}),{cy:.2f},{y_expr})"
    return crop_w,crop_h,x_expr,y_expr
