from __future__ import annotations
import subprocess,tempfile,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services.render import render_clip

with tempfile.TemporaryDirectory() as td:
    td=Path(td); source=td/'sample.mp4'; output=td/'clip.mp4'
    subprocess.run(['ffmpeg','-y','-f','lavfi','-i','testsrc2=size=640x360:rate=24','-f','lavfi','-i','sine=frequency=880:sample_rate=44100','-t','2','-c:v','libx264','-preset','ultrafast','-c:a','aac',str(source)],check=True,capture_output=True)
    segments=[{'start':0,'end':2,'text':'Este é um teste profissional do CutFlow Studio.','words':[{'word':'Este','start':0,'end':.25},{'word':'é','start':.25,'end':.4},{'word':'um','start':.4,'end':.55},{'word':'teste','start':.55,'end':.8},{'word':'profissional','start':.8,'end':1.25},{'word':'do','start':1.25,'end':1.4},{'word':'CutFlow','start':1.4,'end':1.7},{'word':'Studio.','start':1.7,'end':1.95}]}]
    meta={'width':640,'height':360,'has_audio':True}
    info=render_clip(source,output,0,2,segments,'karaoke','tiktok','fit',meta)
    assert output.exists() and output.stat().st_size>10000
    print(f'SMOKE_OK {output.stat().st_size} bytes {info}')
