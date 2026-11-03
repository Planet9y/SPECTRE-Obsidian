"""Network diagnostics, no remote scanning or modification."""
import ipaddress
import socket
import subprocess
import sys


def resolve(host):
    return sorted({x[4][0] for x in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)})


def ping(host):
    # Accept hostname or address, never arbitrary shell input.
    if not host or len(host) > 253 or not all(c.isalnum() or c in '.:-_' for c in host):
        raise ValueError('Enter a valid hostname or IP address')
    args = ['ping', '-n' if sys.platform == 'win32' else '-c', '3', host]
    return subprocess.run(args, capture_output=True, text=True, timeout=12, shell=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout[:5000]


def port_exposure(connection):
    if connection['status'] != 'LISTEN': return None
    local = connection['local']
    if local.startswith(('0.0.0.0:', '[::]:', ':::')):
        return 'Listening on all interfaces. Check firewall and whether this service needs network access.'
    return None
