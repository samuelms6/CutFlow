from pathlib import Path
import subprocess

from app.services.media import probe
from app.services.audiovisual import analyze_audiovisual, build_visual_windows


def test_probe_and_audiovisual_map(tmp_path: Path):
    path=tmp_path/'sample.mp4'
    subprocess.run([
        'ffmpeg','-y',
        '-f','lavfi','-i','color=c=blue:s=640x360:d=3',
        '-f','lavfi','-i','color=c=red:s=640x360:d=3',
        '-f','lavfi','-i','sine=frequency=440:duration=6',
        '-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]',
        '-map','[v]','-map','2:a','-c:v','libx264','-c:a','aac','-shortest',str(path)
    ],check=True,capture_output=True)
    meta=probe(path)
    assert meta['duration']>5
    av=analyze_audiovisual(path,meta['duration'],meta['has_audio'])
    assert av.points
    assert av.natural_boundaries
