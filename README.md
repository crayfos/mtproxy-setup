# mtproxy-setup

Telegram MTProto proxy based on [telemt](https://github.com/whn0thacked/telemt-docker), with nginx SNI routing, a Telegram monitoring bot, and TSPU/DPI bypass for Russian ISPs.

## What this does

- Runs telemt inside Docker, bound to `localhost:8443` only
- nginx sits in front on ports **443** and **3389**, routing by SNI:
  - `SNI = ozon.ru` or empty → telemt (proxy traffic)
  - anything else → real HTTPS website (anti-fingerprinting)
- Two proxy modes enabled simultaneously:
  - **EE-TLS** (port 443) — fake-TLS with `ozon.ru` SNI, works on most ISPs
  - **DD-Secure** (port 3389) — random-looking traffic, bypasses Megafon 4G and other deep TSPU inspection
- Monitoring bot checks telemt directly every 30s and auto-restarts on failure

## Why port 3389

Port 3389 is Windows RDP. Russian TSPU equipment does not deeply inspect it to avoid breaking corporate Remote Desktop access across the country. DD-Secure mode generates traffic with no TLS fingerprint, so it isn't identified as an MTProto proxy. This combination bypasses ISPs that block all TLS traffic to hosting IPs (e.g. Megafon 4G with Timeweb servers).

## Prerequisites

- VPS with Ubuntu 22.04 (any provider — tested on Timeweb)
- A domain with an A-record pointing to your server IP
- A real website to redirect non-proxy traffic to (anti-fingerprinting)
- Docker + Docker Compose installed
- nginx installed (system, not Docker)

## Setup

### 1. Install dependencies

```bash
apt update && apt install -y nginx certbot python3-certbot-nginx python3-pip ufw
pip install requests --break-system-packages
```

Install Docker:
```bash
curl -fsSL https://get.docker.com | sh
```

### 2. Generate your proxy secret

```bash
openssl rand -hex 16
# example output: c708446847093cf6c7d54c38731d9b4d
```

### 3. Register with @MTProxyBot

Open [@MTProxyBot](https://t.me/MTProxyBot) in Telegram:
1. `/newproxy` → enter your server IP and port `443`
2. Copy the **proxy tag** (looks like `5388623ffa38dc8c776f650b6ae37ba4`)
3. Optionally: `/setpromotion` to attach a channel

### 4. Configure telemt

Copy `telemt.toml` to `/root/proxy/telemt.toml` and fill in:

```toml
[access.users]
myproxy = "YOUR_32_CHAR_HEX_SECRET"   # from step 2

ad_tag = "YOUR_PROXY_TAG"              # from @MTProxyBot
```

You can also change `tls_domain` to a different Russian HTTPS site if you prefer.

### 5. Configure nginx

Copy `nginx.conf` to `/etc/nginx/nginx.conf` and replace:
- `YOUR_DOMAIN` → your domain (e.g. `proxy.example.com`)
- `YOUR_WEBSITE` → where non-proxy traffic should redirect (e.g. `example.com`)

Issue a Let's Encrypt certificate:
```bash
mkdir -p /var/www/certbot
certbot certonly --webroot -w /var/www/certbot -d YOUR_DOMAIN
```

Test and reload nginx:
```bash
nginx -t && systemctl reload nginx
```

### 6. Configure UFW

```bash
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 3389/tcp
ufw enable
```

> **Important:** Do not use `ufw limit` on port 443. Telegram opens 4–5 connections simultaneously on reconnect — rate limiting will block real users.

### 7. Start the proxy

```bash
cd /root/proxy
docker compose up -d
docker logs telemt --tail 20
```

You should see:
```
Modes: classic=false secure=true tls=true
TLS domain: ozon.ru
```

### 8. Set up the monitoring bot

Create a bot via [@BotFather](https://t.me/BotFather), get your token.
Get your Telegram user ID from [@userinfobot](https://t.me/userinfobot).

Copy `bot.py` to `/root/proxy/bot.py` and fill in:
```python
BOT_TOKEN = "YOUR_BOT_TOKEN"
ADMIN_ID  = 123456789
```

Start the bot:
```bash
pip install requests --break-system-packages
setsid python3 /root/proxy/bot.py >> /root/proxy/bot.log 2>&1 &
```

## Proxy links

After setup, your proxy links are:

**Universal (DD-Secure, port 3389) — works on Megafon 4G and most ISPs:**
```
tg://proxy?server=YOUR_DOMAIN&port=3389&secret=ddYOUR_SECRET
```

**Fallback (EE-TLS, port 443) — if port 3389 is ever blocked:**
```
tg://proxy?server=YOUR_DOMAIN&port=443&secret=eeYOUR_SECRETHEXozon.ru
```

To build the EE secret: `ee` + your 32-char secret + hex-encoded `ozon.ru`
Hex of `ozon.ru` = `6f7a6f6e2e7275`
So: `ee` + `YOUR_SECRET` + `6f7a6f6e2e7275`

## File structure

```
/root/proxy/
├── telemt.toml        # telemt config
├── docker-compose.yml # Docker setup
├── bot.py             # monitoring bot
└── bot.log            # bot logs

/etc/nginx/nginx.conf  # nginx SNI routing
```

## How the SNI routing works

```
Client connects to port 443 or 3389
        │
      nginx (ssl_preread — reads TLS ClientHello without decrypting)
        │
        ├── SNI = "ozon.ru"  ──────► telemt :8443 (EE-TLS proxy traffic)
        ├── SNI = ""          ──────► telemt :8443 (DD-Secure proxy traffic)
        └── SNI = anything else ───► nginx HTTPS :8444 → 301 redirect
```

telemt is never exposed directly — only reachable through nginx on localhost.

## Troubleshooting

**Proxy connects but Telegram doesn't load (mobile ISP)**
→ Use the DD-Secure link on port 3389. Your ISP likely uses TSPU that blocks TLS data after the handshake.

**Bot doesn't alert on failure**
→ Make sure bot is checking port 8443 (telemt), not 443 (nginx). nginx can be alive while telemt is broken.

**FD exhaustion crash (proxy dies overnight)**
→ Ensure `ulimits.nofile` is set to `65536` in `docker-compose.yml`. Default Docker limit of 1024 is too low for a proxy under sustained load.

**Proxy found quickly after IP change**
→ TSPU scanners probe Timeweb IP ranges actively and find open proxies within minutes. nginx SNI routing helps: scanners without the correct SNI get a real HTTPS site instead of a proxy fingerprint.
