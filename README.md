# SoftEther-VPN-Web-Ui-with-wireguard
SoftEther VPN Web Ui With Wireguard Support

For IPs and port configs, it's all in the .env file, use `nano .env`

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
