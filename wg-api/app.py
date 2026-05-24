#!/usr/bin/env python3
"""
WireGuard Peer Management API
"""
import os, json, subprocess, re, time, shutil
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

WG_DATA = '/wg-data'
COMPOSE_DIR = '/compose'
API_KEY = os.environ.get('WG_API_KEY', 'changeme')
WG_CONTAINER = os.environ.get('WG_CONTAINER', 'wireguard')

def get_peers():
    peers = []
    names = load_names()
    for entry in sorted(os.listdir(WG_DATA)):
        path = os.path.join(WG_DATA, entry)
        if os.path.isdir(path) and re.match(r'^peer\d+$', entry):
            num = int(re.search(r'\d+', entry).group())
            conf_path = os.path.join(path, entry + '.conf')
            peers.append({
                'id': entry, 'num': num,
                'name': names.get(entry, entry),
                'has_conf': os.path.exists(conf_path)
            })
    peers.sort(key=lambda x: x['num'])
    return peers

def load_names():
    path = os.path.join(WG_DATA, '.peer_names.json')
    try:
        with open(path) as f: return json.load(f)
    except: return {}

def save_names(names):
    with open(os.path.join(WG_DATA, '.peer_names.json'), 'w') as f:
        json.dump(names, f, indent=2)

def get_peer_count():
    return sum(1 for e in os.listdir(WG_DATA)
               if os.path.isdir(os.path.join(WG_DATA, e)) and re.match(r'^peer\d+$', e))

def update_env_peers(new_count):
    env_path = os.path.join(COMPOSE_DIR, '.env')
    if not os.path.exists(env_path):
        return False, '.env not found at ' + env_path
    with open(env_path, 'r') as f: content = f.read()
    content = re.sub(r'^WG_PEERS=.*$', f'WG_PEERS={new_count}', content, flags=re.MULTILINE)
    with open(env_path, 'w') as f: f.write(content)
    return True, 'ok'

def read_env():
    env_vars = {}
    try:
        with open(os.path.join(COMPOSE_DIR, '.env')) as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    env_vars[k.strip()] = v.strip()
    except: pass
    return env_vars

def get_docker_network():
    """Detect the Docker network this container is on"""
    result = subprocess.run(
        ['docker', 'inspect', '--format',
         '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}',
         'wg-api'],
        capture_output=True, text=True, timeout=10
    )
    network = result.stdout.strip()
    if not network:
        # fallback: detect from compose dir name
        compose_dir = os.path.basename(COMPOSE_DIR.rstrip('/'))
        # COMPOSE_DIR is /compose which is mounted from the stack dir
        # try to find network from wireguard container if it exists
        r2 = subprocess.run(
            ['docker', 'inspect', '--format',
             '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}',
             WG_CONTAINER],
            capture_output=True, text=True, timeout=10
        )
        network = r2.stdout.strip() or 'softether-vpn_vpn-net'
    print(f'Using network: {network}', flush=True)
    return network

def recreate_wireguard(new_count):
    env = read_env()
    host_wg_data = env.get('HOST_WG_DATA', os.environ.get('HOST_WG_DATA', ''))

    if not host_wg_data:
        return False, 'HOST_WG_DATA not set in .env — cannot mount WireGuard config volume'

    print(f'host_wg_data: {host_wg_data}', flush=True)

    # Force stop and remove — ignore errors
    subprocess.run(['docker', 'stop', WG_CONTAINER], capture_output=True, timeout=30)
    subprocess.run(['docker', 'rm', '-f', WG_CONTAINER], capture_output=True, timeout=30)

    # Delete all wg_confs to force full peer regeneration
    wg_confs = os.path.join(WG_DATA, 'wg_confs')
    if os.path.exists(wg_confs):
        for f in os.listdir(wg_confs):
            fp = os.path.join(wg_confs, f)
            if os.path.isfile(fp):
                os.remove(fp)
                print(f'Deleted {fp}', flush=True)

    network = get_docker_network()

    result = subprocess.run([
        'docker', 'run', '-d',
        '--name', WG_CONTAINER,
        '--restart', 'unless-stopped',
        '--cap-add', 'NET_ADMIN',
        '--cap-add', 'SYS_MODULE',
        '--sysctl', 'net.ipv4.conf.all.src_valid_mark=1',
        '-e', 'PUID=1000', '-e', 'PGID=1000', '-e', 'TZ=UTC',
        '-e', f'SERVERURL={env.get("SERVER_IP", "")}',
        '-e', f'SERVERPORT={env.get("PORT_WIREGUARD", "51820")}',
        '-e', f'PEERS={new_count}',
        '-e', 'PEERDNS=auto',
        '-e', 'INTERNAL_SUBNET=10.13.13.0',
        '-e', 'ALLOWEDIPS=0.0.0.0/0',
        '-e', 'LOG_CONFS=true',
        '-v', f'{host_wg_data}:/config',
        '-v', '/lib/modules:/lib/modules:ro',
        '-p', f'{env.get("PORT_WIREGUARD", "51820")}:51820/udp',
        '--network', network,
        'lscr.io/linuxserver/wireguard:latest'
    ], capture_output=True, text=True, timeout=60)

    print(f'docker run result: {result.returncode}', flush=True)
    print(f'stdout: {result.stdout.strip()}', flush=True)
    print(f'stderr: {result.stderr.strip()}', flush=True)

    if result.returncode != 0:
        return False, f'docker run failed (code {result.returncode}): {result.stderr.strip()}'

    # Poll for new peer folder (up to 90 seconds)
    new_peer = f'peer{new_count}'
    new_peer_path = os.path.join(WG_DATA, new_peer)
    print(f'Waiting for {new_peer}...', flush=True)
    for i in range(90):
        time.sleep(1)
        if os.path.exists(new_peer_path) and os.path.exists(os.path.join(new_peer_path, f'{new_peer}.conf')):
            print(f'{new_peer} ready after {i+1}s', flush=True)
            break
    else:
        print(f'Timeout waiting for {new_peer}', flush=True)

    subprocess.run(['chmod', '-R', 'a+rX', WG_DATA], capture_output=True)
    return True, 'ok'

def delete_peer(peer_id):
    peer_path = os.path.join(WG_DATA, peer_id)
    if not os.path.exists(peer_path):
        return False, f'{peer_id} not found'

    names = load_names()
    shutil.rmtree(peer_path)
    print(f'Deleted {peer_path}', flush=True)

    remaining = sorted([
        e for e in os.listdir(WG_DATA)
        if os.path.isdir(os.path.join(WG_DATA, e)) and re.match(r'^peer\d+$', e)
    ], key=lambda x: int(re.search(r'\d+', x).group()))

    new_names = {}
    for i, old_id in enumerate(remaining):
        new_id = f'peer{i+1}'
        if old_id != new_id:
            old_path = os.path.join(WG_DATA, old_id)
            new_path = os.path.join(WG_DATA, new_id)
            os.rename(old_path, new_path)
            for f in os.listdir(new_path):
                if old_id in f:
                    os.rename(os.path.join(new_path, f),
                              os.path.join(new_path, f.replace(old_id, new_id)))
        if old_id in names:
            new_names[f'peer{i+1}'] = names[old_id]

    save_names(new_names)
    new_count = len(remaining)
    update_env_peers(new_count)
    return recreate_wireguard(new_count)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"{args[0]} {args[1]} {args[2]}", flush=True)

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
        if self.headers.get('X-API-Key', '') != API_KEY:
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
        elif parsed.path == '/wg-stats':
            if not self.check_auth(): return
            result = subprocess.run(
                ['docker', 'exec', WG_CONTAINER, 'wg', 'show', 'wg0', 'dump'],
                capture_output=True, text=True, timeout=10
            )
            peers = []
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                pubkey_map = {}
                for entry in sorted(os.listdir(WG_DATA)):
                    path = os.path.join(WG_DATA, entry)
                    if os.path.isdir(path) and re.match(r'^peer\d+$', entry):
                        pub_path = os.path.join(path, f'publickey-{entry}')
                        if os.path.exists(pub_path):
                            try:
                                with open(pub_path) as f:
                                    pubkey_map[f.read().strip()] = entry
                            except: pass
                names = load_names()
                for line in lines[1:]:
                    parts = line.split('\t')
                    if len(parts) >= 7:
                        try:
                            pubkey = parts[0]
                            handshake = int(parts[4]) if parts[4] not in ('0','') else None
                            peer_id = pubkey_map.get(pubkey, pubkey[:8]+'...')
                            peers.append({
                                'peer_id': peer_id,
                                'name': names.get(peer_id, peer_id),
                                'endpoint': parts[2] if parts[2] != '(none)' else None,
                                'allowed_ips': parts[3],
                                'latest_handshake': handshake,
                                'transfer_rx': int(parts[5]),
                                'transfer_tx': int(parts[6]),
                            })
                        except Exception as e:
                            print(f'Parse error: {e}', flush=True)
            self.send_json({'peers': peers})
        else:
            self.send_json({'error': 'Not found'}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if not self.check_auth(): return
        body = self.read_body()

        if parsed.path == '/peers/add':
            count = int(body.get('count', 1))
            current = get_peer_count()
            new_total = current + count
            ok, msg = update_env_peers(new_total)
            if not ok:
                self.send_json({'error': msg}, 500)
                return
            print(f'Adding {count} peers, new total: {new_total}', flush=True)
            ok, log = recreate_wireguard(new_total)
            if ok:
                self.send_json({'ok': True, 'total': new_total})
            else:
                self.send_json({'error': log}, 500)

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

        elif parsed.path == '/peers/delete':
            peer_id = body.get('id')
            if not peer_id:
                self.send_json({'error': 'Missing peer id'}, 400)
                return
            print(f'Deleting {peer_id}...', flush=True)
            ok, log = delete_peer(peer_id)
            self.send_json({'ok': ok, 'log': log})

        else:
            self.send_json({'error': 'Not found'}, 404)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8099))
    print(f'WireGuard API starting on port {port}', flush=True)
    print(f'HOST_WG_DATA: {os.environ.get("HOST_WG_DATA", "NOT SET")}', flush=True)
    print(f'WG_CONTAINER: {WG_CONTAINER}', flush=True)
    HTTPServer(('0.0.0.0', port), Handler).serve_forever()
