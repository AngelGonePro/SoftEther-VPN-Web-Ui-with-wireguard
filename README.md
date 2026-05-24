# STILL IN BETA DEVELOPMENT, DO NOT USE | SoftEther-VPN-Web-Ui-with-wireguard
SoftEther VPN Web Ui With Wireguard Support

PLEASE WAIT 20 SECONDS AFTER CONTAINER FULLY STARTS TO LOGIN

For IPs and port configs, it's all in the .env file, use `nano .env`
AND CHANGE THE CONFIGS IN THE `index.html` with `nano ~/softether-vpn/` and do `ctrl+W` and search for `const CFG = {` WHICH INCLUDES COPYING the WireGuard API Key from the `.env` to the `wgApiKey` under `const CFG = {` in the `index.html`!

Starting:
```
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
