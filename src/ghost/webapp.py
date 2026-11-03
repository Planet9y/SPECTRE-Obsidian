"""SPECTRE Obsidian local web desktop UI, powered by the existing read-only monitor."""
from __future__ import annotations
import csv
import io
import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from collections import Counter, deque
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from .monitor import Sampler
from .storage import History
from .diagnostics import resolve, ping, port_exposure

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
WEB = ROOT / 'web'

class Engine:
    def __init__(self):
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local' / 'share')) / 'SPECTRE'
        self.history = History(base / 'history.db')
        self.lock = threading.RLock()
        self.snapshot = None
        self.samples = deque(maxlen=90)
        self.error = ''
        self.running = True
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()

    def _sample(self):
        sampler = Sampler()
        while self.running:
            start = time.monotonic()
            try:
                snap = sampler.sample()
                with self.lock:
                    self.snapshot = snap
                    self.samples.append({'time':snap.timestamp[11:19], 'cpu':snap.cpu, 'ram':snap.memory,
                                         'gpu':snap.gpu['load'] if snap.gpu else 0,
                                         'up':round(snap.upload/1024, 2), 'down':round(snap.download/1024, 2)})
                    self.history.record(snap.timestamp, snap.connections)
                    self.error = snap.error
            except Exception as exc:
                with self.lock: self.error = str(exc)
            time.sleep(max(0.1, 2 - (time.monotonic()-start)))

    def payload(self):
        with self.lock:
            snap = self.snapshot
            if not snap: return {'ready':False, 'error':self.error}
            connections = snap.connections
            listeners = [c for c in connections if c['status'] == 'LISTEN']
            public = [c for c in connections if c['scope'] == 'Public' and c['status'] == 'ESTABLISHED']
            wildcard = [c for c in listeners if c['local'].startswith(('0.0.0.0:', '[::]:', ':::'))]
            remote_counts = Counter(c['name'] for c in connections if c['remote'] not in ('—','-'))
            advisories = []
            if snap.disk >= 90: advisories.append({'level':'high', 'title':'Storage capacity warning', 'detail':f'Primary disk {snap.disk:.0f}% utilized. Consider freeing space.'})
            else: advisories.append({'level':'good', 'title':'Storage capacity normal', 'detail':f'{snap.disk:.0f}% used on primary volume.'})
            if snap.memory >= 90: advisories.append({'level':'medium', 'title':'Memory pressure detected', 'detail':f'{snap.memory:.0f}% physical memory in use.'})
            else: advisories.append({'level':'good', 'title':'Memory pressure normal', 'detail':f'{snap.memory:.0f}% physical memory in use.'})
            advisories.append({'level':'medium' if wildcard else 'good', 'title':f'{len(wildcard)} wildcard listeners', 'detail':'Bound to all interfaces; firewall exposure is not established.' if wildcard else 'No all-interface TCP listeners observed.'})
            advisories.append({'level':'info', 'title':f'{len(public)} public connections', 'detail':'Established remote public endpoints. Not inherently suspicious.'})
            return {'ready':True, 'timestamp':snap.timestamp, 'cpu':snap.cpu,'ram':snap.memory,'disk':snap.disk,
                    'upload':snap.upload/1024,'download':snap.download/1024,'gpu':snap.gpu,
                    'connections':connections,'processes':snap.processes[:500], 'listeners':listeners,
                    'advisories':advisories,'samples':list(self.samples),'error':self.error,
                    'counts':{'sockets':len(connections),'established':sum(c['status']=='ESTABLISHED' for c in connections),
                              'public':len(public),'listeners':len(listeners),'processes':len(snap.processes)},
                    'top_remote':remote_counts.most_common(6)}

    def recent(self):
        with self.lock: return self.history.recent(25000)

    def close(self):
        self.running = False
        self._thread.join(timeout=6)
        with self.lock: self.history.close()


def create_handler(engine, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args): pass
        def _send(self, code, data, mime='application/json; charset=utf-8', extra=None):
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
            for k,v in (extra or {}).items():self.send_header(k,v)
            self.end_headers(); self.wfile.write(data)
        def _json(self, data, code=200):self._send(code,json.dumps(data,ensure_ascii=False,default=str).encode('utf-8'))
        def _auth(self):
            return parse_qs(urlparse(self.path).query).get('token',[None])[0] == token
        def do_GET(self):
            path=urlparse(self.path).path
            if path in ('/','/app.js','/style.css','/obsidian-violet.css','/obsidian-detail.css'):
                name={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/obsidian-violet.css':'obsidian-violet.css','/obsidian-detail.css':'obsidian-detail.css'}[path]
                mime='text/html; charset=utf-8' if path=='/' else ('text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8')
                try:self._send(200,(WEB/name).read_bytes(),mime)
                except OSError:self._json({'error':'UI assets missing'},500)
                return
            if not self._auth():return self._json({'error':'Unauthorized'},403)
            if path=='/api/snapshot':return self._json(engine.payload())
            if path=='/api/history':return self._json({'rows':engine.recent()})
            if path=='/api/export':
                kind=parse_qs(urlparse(self.path).query).get('kind',['connections'])[0]
                out=io.StringIO(); writer=csv.writer(out)
                if kind=='history':
                    writer.writerow(['Time','Event','Process','PID','Protocol','Local','Remote','Status']);writer.writerows(engine.recent())
                elif kind=='connections':
                    keys=['name','pid','protocol','local','remote','scope','status'];writer.writerow(keys)
                    with engine.lock:
                        if engine.snapshot:writer.writerows([[c.get(k,'') for k in keys] for c in engine.snapshot.connections])
                else:return self._json({'error':'Unknown export'},400)
                return self._send(200,('\ufeff'+out.getvalue()).encode('utf-8'),'text/csv; charset=utf-8',{'Content-Disposition':f'attachment; filename="spectre_{kind}.csv"'})
            self._json({'error':'Not found'},404)
        def do_POST(self):
            if not self._auth():return self._json({'error':'Unauthorized'},403)
            if urlparse(self.path).path!='/api/diagnostic':return self._json({'error':'Not found'},404)
            try:
                size=int(self.headers.get('Content-Length','0'))
                if size>2048: return self._json({'error':'Request too large'},413)
                data=json.loads(self.rfile.read(size))
                host=str(data.get('host','')).strip(); operation=data.get('operation')
                if not host or len(host)>253 or any(c.isspace() for c in host) or host.startswith('-'):
                    return self._json({'error':'Enter a valid hostname or IP address.'},400)
                if operation not in ('DNS','Ping'):return self._json({'error':'Unsupported diagnostic'},400)
                result='\n'.join(resolve(host)) if operation=='DNS' else ping(host)
                return self._json({'result':result or 'No result'})
            except Exception as exc:self._json({'error':str(exc)},500)
    return Handler


def main():
    engine=Engine(); token=secrets.token_urlsafe(24)
    server=ThreadingHTTPServer(('127.0.0.1',0),create_handler(engine,token))
    url=f'http://127.0.0.1:{server.server_port}/?token={token}'
    print('SPECTRE // OBSIDIAN — local dashboard:',url)
    webbrowser.open(url)
    try:server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:pass
    finally:server.server_close();engine.close()

if __name__=='__main__':main()
