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
    """Detect the Docker network this container is on — always prefer vpn-net"""
    result = subprocess.run(
        ['docker', 'inspect', '--format',
         '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}\n{{end}}',
         'wg-api'],
        capture_output=True, text=True, timeout=10
    )
    networks = [n.strip() for n in result.stdout.strip().splitlines() if n.strip()]
    # Prefer vpn-net over windscribe_net for wireguard container placement
    for n in networks:
        if 'vpn-net' in n:
            print(f'Using network: {n}', flush=True)
            return n
    network = networks[0] if networks else 'softether-vpn_vpn-net'
    print(f'Using network: {network}', flush=True)
    return network

def parse_public_ips(env):
    raw = env.get('PUBLIC_IPS', '').strip()
    if not raw:
        return []
    ips = []
    for entry in raw.split(','):
        ip = entry.strip().split('/')[0]
        if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ip):
            ips.append(ip)
        else:
            print(f'parse_public_ips: skipping "{entry.strip()}" — not a bare IPv4', flush=True)
    return ips


def patch_wg0_conf(public_ips, lan_ip):
    if not public_ips:
        print('patch_wg0_conf: no PUBLIC_IPS, skipping', flush=True)
        return
    if not lan_ip:
        print('patch_wg0_conf: LAN_IP not set, skipping', flush=True)
        return
    wg_conf_path = os.path.join(WG_DATA, 'wg_confs', 'wg0.conf')
    for _ in range(10):
        if os.path.exists(wg_conf_path):
            break
        time.sleep(2)
    else:
        print('patch_wg0_conf: wg0.conf not found after 20s, skipping', flush=True)
        return
    with open(wg_conf_path, 'r') as f:
        content = f.read()
    if 'hairpin' in content:
        print('patch_wg0_conf: already patched, skipping', flush=True)
        return
    up_rules, down_rules = [], []
    for ip in public_ips:
        cidr = f'{ip}/32'
        up_rules.append(f'iptables -t nat -A OUTPUT -d {cidr} -j DNAT --to-destination {lan_ip}')
        up_rules.append(f'iptables -t nat -A POSTROUTING -d {lan_ip} -j MASQUERADE')
        up_rules.append(f'iptables -t nat -A POSTROUTING -s {lan_ip} -j MASQUERADE')
        down_rules.append(f'iptables -t nat -D OUTPUT -d {cidr} -j DNAT --to-destination {lan_ip}')
        down_rules.append(f'iptables -t nat -D POSTROUTING -d {lan_ip} -j MASQUERADE')
        down_rules.append(f'iptables -t nat -D POSTROUTING -s {lan_ip} -j MASQUERADE')
    hairpin_postup   = 'PostUp = '   + '; '.join(up_rules)   + '  # hairpin'
    hairpin_postdown = 'PostDown = ' + '; '.join(down_rules) + '  # hairpin'
    if '\n[Peer]' in content:
        content = content.replace('\n[Peer]', f'\n{hairpin_postup}\n{hairpin_postdown}\n\n[Peer]', 1)
    else:
        content += f'\n{hairpin_postup}\n{hairpin_postdown}\n'
    with open(wg_conf_path, 'w') as f:
        f.write(content)
    print(f'patch_wg0_conf: patched {wg_conf_path}', flush=True)
    print(f'  LAN_IP     : {lan_ip}', flush=True)
    print(f'  PUBLIC_IPS : {", ".join(public_ips)} (written as /32)', flush=True)
    for cmd in [['wg-quick', 'down', 'wg0'], ['wg-quick', 'up', 'wg0']]:
        r = subprocess.run(['docker', 'exec', WG_CONTAINER] + cmd,
                          capture_output=True, text=True, timeout=15)
        print(f'{" ".join(cmd)}: rc={r.returncode} {r.stderr.strip()}', flush=True)


def recreate_wireguard(new_count):
    env = read_env()
    host_wg_data = env.get('HOST_WG_DATA', os.environ.get('HOST_WG_DATA', ''))

    if not host_wg_data:
        return False, 'HOST_WG_DATA not set in .env — cannot mount WireGuard config volume'

    print(f'host_wg_data: {host_wg_data}', flush=True)

    # Stop and remove the existing wireguard container before recreating.
    # Labels on the new container ensure docker compose down picks it up.
    subprocess.run(['docker', 'stop', WG_CONTAINER], capture_output=True, timeout=30)
    subprocess.run(['docker', 'rm', '-f', WG_CONTAINER], capture_output=True, timeout=30)

    # Save the server private key before wiping wg_confs so existing peer
    # configs remain valid after regeneration — without this every recreate
    # generates a new server keypair and all clients need new configs.
    saved_privkey = None
    wg_conf_path = os.path.join(WG_DATA, 'wg_confs', 'wg0.conf')
    if os.path.exists(wg_conf_path):
        with open(wg_conf_path) as f:
            for line in f:
                if line.strip().startswith('PrivateKey'):
                    saved_privkey = line.strip().split('=', 1)[1].strip()
                    break
        if saved_privkey:
            print(f'Saved server PrivateKey for restoration', flush=True)

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
        '--restart', 'no',
        '--cap-add', 'NET_ADMIN',
        '--cap-add', 'SYS_MODULE',
        '-e', 'PUID=1000', '-e', 'PGID=1000', '-e', 'TZ=UTC',
        '-e', f'SERVERURL={env.get("SERVER_IP", "")}',
        '-e', f'SERVERPORT={env.get("PORT_WIREGUARD", "51820")}',
        '-e', f'PEERS={new_count}',
        '-e', 'PEERDNS=auto',
        '-e', 'INTERNAL_SUBNET=10.13.13.0',
        '-e', f'ALLOWEDIPS={env.get("VPN_ROUTES", "0.0.0.0/0")}',
        '-e', 'LOG_CONFS=true',
        '-v', f'{host_wg_data}:/config',
        '-v', '/lib/modules:/lib/modules:ro',
        '--network', 'host',
        '--label', 'com.docker.compose.project=softether-vpn',
        '--label', 'com.docker.compose.service=wireguard',
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

    # Restore the saved server private key so existing peer configs stay valid.
    # The container generates a new keypair on first run — we overwrite it with
    # the original so clients never need to re-import their configs.
    if saved_privkey and os.path.exists(wg_conf_path):
        with open(wg_conf_path, 'r') as f:
            conf = f.read()
        # Replace the newly generated PrivateKey with the saved one
        conf = re.sub(r'^PrivateKey\s*=\s*.+$', f'PrivateKey = {saved_privkey}',
                      conf, flags=re.MULTILINE)
        with open(wg_conf_path, 'w') as f:
            f.write(conf)
        print(f'Restored server PrivateKey — existing peer configs remain valid', flush=True)
        # Restart the container so it uses the restored key
        subprocess.run(['docker', 'restart', WG_CONTAINER], capture_output=True, timeout=30)
        time.sleep(5)
    elif not saved_privkey:
        print('No saved PrivateKey (first run) — this is normal', flush=True)

    subprocess.run(['chmod', '-R', 'a+rX', WG_DATA], capture_output=True)

    env2 = read_env()
    public_ips = parse_public_ips(env2)
    lan_ip = env2.get('LAN_IP', '').strip()
    patch_wg0_conf(public_ips, lan_ip)

    setup_windscribe_routing(WG_CONTAINER)

    return True, 'ok'

def setup_windscribe_routing(container_name):
    """After wireguard container starts, route VPN client traffic through Windscribe."""
    import time as _time
    _time.sleep(5)

    # Get windscribe-gw's IP on vpn-net
    ws_ip = subprocess.run(
        ['docker', 'inspect', '--format',
         '{{(index .NetworkSettings.Networks "softether-vpn_vpn-net").IPAddress}}',
         'windscribe-gw'],
        capture_output=True, text=True, timeout=10
    ).stdout.strip()

    if not ws_ip:
        print('Could not get windscribe-gw IP on vpn-net — skipping routing setup', flush=True)
        return

    print(f'Windscribe-gw IP on vpn-net: {ws_ip}', flush=True)

    # Remove any stale ARP spoof entries
    subprocess.run(
        ['docker', 'exec', container_name, 'ip', 'neigh', 'del', '172.21.0.1', 'dev', 'eth0'],
        capture_output=True, timeout=10
    )

    # Add policy routing: traffic FROM VPN clients (10.13.13.0/24) goes through windscribe-gw
    subprocess.run(
        ['docker', 'exec', container_name,
         'ip', 'route', 'replace', 'default', 'via', ws_ip, 'dev', 'eth0', 'table', '200'],
        capture_output=True, text=True, timeout=10
    )
    r2 = subprocess.run(
        ['docker', 'exec', container_name,
         'ip', 'rule', 'add', 'from', '10.13.13.0/24', 'table', '200', 'priority', '50'],
        capture_output=True, text=True, timeout=10
    )
    print(f'Policy route: rc={r2.returncode} {r2.stderr.strip()}', flush=True)

    # MASQUERADE VPN client traffic going out eth0
    subprocess.run(
        ['docker', 'exec', container_name,
         'iptables', '-t', 'nat', '-C', 'POSTROUTING',
         '-s', '10.13.13.0/24', '-o', 'eth0', '-j', 'MASQUERADE'],
        capture_output=True, timeout=10
    ).returncode != 0 and subprocess.run(
        ['docker', 'exec', container_name,
         'iptables', '-t', 'nat', '-A', 'POSTROUTING',
         '-s', '10.13.13.0/24', '-o', 'eth0', '-j', 'MASQUERADE'],
        capture_output=True, timeout=10
    )

    print(f'Windscribe routing setup complete — client traffic via {ws_ip}', flush=True)


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
        elif parsed.path == '/config':
            env = read_env()
            raw_routes = env.get('VPN_ROUTES', '0.0.0.0/0').strip()
            vpn_routes = [r.strip() for r in raw_routes.split(',') if r.strip()]
            self.send_json({
                'wgApiKey':   env.get('WG_API_KEY',      API_KEY),
                'serverIP':   env.get('SERVER_IP',        ''),
                'wgPort':     int(env.get('PORT_WIREGUARD', 51820)),
                'vpnRoutes':  vpn_routes,
                'ports': {
                    'ovpnUdp':  int(env.get('PORT_OVPN_UDP',  9194)),
                    'ovpnTcp':  int(env.get('PORT_OVPN_TCP',  8443)),
                    'sslVpn':   int(env.get('PORT_SSL_ALT',   9992)),
                    'l2tp':     int(env.get('PORT_L2TP',      9701)),
                    'ikev2':    int(env.get('PORT_IKEV2',     9000)),
                    'ikev2Nat': int(env.get('PORT_IKEV2_NAT', 9500)),
                    'jsonRpc':  int(env.get('PORT_JSONRPC',   9555)),
                    'webUi':    int(env.get('PORT_WEBUI',     9765)),
                },
            })
        elif parsed.path == '/config/hairpin-status':
            if not self.check_auth(): return
            wg_conf_path = os.path.join(WG_DATA, 'wg_confs', 'wg0.conf')
            patched = False
            if os.path.exists(wg_conf_path):
                with open(wg_conf_path) as f:
                    patched = 'hairpin' in f.read()
            env = read_env()
            self.send_json({
                'patched': patched,
                'public_ips': parse_public_ips(env),
                'lan_ip': env.get('LAN_IP', ''),
                'wg_conf_exists': os.path.exists(wg_conf_path),
            })
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

        elif parsed.path == '/config/apply-hairpin':
            env = read_env()
            public_ips = parse_public_ips(env)
            lan_ip = env.get('LAN_IP', '').strip()
            if not public_ips:
                self.send_json({'error': 'PUBLIC_IPS not set in .env'}, 400)
                return
            if not lan_ip:
                self.send_json({'error': 'LAN_IP not set in .env'}, 400)
                return
            patch_wg0_conf(public_ips, lan_ip)
            wg_conf_path = os.path.join(WG_DATA, 'wg_confs', 'wg0.conf')
            patched = os.path.exists(wg_conf_path) and 'hairpin' in open(wg_conf_path).read()
            self.send_json({'ok': True, 'patched': patched,
                            'public_ips': public_ips, 'lan_ip': lan_ip})
        else:
            self.send_json({'error': 'Not found'}, 404)

if __name__ == '__main__':
    import signal

    def shutdown(signum, frame):
        # Stop wireguard when wg-api shuts down so docker compose down
        # can remove the network cleanly in one command.
        print('wg-api shutting down — stopping wireguard...', flush=True)
        subprocess.run(['docker', 'stop', WG_CONTAINER], capture_output=True, timeout=30)
        subprocess.run(['docker', 'rm', '-f', WG_CONTAINER], capture_output=True, timeout=30)
        print('wireguard stopped', flush=True)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    port = int(os.environ.get('PORT', 8099))
    # Start wireguard on boot if not already running
    _check = subprocess.run(['docker', 'inspect', '--format', '{{.State.Running}}', WG_CONTAINER],
                            capture_output=True, text=True)
    if _check.stdout.strip() != 'true':
        print('wireguard not running — starting it...', flush=True)
        _env = read_env()
        _host_wg_data = _env.get('HOST_WG_DATA', os.environ.get('HOST_WG_DATA', ''))
        _network = get_docker_network()
        _peers = _env.get('WG_PEERS', '5')
        subprocess.run([
            'docker', 'run', '-d',
            '--name', WG_CONTAINER,
            '--restart', 'no',
            '--cap-add', 'NET_ADMIN', '--cap-add', 'SYS_MODULE',
                '-e', 'PUID=1000', '-e', 'PGID=1000', '-e', 'TZ=UTC',
            '-e', f'SERVERURL={_env.get("SERVER_IP", "")}',
            '-e', f'SERVERPORT={_env.get("PORT_WIREGUARD", "51820")}',
            '-e', f'PEERS={_peers}',
            '-e', 'PEERDNS=auto', '-e', 'INTERNAL_SUBNET=10.13.13.0',
            '-e', f'ALLOWEDIPS={_env.get("VPN_ROUTES", "0.0.0.0/0")}',
            '-e', 'LOG_CONFS=true',
            '-v', f'{_host_wg_data}:/config',
            '-v', '/lib/modules:/lib/modules:ro',
            '--network', 'host',
            'lscr.io/linuxserver/wireguard:latest'
        ], capture_output=True, timeout=60)
        print('wireguard started', flush=True)
        setup_windscribe_routing(WG_CONTAINER)
    else:
        print('wireguard already running', flush=True)
    print(f'WireGuard API starting on port {port}', flush=True)
    print(f'HOST_WG_DATA: {os.environ.get("HOST_WG_DATA", "NOT SET")}', flush=True)
    print(f'WG_CONTAINER: {WG_CONTAINER}', flush=True)
    _startup_env = {}
    try:
        with open(os.path.join(COMPOSE_DIR, '.env')) as _f:
            for _l in _f:
                _l = _l.strip()
                if '=' in _l and not _l.startswith('#'):
                    _k, _v = _l.split('=', 1)
                    _startup_env[_k.strip()] = _v.strip()
    except Exception as _e:
        print(f'.env read error at startup: {_e}', flush=True)
    _ips = parse_public_ips(_startup_env)
    _lan = _startup_env.get('LAN_IP', 'NOT SET')
    print(f'PUBLIC_IPS : {", ".join(_ips) if _ips else "NOT SET"}', flush=True)
    print(f'LAN_IP     : {_lan}', flush=True)
    HTTPServer(('0.0.0.0', port), Handler).serve_forever()
