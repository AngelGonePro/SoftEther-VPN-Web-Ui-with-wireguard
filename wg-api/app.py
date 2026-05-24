#!/usr/bin/env python3
"""
WireGuard Peer Management API
Runs as a sidecar container with access to Docker socket and wg-data volume
"""
import os, json, shutil, subprocess, re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

WG_DATA = '/wg-data'
COMPOSE_DIR = '/compose'
API_KEY = os.environ.get('WG_API_KEY', 'changeme')

def get_peers():
    """Get all peers with their names from the wg-data directory"""
    peers = []
    names = load_names()
    for entry in sorted(os.listdir(WG_DATA)):
        path = os.path.join(WG_DATA, entry)
        if os.path.isdir(path) and re.match(r'^peer\d+$', entry):
            num = int(re.search(r'\d+', entry).group())
            conf_path = os.path.join(path, entry + '.conf')
            has_conf = os.path.exists(conf_path)
            peers.append({
                'id': entry,
                'num': num,
                'name': names.get(entry, entry),
                'has_conf': has_conf
            })
    peers.sort(key=lambda x: x['num'])
    return peers

def load_names():
    path = os.path.join(WG_DATA, '.peer_names.json')
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}

def save_names(names):
    path = os.path.join(WG_DATA, '.peer_names.json')
    with open(path, 'w') as f:
        json.dump(names, f, indent=2)

def get_peer_count():
    count = 0
    for entry in os.listdir(WG_DATA):
        if os.path.isdir(os.path.join(WG_DATA, entry)) and re.match(r'^peer\d+$', entry):
            count += 1
    return count

def update_env_peers(new_count):
    """Update PEERS= in .env file"""
    env_path = os.path.join(COMPOSE_DIR, '.env')
    if not os.path.exists(env_path):
        return False
    with open(env_path, 'r') as f:
        content = f.read()
    content = re.sub(r'^WG_PEERS=.*$', f'WG_PEERS={new_count}', content, flags=re.MULTILINE)
    with open(env_path, 'w') as f:
        f.write(content)
    return True

def restart_wireguard():
    """Restart the WireGuard container via docker compose"""
    result = subprocess.run(
        ['docker', 'compose', 'restart', 'wireguard'],
        cwd=COMPOSE_DIR,
        capture_output=True, text=True, timeout=60
    )
    return result.returncode == 0, result.stdout + result.stderr

def fix_permissions():
    """Make peer configs readable by nginx"""
    subprocess.run(['chmod', '-R', 'a+rX', WG_DATA], capture_output=True)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default logging

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-API-Key')
        self.end_headers()
        self.wfile.write(body)

    def check_auth(self):
        key = self.headers.get('X-API-Key', '')
        if key != API_KEY:
            self.send_json({'error': 'Unauthorized'}, 401)
            return False
        return True

    def read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-API-Key')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/peers':
            if not self.check_auth(): return
            self.send_json({'peers': get_peers(), 'total': get_peer_count()})
        elif parsed.path == '/health':
            self.send_json({'status': 'ok'})
        else:
            self.send_json({'error': 'Not found'}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if not self.check_auth(): return
        body = self.read_body()

        if parsed.path == '/peers/add':
            # Add N more peers
            count = body.get('count', 1)
            current = get_peer_count()
            new_total = current + count
            if not update_env_peers(new_total):
                self.send_json({'error': '.env file not found'}, 500)
                return
            ok, log = restart_wireguard()
            if ok:
                # Wait for files then fix permissions
                import time; time.sleep(5)
                fix_permissions()
                self.send_json({'ok': True, 'total': new_total, 'log': log})
            else:
                self.send_json({'error': 'Restart failed', 'log': log}, 500)

        elif parsed.path == '/peers/rename':
            peer_id = body.get('id')
            name = body.get('name', '').strip()
            if not peer_id or not name:
                self.send_json({'error': 'Missing id or name'}, 400)
                return
            names = load_names()
            names[peer_id] = name
            save_names(names)
            self.send_json({'ok': True})

        elif parsed.path == '/peers/restart':
            ok, log = restart_wireguard()
            import time; time.sleep(5)
            fix_permissions()
            self.send_json({'ok': ok, 'log': log})

        else:
            self.send_json({'error': 'Not found'}, 404)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8099))
    print(f'WireGuard API starting on port {port}')
    HTTPServer(('0.0.0.0', port), Handler).serve_forever()
