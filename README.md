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
├── .env
├── docker-compose.yml
├── vpn_server.config
├── softether/                ← NEW
│   ├── Dockerfile
│   └── entrypoint-wrapper.sh
├── wg-api/
│   ├── Dockerfile
│   └── app.py
├── wg-data/
└── ui/
    ├── index.html
    └── nginx.conf
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
