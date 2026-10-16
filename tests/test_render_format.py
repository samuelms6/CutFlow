from pathlib import Path

from app.services import render


def test_action_render_is_full_bleed_9_16_without_blurred_overlay(monkeypatch, tmp_path):
    captured = {}

    monkeypatch.setattr(render, "require_binary", lambda _name: None)
    monkeypatch.setattr(
        render,
        "detect_action_track",
        lambda *args, **kwargs: {
            "subject": "action",
            "confidence": 0.8,
            "samples": [{"t": 0.0, "cx": 0.5, "cy": 0.5}],
        },
    )

    def fake_run(cmd, duration, progress_cb, timeout):
        captured["cmd"] = cmd

    monkeypatch.setattr(render, "_run_ffmpeg_progress", fake_run)

    result = render.render_clip(
        Path("source.mp4"),
        tmp_path / "clip.mp4",
        0,
        30,
        [],
        "none",
        "tiktok",
        "action",
        {"width": 1920, "height": 1080, "has_audio": False},
    )

    filter_complex = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    assert "crop=" in filter_complex
    assert "overlay=" not in filter_complex
    assert result["format"] == "1080x1920"
    assert result["aspect_ratio"] == "9:16"
    assert result["full_bleed"] is True
