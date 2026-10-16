from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path
from typing import Any, Callable
from ..config import OUTPUT_CRF, PRESETS
from .media import MediaError, require_binary
from .tracking import crop_expression, detect_action_track, detect_face_track


def _ass_time(seconds: float) -> str:
    h = int(seconds // 3600); m = int((seconds % 3600)//60); s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", " ")


def _word_events(segments: list[dict[str, Any]], clip_start: float, clip_end: float):
    words=[]
    for seg in segments:
        for w in seg.get("words") or []:
            ws, we = float(w.get("start",0)), float(w.get("end",0))
            if we <= clip_start or ws >= clip_end: continue
            words.append({"word": str(w.get("word","")).strip(), "start": max(ws,clip_start)-clip_start, "end": min(we,clip_end)-clip_start})
    return [w for w in words if w["word"] and w["end"]>w["start"]]


def write_clip_ass(segments: list[dict[str, Any]], clip_start: float, clip_end: float, path: Path, style: str, width: int, height: int, safe_bottom: int) -> bool:
    words = _word_events(segments, clip_start, clip_end)
    if not words:
        return False
    fontsize = max(42, int(height * 0.042)); margin_v = safe_bottom + 60
    header = f"""[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Default,Arial,{fontsize},&H00FFFFFF,&H0000FFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,4,0,2,70,70,{margin_v},1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"""
    events=[]
    # group 4-6 words; karaoke uses \k centiseconds on each word.
    chunk=[]
    for w in words:
        chunk.append(w)
        if len(chunk)>=5 or re.search(r"[.!?]$", w["word"]):
            st, en = chunk[0]["start"], chunk[-1]["end"]
            if style == "karaoke":
                text = " ".join(f"{{\\k{max(1,int((x['end']-x['start'])*100))}}}{_ass_escape(x['word'])}" for x in chunk)
            else:
                text = " ".join(_ass_escape(x["word"]) for x in chunk)
                if style == "viral": text = "{\\fscx105\\fscy105}" + text
            events.append(f"Dialogue: 0,{_ass_time(st)},{_ass_time(en)},Default,,0,0,0,,{text}")
            chunk=[]
    if chunk:
        st,en=chunk[0]["start"],chunk[-1]["end"]; text=" ".join(_ass_escape(x["word"]) for x in chunk)
        events.append(f"Dialogue: 0,{_ass_time(st)},{_ass_time(en)},Default,,0,0,0,,{text}")
    path.write_text(header + "\n".join(events), encoding="utf-8")
    return True


def _escape_filter_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _run_ffmpeg_progress(cmd: list[str], duration: float, progress_cb: Callable[[float], None] | None, timeout: int) -> None:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line=line.strip()
            if line.startswith("out_time_ms="):
                try:
                    secs=int(line.split("=",1)[1])/1_000_000
                    if progress_cb: progress_cb(min(0.995, secs/max(duration,0.1)))
                except Exception: pass
        rc=proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill(); raise MediaError("A renderização excedeu o tempo limite.")
    if rc != 0:
        err = proc.stderr.read() if proc.stderr else ""
        raise MediaError((err or "FFmpeg falhou na renderização")[-3500:])
    if progress_cb: progress_cb(1.0)



def resolve_project_framing(
    source: Path,
    windows: list[tuple[float, float]],
    requested: str,
    media_meta: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Resolve um único enquadramento automático para todos os cortes do projeto.

    Evita alternar visualmente entre crop com tracking e vídeo completo com fundo
    quando apenas um corte tem uma detecção ocasional de rosto.
    """
    requested = requested or "auto"
    if requested != "auto":
        return requested, {"requested": requested, "effective": requested, "sampled": 0, "confident_faces": 0}

    src_w = int((media_meta or {}).get("width") or 1920)
    src_h = int((media_meta or {}).get("height") or 1080)
    if not windows:
        return "center", {"requested": "auto", "effective": "center", "sampled": 0, "confident_faces": 0}
    if src_w <= src_h:
        return "center", {"requested": "auto", "effective": "center", "sampled": 0, "confident_faces": 0}

    sample_windows = windows[: min(6, len(windows))]
    tracks: list[dict[str, Any]] = []
    for start, end in sample_windows:
        tracks.append(detect_face_track(source, float(start), float(end), src_w, src_h))

    confident_faces = [
        t for t in tracks
        if t.get("subject") == "face" and float(t.get("confidence", 0) or 0) >= 0.45
    ]
    required = max(1, math.ceil(len(tracks) * 0.70))
    effective = "face" if len(confident_faces) >= required else "action"
    return effective, {
        "requested": "auto",
        "effective": effective,
        "sampled": len(tracks),
        "confident_faces": len(confident_faces),
        "required_faces": required,
        "average_confidence": round(
            sum(float(t.get("confidence", 0) or 0) for t in tracks) / max(len(tracks), 1), 3
        ),
    }

def render_clip(source: Path, output: Path, start: float, end: float, segments: list[dict[str, Any]], subtitle_style: str,
                preset: str="tiktok", framing: str="auto", media_meta: dict[str,Any]|None=None, progress_cb=None) -> dict[str,Any]:
    require_binary("ffmpeg")
    cfg=PRESETS.get(preset, PRESETS["tiktok"]); width,height=cfg["width"],cfg["height"]; duration=max(end-start,0.1)
    ass_path=output.with_suffix(".ass")
    has_subs = False if subtitle_style == "none" else write_clip_ass(segments,start,end,ass_path,subtitle_style,width,height,int(cfg["safe_bottom"]))
    src_w=int((media_meta or {}).get("width") or 1920); src_h=int((media_meta or {}).get("height") or 1080)
    track={"mode":"center","confidence":0,"samples":[],"subject":"none"}
    effective=framing
    if framing=="auto":
        effective="action"
    if effective=="face" and src_w>src_h:
        track=detect_face_track(source,start,end,src_w,src_h)
        cw,ch,xexpr,yexpr=crop_expression(track,src_w,src_h)
        vf=f"[0:v]crop={cw}:{ch}:x='{xexpr}':y='{yexpr}',scale={width}:{height}[base]"
    elif effective=="action" and src_w>src_h:
        track=detect_action_track(source,start,end,src_w,src_h)
        cw,ch,xexpr,yexpr=crop_expression(track,src_w,src_h)
        vf=f"[0:v]crop={cw}:{ch}:x='{xexpr}':y='{yexpr}',scale={width}:{height}[base]"
    elif effective in {"center","fill"}:
        vf=f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}[base]"
    elif effective=="fit":
        vf=(f"[0:v]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=18:9,scale={width}:{height}[bg];"
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[base]")
    else:
        vf=f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}[base]"
    if has_subs: vf += f";[base]ass='{_escape_filter_path(ass_path)}'[v]"
    else: vf += ";[base]null[v]"
    audio_filter="highpass=f=70,lowpass=f=15000,afftdn=nf=-28,loudnorm=I=-14:LRA=7:TP=-1.5"
    cmd=["ffmpeg","-y","-ss",f"{start:.3f}","-i",str(source),"-t",f"{duration:.3f}","-filter_complex",vf,"-map","[v]"]
    if (media_meta or {}).get("has_audio", True):
        cmd += ["-map","0:a?","-af",audio_filter,"-c:a","aac","-b:a",cfg["audio_bitrate"],"-ar","48000"]
    cmd += ["-c:v","libx264","-preset","veryfast","-crf",str(OUTPUT_CRF),"-maxrate",cfg["video_bitrate"],"-bufsize","12000k",
            "-movflags","+faststart","-pix_fmt","yuv420p","-progress","pipe:1","-nostats",str(output)]
    _run_ffmpeg_progress(cmd,duration,progress_cb,max(300,int(duration*25)))
    return {
        "framing": effective,
        "face_confidence": track.get("confidence",0) if track.get("subject")=="face" else 0,
        "tracking_confidence": track.get("confidence",0),
        "tracking_subject": track.get("subject","none"),
        "preset": preset,
        "subtitle_style": subtitle_style,
        "format": f"{width}x{height}",
        "aspect_ratio": "9:16",
        "full_bleed": effective != "fit",
    }
