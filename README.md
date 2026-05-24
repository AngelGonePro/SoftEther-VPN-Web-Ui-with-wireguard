# SoftEther-VPN-Web-Ui-with-wireguard
SoftEther VPN Web Ui With Wireguard Support

For IPs and port configs, it's all in the .env file, use `nano .env`
AND CHANGE THE CONFIGS IN THE `index.html` with `nano ~/softether-vpn/` and do `ctrl+W` and search for `const CFG = {` WHICH INCLUDES COPYING the WireGuard API Key from the `.env` to the `wgApiKey` under `const CFG = {` in the `index.html`!

Starting:
```
docker compose up -d --build
docker compose down
docker compose up -d
```

File paths:
```
~/softether-vpn/
├── .env                          ← your secrets and ports (copy from .env.example)
├── .env.example                  ← template, safe to share
├── docker-compose.yml            ← main compose file
├── vpn_server.config             ← SoftEther config (touch this if empty)
│
├── wg-data/                      ← auto-created by WireGuard container
│   ├── .peer_names.json          ← auto-created by wg-api when you rename peers
│   ├── peer1/
│   │   └── peer1.conf
│   ├── peer2/
│   │   └── peer2.conf
│   └── ...
│
├── ui/                           ← web UI files
│   ├── index.html
│   └── nginx.conf
│
└── wg-api/                       ← WireGuard management API
    ├── Dockerfile                ← exactly "Dockerfile", no extension
    └── app.py
```

When changing the .env
Use
```
cd ~/softether-vpn
docker compose down
rm vpn_server.config
touch vpn_server.config
docker compose up -d
```
But redownload configs after as it will make whole new ones.
