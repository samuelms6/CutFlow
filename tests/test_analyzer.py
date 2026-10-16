from app.services.analyzer import Candidate, local_social_copy, select_best_candidates
from app.services.audiovisual import AVMap, AVPoint, auto_clip_budget


def fake_av(duration=240):
    points=[]
    for i in range(0, duration+1):
        active = 0.82 if 45 <= i <= 80 or 150 <= i <= 185 else 0.18
        points.append(AVPoint(float(i), scene=.7 if i in {45,80,150,185} else .1, motion=active, audio=active*.8, activity=active))
    return AVMap(duration,1.0,points,[45,80,150,185],[0,45,80,150,185,duration],True,{})


def test_auto_budget_scales_with_duration():
    assert auto_clip_budget(50)==1
    assert auto_clip_budget(170)==3
    assert auto_clip_budget(800)==10


def test_visual_selection_without_transcript_returns_content_moments():
    clips=select_best_candidates(fake_av(),[],20,55,"Messi Highlights",False)
    assert clips
    assert all(c.analysis_mode=='audiovisual' for c in clips)
    assert any(c.start <= 55 <= c.end for c in clips)
    assert all(c.end>c.start for c in clips)


def test_semantic_mode_uses_natural_sentence_endings():
    av=fake_av(120)
    segs=[
        {'start':10,'end':18,'text':'Existe um erro importante que muita gente comete.','words':[]},
        {'start':18,'end':30,'text':'A solução é organizar o código em partes menores.','words':[]},
        {'start':30,'end':39,'text':'Assim a manutenção fica muito mais simples.','words':[]},
    ]
    clips=select_best_candidates(av,segs,20,50,'Aula de programação',True)
    assert clips
    assert any(c.analysis_mode in {'híbrido','audiovisual'} for c in clips)


def test_social_copy_does_not_require_transcript():
    c=Candidate(0,35,80,'Messi — momento 1','Sequência de alta intensidade','Pico forte de atividade',analysis_mode='audiovisual')
    social=local_social_copy(c,'Lionel Messi King of Football')
    assert social['description']
    assert social['hashtags']
