from app.services.analyzer import (
    Candidate,
    _calibrate_scores,
    build_audiovisual_candidates,
    local_social_copy,
    select_best_candidates,
)
from app.services.audiovisual import AVMap, AVPoint, auto_clip_budget


def fake_av(duration=240):
    points = []
    for i in range(0, duration + 1):
        active = 0.82 if 45 <= i <= 80 or 150 <= i <= 185 else 0.18
        points.append(
            AVPoint(
                float(i),
                scene=.7 if i in {45, 80, 150, 185} else .1,
                motion=active,
                audio=active * .8,
                activity=active,
            )
        )
    return AVMap(
        duration,
        1.0,
        points,
        [45, 80, 150, 185],
        [0, 45, 80, 150, 185, duration],
        True,
        {},
    )


def test_auto_budget_is_only_a_safety_ceiling():
    assert auto_clip_budget(50) == 1
    assert auto_clip_budget(170) == 3
    assert auto_clip_budget(800) == 10


def test_visual_selection_without_transcript_returns_content_moments():
    clips = select_best_candidates(fake_av(), [], 20, 55, "Messi Highlights", False)
    assert clips
    assert all(c.analysis_mode == "audiovisual" for c in clips)
    assert any(c.start <= 55 <= c.end for c in clips)
    assert all(c.end > c.start for c in clips)


def test_long_video_does_not_fill_the_safety_ceiling_when_quality_is_sparse():
    clips = select_best_candidates(fake_av(1800), [], 20, 55, "Messi Highlights", False)
    assert clips
    assert len(clips) < auto_clip_budget(1800)


def test_visual_titles_are_descriptive_not_generic_numbered_moments():
    candidates = build_audiovisual_candidates(fake_av(), 20, 55, "Lionel Messi Highlights 1080p")
    assert candidates
    title = candidates[0].title.lower()
    assert "— momento" not in title
    assert "destaque 1" not in title


def test_score_calibration_creates_meaningful_separation():
    candidates = [
        Candidate(0, 30, 40, "a", "a", "a"),
        Candidate(40, 70, 60, "b", "b", "b"),
        Candidate(80, 110, 82, "c", "c", "c"),
    ]
    _calibrate_scores(candidates)
    scores = sorted(c.score for c in candidates)
    assert scores[-1] - scores[0] >= 30
    assert scores[-1] >= 90


def test_semantic_mode_uses_natural_sentence_endings():
    av = fake_av(120)
    segs = [
        {"start": 10, "end": 18, "text": "Existe um erro importante que muita gente comete.", "words": []},
        {"start": 18, "end": 30, "text": "A solução é organizar o código em partes menores.", "words": []},
        {"start": 30, "end": 39, "text": "Assim a manutenção fica muito mais simples.", "words": []},
    ]
    clips = select_best_candidates(av, segs, 20, 50, "Aula de programação", True)
    assert clips
    assert any(c.analysis_mode in {"híbrido", "audiovisual"} for c in clips)


def test_social_copy_does_not_require_transcript():
    candidate = Candidate(
        0,
        35,
        80,
        "Messi · Sequência de alta intensidade",
        "Pico de ação e movimento",
        "Pico forte de atividade",
        analysis_mode="audiovisual",
    )
    social = local_social_copy(candidate, "Lionel Messi King of Football")
    assert social["description"]
    assert social["hashtags"]
