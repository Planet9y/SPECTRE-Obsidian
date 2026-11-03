from ghost.monitor import classify_address, fmt_addr
from ghost.diagnostics import port_exposure

def test_scope():
    assert classify_address('127.0.0.1') == 'Loopback'
    assert classify_address('192.168.1.1') == 'Private'
    assert classify_address('8.8.8.8') == 'Public'

def test_address():
    assert fmt_addr(()) == '—'

def test_exposure():
    assert port_exposure({'status':'LISTEN','local':'0.0.0.0:8080'})
    assert port_exposure({'status':'ESTABLISHED','local':'0.0.0.0:8080'}) is None


def test_gpu_decimal_temperature(monkeypatch):
    from ghost import monitor
    from types import SimpleNamespace
    monkeypatch.setattr(monitor.shutil, 'which', lambda _: '/mock/nvidia-smi')
    monkeypatch.setattr(monitor.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout='0, 1875, 8192, 41.22\n'))
    assert monitor.gpu_stats() == {'load': 0.0, 'used': 1875, 'total': 8192, 'temp': 41.2}
