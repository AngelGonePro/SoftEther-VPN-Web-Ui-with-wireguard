# WARNING: STILL IN BETA DEVELOPMENT | SoftEther-VPN-Web-Ui-with-wireguard
SoftEther VPN Web Ui With Wireguard Support and Custom port config

TESTED DEVICES ARE WINDOWS, ANDROID, AND UniFi OS VPN Client. Issues with others feel free to make a puul request with detialed logs!!!!

`Full_VPN_Config.zip` has all the files inside if you use `curl` on linux or download it.

---

## File Structure
```
~/softether-vpn/
├── .env                          ← copy env.example, fill in your values
├── docker-compose.yml
├── hairpin.sh
├── vpn_server.config             ← your existing SoftEther config
├── softether/
│   ├── Dockerfile
│   └── entrypoint-wrapper.sh
├── wg-api/
│   ├── Dockerfile
│   └── app.py
├── wg-data/                      ← create empty, wg-api fills it
└── ui/
    ├── index.html
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

# 4. Fix WireGuard permissions
chmod -R a+rX ~/softether-vpn/wg-data/

# 5.
mkdir -p wg-data
chmod +x hairpin.sh softether/entrypoint-wrapper.sh

# 6. Create empty SoftEther config
touch ~/softether-vpn/vpn_server.config

# 7. Start everything
cd ~/softether-vpn
docker compose up -d --build

# 8. Stop/Start Everything
Stop: docker compose stop
Start: docker compose up -d --build
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

PLEASE WAIT 20 SECONDS AFTER CONTAINER FULLY STARTS TO LOGIN

For IPs and port configs, it's all in the `.env` file, use `nano .env`

OLD INFO: AND CHANGE THE CONFIGS IN THE `index.html` with `nano ~/softether-vpn/` and do `ctrl+W` and search for `const CFG = {` WHICH INCLUDES COPYING the WireGuard API Key from the `.env` to the `wgApiKey` under `const CFG = {` in the `index.html`!

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
