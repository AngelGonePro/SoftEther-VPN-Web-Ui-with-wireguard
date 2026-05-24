# WARNING: STILL IN BETA DEVELOPMENT | SoftEther-VPN-Web-Ui-with-wireguard
SoftEther VPN Web Ui With Wireguard Support

---

## File Structure
```
~/softether-vpn/
├── .env                          ← copy from .env.example, edit for each server
├── docker-compose.yml
├── vpn_server.config             ← touch this on first deploy, never delete after
├── softether/
│   ├── Dockerfile
│   └── entrypoint-wrapper.sh
├── wg-api/
│   ├── Dockerfile
│   └── app.py
├── wg-data/                      ← auto-created by WireGuard
└── ui/
    ├── index.html                ← edit CFG block for each server
    └── nginx.conf
```

---

## New Server?

```bash
# 1. Create folders
mkdir -p ~/softether-vpn/softether ~/softether-vpn/wg-api ~/softether-vpn/ui

# 2. Upload all files via scp from Windows:
# scp -r C:\path\to\softether-vpn\* root@NEW_IP:/root/softether-vpn/

# 3. Copy and edit .env
cp ~/softether-vpn/.env.example ~/softether-vpn/.env
nano ~/softether-vpn/.env
# Change: SERVER_IP, HOST_WG_DATA, all passwords, ports if needed

# 4. Edit CFG block in index.html
nano ~/softether-vpn/ui/index.html
# Ctrl+W → search "const CFG" → update serverIP, ports, wgPort

# 5. Set API key in index.html (use Python — avoids special char issues)
python3 -c "
with open('/root/softether-vpn/ui/index.html','r') as f: c=f.read()
c=c.replace(\"wgApiKey: 'ChangeMe_WgApiKey'\",\"wgApiKey: 'YOUR_WG_API_KEY'\")
with open('/root/softether-vpn/ui/index.html','w') as f: f.write(c)
"

# 6. Create empty SoftEther config
touch ~/softether-vpn/vpn_server.config

# 7. Start everything
cd ~/softether-vpn
docker compose up -d --build

# 8. Fix WireGuard permissions
sleep 30
chmod -R a+rX ~/softether-vpn/wg-data/
```

---

## What to Change Per Server

**`.env`** — these must change:
```
SERVER_IP=NEW_IP_OR_DOMAIN
HOST_WG_DATA=/root/softether-vpn/wg-data   # adjust if deployed elsewhere
SE_SERVER_PASSWORD=...
SE_HUB_PASSWORD=...
SE_USERS=username:password
SE_PSK=...
WG_API_KEY=...
# Change any ports that conflict with existing services
```

**`ui/index.html`** CFG block:
```js
const CFG = {
  serverIP: 'NEW_IP_OR_DOMAIN',  // ← change
  ports: {
    ovpnUdp:  9194,   // match .env PORT_OVPN_UDP
    ovpnTcp:  8443,   // match .env PORT_OVPN_TCP
    sslVpn:   9992,
    l2tp:     9701,
    ikev2:    9000,
    ikev2Nat: 9500,
    jsonRpc:  9555,
    webUi:    9765,
  },
  wgPort: 51820,      // match .env PORT_WIREGUARD
  hubName: 'DEFAULT',
  wgApiKey: 'YOUR_WG_API_KEY',  // match .env WG_API_KEY
};
```

---

## Important Rules
- **Never delete `vpn_server.config`** after first start — it saves all SoftEther settings
- **Never run `docker compose down` + `rm vpn_server.config`** unless you want to reset everything
- **To update files**: use `docker compose up -d --build` only — never `down` first
- **To update just UI**: `docker compose restart vpn-ui`
- **To update just wg-api**: `docker compose up -d --build wg-api`

---

## Important Rules
- **Never delete `vpn_server.config`** after first start — it saves all SoftEther settings
- **Never run `docker compose down` + `rm vpn_server.config`** unless you want to reset everything
- **To update files**: use `docker compose up -d --build` only — never `down` first
- **To update just UI**: `docker compose restart vpn-ui`
- **To update just wg-api**: `docker compose up -d --build wg-api`

---

PLEASE WAIT 20 SECONDS AFTER CONTAINER FULLY STARTS TO LOGIN

For IPs and port configs, it's all in the .env file, use `nano .env`
AND CHANGE THE CONFIGS IN THE `index.html` with `nano ~/softether-vpn/` and do `ctrl+W` and search for `const CFG = {` WHICH INCLUDES COPYING the WireGuard API Key from the `.env` to the `wgApiKey` under `const CFG = {` in the `index.html`!

Starting:
```
touch ~/softether-vpn/vpn_server.config
chmod -R a+rX ~/softether-vpn/wg-data/
docker compose up -d --build
```

File paths:
```
~/softether-vpn/
├── .env                          ← edit this for each server
├── docker-compose.yml
├── vpn_server.config             ← touch this on first run
├── softether/
│   ├── Dockerfile
│   └── entrypoint-wrapper.sh
├── wg-api/
│   ├── Dockerfile
│   └── app.py
├── wg-data/                      ← auto-created by WireGuard
└── ui/
    ├── index.html                ← edit CFG block for each server
    └── nginx.conf
```

After changing the `.env` if you wanted to change ports, etc.
Use
```
cd ~/softether-vpn
docker compose down
rm vpn_server.config
touch vpn_server.config
docker compose up -d --build
```
But redownload configs after as it will make whole new ones.
