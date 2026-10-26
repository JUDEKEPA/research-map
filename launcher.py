#!/usr/bin/env python3
"""Local project picker. Each project runs in its own isolated backend process."""
import argparse
import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from project_workspace import prepare_project,atomic_json
from project_doctor import report,verify_ai,codex_path

CODE=Path(__file__).resolve().parent
class Projects:
    def __init__(self,home):
        self.home=Path(home);self.home.mkdir(parents=True,exist_ok=True);self.jobs={};self.children={};self.lock=threading.Lock();self.url=''
    def recent(self):
        try:return json.loads((self.home/'recent.json').read_text())
        except (OSError,ValueError):return []
    def open(self,path):
        with self.lock:
            if any(j['state']=='running' for j in self.jobs.values()):raise ValueError('Wait for the current project to finish opening')
            key=uuid.uuid4().hex;self.jobs[key]={'state':'running','progress':0,'message':'Preparing project'}
        threading.Thread(target=self.work,args=(key,path),daemon=True).start();return key
    def work(self,key,path):
        job=self.jobs[key]
        def progress(amount,message):job.update(progress=amount,message=message)
        try:
            root=Path(path).expanduser().resolve()
            known=root/'.research-map/project.json'
            if known.exists():
                identity=json.loads(known.read_text()).get('project_id');child=self.children.get(identity)
                if child and child['process'].poll() is None:
                    if child['root']!=str(root):raise ValueError('Close this project before reopening its moved folder')
                    job.update(state='ready',progress=100,message='Project ready',url=child['url']);return
            state,manifest=prepare_project(root,CODE,progress)
            identity=manifest['project_id']
            child=self.children.get(identity)
            if child and child['process'].poll() is None and child['root']==str(root):
                job.update(state='ready',progress=100,message='Project ready',url=child['url']);return
            if child and child['process'].poll() is None:raise ValueError('Close this project before reopening its moved folder')
            progress(42,'Checking Codex and local setup')
            diagnostics=report(state)
            if diagnostics['local_ready'] and root != (CODE/'demo'/'Orchard Study').resolve():
                progress(48,'Checking a read-only Codex response')
                previous={}
                try:previous=json.loads((state/'setup-status.json').read_text())
                except (OSError,ValueError):pass
                check=next((c for c in previous.get('checks',[]) if c['name']=='AI response' and c['ok']),None)
                diagnostics['checks'].append(check or verify_ai(state,codex_path()))
            diagnostics['local_ready']=all(c['ok'] for c in diagnostics['checks']);atomic_json(state/'setup-status.json',diagnostics)
            progress(55,'Scanning folders and rebuilding graph')
            ready=self.home/('backend-'+identity+'.json');ready.unlink(missing_ok=True)
            log=(self.home/('backend-'+identity+'.log')).open('a')
            process=subprocess.Popen([sys.executable,str(CODE/'server.py'),'--project',str(root),'--port','0','--launcher-url',self.url,'--ready-file',str(ready)],stdout=log,stderr=log,start_new_session=True);log.close()
            self.children[identity]={'process':process,'root':str(root)}
            started=time.monotonic()
            while not ready.exists():
                if process.poll() is not None:raise ValueError('The project backend could not start. See '+str(self.home/('backend-'+identity+'.log')))
                if time.monotonic()-started>300:
                    process.send_signal(signal.SIGINT);raise ValueError('Project indexing took longer than five minutes; retry or inspect the backend log')
                time.sleep(.2)
            data=json.loads(ready.read_text());self.children[identity].update(url=data['url'])
            recent=[r for r in self.recent() if r['project_id']!=identity];recent.insert(0,dict(project_id=identity,name=root.name,path=str(root),opened=time.time()));atomic_json(self.home/'recent.json',recent[:12])
            progress(95,'Graph ready · live Codex validation available inside')
            job.update(state='ready',progress=100,message='Project ready',url=data['url'],diagnostics=diagnostics)
        except Exception as error:job.update(state='error',message=str(error))
    def close(self):
        for child in self.children.values():
            p=child['process']
            if p.poll() is None:
                p.send_signal(signal.SIGINT)
                try:p.wait(timeout=8)
                except subprocess.TimeoutExpired:p.terminate()

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,data,status=200,mime='application/json'):
        payload=(json.dumps(data).encode() if mime=='application/json' else data)
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(payload)));self.send_header('Cache-Control','no-store');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'");self.end_headers();self.wfile.write(payload)
    def valid(self):
        try:return urlparse('http://'+self.headers.get('Host','')).hostname in ('127.0.0.1','localhost') and urlparse('http://'+self.headers.get('Host','')).port==self.server.server_port
        except ValueError:return False
    def do_GET(self):
        if not self.valid():return self.reply({'error':'Local access only'},403)
        url=urlparse(self.path)
        if url.path=='/api/projects':return self.reply({'token':self.server.token,'recent':self.server.projects.recent(),'demo':str(CODE/'demo'/'Orchard Study')})
        if url.path=='/api/open-status':return self.reply(self.server.projects.jobs.get(parse_qs(url.query).get('id',[''])[0],{'state':'error','message':'Unknown request'}))
        files={'/':('welcome.html','text/html'),'/welcome.css':('welcome.css','text/css'),'/welcome.js':('welcome.js','application/javascript')}
        if url.path not in files:return self.reply({'error':'Not found'},404)
        name,mime=files[url.path];return self.reply((CODE/name).read_bytes(),mime=mime)
    def do_POST(self):
        if not self.valid():return self.reply({'error':'Local access only'},403)
        origin=self.headers.get('Origin');expected='http://'+self.headers.get('Host','')
        if self.headers.get('X-Workspace-Token')!=self.server.token or (origin and origin!=expected):return self.reply({'error':'Unauthorized request'},403)
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size<1 or size>10000:raise ValueError('Invalid request size')
            body=json.loads(self.rfile.read(size))
            if self.path!='/api/open-project':return self.reply({'error':'Not found'},404)
            return self.reply({'id':self.server.projects.open(body['path'])},202)
        except (ValueError,KeyError,TypeError) as e:self.reply({'error':str(e)},400)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8767);p.add_argument('--home',default=str(Path.home()/'Library/Application Support/Research Map Community'));p.add_argument('--ready-file');a=p.parse_args()
    projects=Projects(a.home);server=ThreadingHTTPServer(('127.0.0.1',a.port),Handler);server.projects=projects;server.token=secrets.token_urlsafe(32);projects.url='http://127.0.0.1:'+str(server.server_port)
    if a.ready_file:atomic_json(Path(a.ready_file),{'url':projects.url})
    print(projects.url,flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:projects.close();server.server_close()
