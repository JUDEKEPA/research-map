#!/usr/bin/env python3
"""Rebuild deterministic fictional data and PNG figures (standard library only)."""
import csv
import json
import math
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parent / 'demo' / 'Orchard Study'

def chart(path, rows):
    width, height = 800, 440
    pixels = bytearray([248, 248, 246]) * (width * height)
    def dot(x, y, color, radius=1):
        for dy in range(-radius, radius+1):
            for dx in range(-radius, radius+1):
                a, b = x+dx, y+dy
                if 0 <= a < width and 0 <= b < height:
                    i = (b*width+a)*3; pixels[i:i+3] = bytes(color)
    def line(a, b, color):
        steps = max(abs(b[0]-a[0]), abs(b[1]-a[1]), 1)
        for i in range(steps+1):
            t=i/steps; dot(round(a[0]+(b[0]-a[0])*t), round(a[1]+(b[1]-a[1])*t), color)
    for y in range(60, 381, 64): line((60,y),(760,y),(220,220,216))
    line((60,40),(60,380),(85,85,85)); line((60,380),(760,380),(85,85,85))
    points=[(60+round(float(r['day'])/20*700),380-round(float(r['height_cm'])/32*320)) for r in rows]
    for a,b in zip(points,points[1:]):line(a,b,(193,130,74))
    for point in points:dot(*point,(193,130,74),radius=3)
    def chunk(kind, data):return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    raw=b''.join(b'\0'+pixels[y*width*3:(y+1)*width*3] for y in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))

def generate():
    ROOT.mkdir(parents=True,exist_ok=True)
    (ROOT/'README.md').write_text('# Orchard Study\n\nAll names, measurements and results are fictional. This project demonstrates folder navigation, text previews and figures.\n\nThe two growth-model variants are peers. Their comparison is stored beside them. Each package owns its code, small outputs, figures and metadata. Figures plot day (0–20, horizontal) against simulated height (0–32 cm, vertical).\n')
    for index,(name,rate) in enumerate([('baseline',0.12),('faster-growth',0.18)]):
        folder=ROOT/'analyses'/'growth-model'/name
        for sub in ('code','data','figures'): (folder/sub).mkdir(parents=True,exist_ok=True)
        rows=[{'day':day,'height_cm':round(30/(1+math.exp(-rate*(day-10))),3)} for day in range(21)]
        with (folder/'data'/'growth.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=['day','height_cm']);writer.writeheader();writer.writerows(rows)
        (folder/'code'/'model.py').write_text('"""Fictional logistic growth model; no external inputs."""\nimport math\n\ndef height(day, rate='+str(rate)+'):\n    return 30 / (1 + math.exp(-rate * (day - 10)))\n\nif __name__ == "__main__":\n    for day in range(21):\n        print(day, round(height(day), 3))\n')
        (folder/'analysis_report.json').write_text(json.dumps({'description':'Fictional '+name+' growth simulation.','method':'Logistic growth','parameters':{'rate':rate,'capacity_cm':30},'source_scripts':['code/model.py'],'source':'data/growth.csv'},indent=2)+'\n')
        (folder/'metadata.json').write_text(json.dumps({'schema_version':1,'node_id':'node-'+str(index+1)*32,'role':'analysis','description':'Fictional '+name+' simulation with code, data and a figure.','synthetic':True},indent=2)+'\n')
        chart(folder/'figures'/'growth.png',rows)
    compare=ROOT/'analyses'/'growth-model'/'comparison';compare.mkdir(exist_ok=True)
    (compare/'summary.md').write_text('# Variant comparison\n\nThe faster-growth variant has a steeper rise around day 10. Both variants have the same midpoint and limiting height. These are deterministic synthetic results, not biological evidence.\n')
    (compare/'analysis_report.json').write_text(json.dumps({'description':'Compare the two fictional growth variants.','inputs':['../baseline/data/growth.csv','../faster-growth/data/growth.csv']},indent=2)+'\n')
    (ROOT/'notes').mkdir(exist_ok=True)
    (ROOT/'notes'/'research-plan.md').write_text('# Research plan\n\n1. Inspect the baseline model.\n2. Compare the rate variant.\n3. Open the saved figures.\n4. Optionally start a node-bound Codex conversation using your own account.\n')
    return ROOT

if __name__=='__main__':print(generate().name+' demo generated')
