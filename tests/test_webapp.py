"""HTTP surface tests for the Obsidian frontend."""
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen
from ghost.webapp import create_handler

class FakeEngine:
    def payload(self):return {'ready':True,'cpu':23,'connections':[]}
    def recent(self):return []
    lock=threading.RLock()
    snapshot=None

def test_web_assets_and_token():
    server=ThreadingHTTPServer(('127.0.0.1',0),create_handler(FakeEngine(),'test-secret'))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        for path in ('/','/style.css','/app.js'):
            with urlopen(base+path) as response:
                assert response.status==200
                assert len(response.read())>100
        with urlopen(base+'/api/snapshot?token=test-secret') as response:
            assert json.load(response)['cpu']==23
        try:
            urlopen(base+'/api/snapshot')
            assert False,'Missing token must be rejected'
        except HTTPError as exc:assert exc.code==403
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
