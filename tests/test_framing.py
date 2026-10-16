from pathlib import Path

from app.services import render


def test_auto_framing_uses_action_when_face_detection_is_inconsistent(monkeypatch):
    tracks = iter([
        {"subject": "face", "confidence": 0.80},
        {"subject": "none", "confidence": 0.10},
        {"subject": "person", "confidence": 0.75},
    ])
    monkeypatch.setattr(render, "detect_face_track", lambda *args, **kwargs: next(tracks))
    mode, info = render.resolve_project_framing(
        Path("video.mp4"),
        [(0, 30), (30, 60), (60, 90)],
        "auto",
        {"width": 1920, "height": 1080},
    )
    assert mode == "action"
    assert info["confident_faces"] == 1


def test_auto_framing_uses_face_when_faces_are_consistent(monkeypatch):
    tracks = iter([
        {"subject": "face", "confidence": 0.78},
        {"subject": "face", "confidence": 0.64},
        {"subject": "face", "confidence": 0.71},
    ])
    monkeypatch.setattr(render, "detect_face_track", lambda *args, **kwargs: next(tracks))
    mode, info = render.resolve_project_framing(
        Path("video.mp4"),
        [(0, 30), (30, 60), (60, 90)],
        "auto",
        {"width": 1920, "height": 1080},
    )
    assert mode == "face"
    assert info["required_faces"] == 3


def test_explicit_framing_is_preserved(monkeypatch):
    monkeypatch.setattr(
        render,
        "detect_face_track",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()),
    )
    mode, info = render.resolve_project_framing(
        Path("video.mp4"),
        [(0, 30)],
        "center",
        {"width": 1920, "height": 1080},
    )
    assert mode == "center"
    assert info["effective"] == "center"
