"""Read-only system sampling and network socket inventory."""
from __future__ import annotations
import datetime as dt
import ipaddress
import socket
import subprocess
import shutil
import os
from collections import Counter
from dataclasses import dataclass
import psutil


def fmt_addr(addr):
    if not addr:
        return "—"
    return f"{addr.ip}:{addr.port}" if hasattr(addr, 'ip') else str(addr)


def classify_address(address):
    try:
        ip = ipaddress.ip_address(address)
        if ip.is_loopback: return 'Loopback'
        if ip.is_private: return 'Private'
        if ip.is_link_local: return 'Link-local'
        if ip.is_multicast: return 'Multicast'
        if ip.is_global: return 'Public'
        return 'Special'
    except ValueError:
        return 'Unknown'


def gpu_stats():
    try:
        exe = shutil.which('nvidia-smi')
        if not exe and os.name == 'nt':
            for base in (os.environ.get('ProgramFiles', ''), os.environ.get('SystemRoot', '')):
                for candidate in (os.path.join(base, 'NVIDIA Corporation', 'NVSMI', 'nvidia-smi.exe'), os.path.join(base, 'System32', 'nvidia-smi.exe')):
                    if os.path.isfile(candidate): exe = candidate; break
                if exe: break
        if not exe: return None
        out = subprocess.run([exe, '--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu', '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=2, check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        vals = [x.strip() for x in out.stdout.splitlines()[0].split(',')]
        if len(vals) != 4:
            return None
        # NVIDIA can return decimal temperatures (e.g. 41.22), not just integers.
        load, used, total, temp = map(float, vals)
        return {'load': load, 'used': int(used), 'total': int(total), 'temp': round(temp, 1)}
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


@dataclass
class Snapshot:
    timestamp: str
    cpu: float
    memory: float
    disk: float
    upload: float
    download: float
    gpu: dict | None
    connections: list[dict]
    processes: list[dict]
    error: str = ''


class Sampler:
    def __init__(self):
        self.last = psutil.net_io_counters()
        self.last_time = dt.datetime.now().timestamp()
        psutil.cpu_percent(interval=None)

    def sample(self):
        now = dt.datetime.now()
        net = psutil.net_io_counters()
        delta = max(now.timestamp() - self.last_time, .001)
        up = max(0, (net.bytes_sent - self.last.bytes_sent) / delta)
        down = max(0, (net.bytes_recv - self.last.bytes_recv) / delta)
        self.last, self.last_time = net, now.timestamp()
        names = {}
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'memory_info', 'status']):
            try:
                info = p.info
                names[info['pid']] = info['name'] or 'Unknown'
                procs.append({'pid': info['pid'], 'name': names[info['pid']], 'ram': round((info['memory_info'].rss if info['memory_info'] else 0)/1048576, 1), 'status': info['status'] or ''})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        procs.sort(key=lambda p: p['ram'], reverse=True)
        connections, err = [], ''
        try:
            for c in psutil.net_connections(kind='inet'):
                protocol = 'TCP' if c.type == socket.SOCK_STREAM else 'UDP'
                remote_ip = c.raddr.ip if c.raddr else ''
                connections.append({'pid': c.pid, 'name': names.get(c.pid, 'Unattributed (closed socket)' if c.pid is None else 'Unknown process'), 'protocol': protocol, 'local': fmt_addr(c.laddr), 'remote': fmt_addr(c.raddr), 'remote_ip': remote_ip, 'scope': classify_address(remote_ip) if remote_ip else '—', 'status': c.status or '—'})
        except (psutil.AccessDenied, OSError) as exc:
            err = f'Connection access limited: {exc}. Try running as administrator.'
        connections.sort(key=lambda c: (c['name'].lower(), c['remote']))
        return Snapshot(now.isoformat(timespec='seconds'), psutil.cpu_percent(interval=None), psutil.virtual_memory().percent, psutil.disk_usage('C:\\' if __import__('os').name == 'nt' else '/').percent, up, down, gpu_stats(), connections, procs, err)
