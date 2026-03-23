#!/usr/bin/env python3
"""
Telegram bot for monitoring and auto-restarting the MTProto proxy.
Checks telemt directly on port 8443 (not just nginx on 443).

Commands: /status, /restart, /help
"""
import time, threading, subprocess, socket, requests

BOT_TOKEN = "YOUR_BOT_TOKEN"   # from @BotFather
ADMIN_ID  = 0                  # your Telegram user ID (get from @userinfobot)
API       = f"https://api.telegram.org/bot{BOT_TOKEN}"
CHECK_INTERVAL = 30    # seconds between health checks
FAIL_THRESHOLD = 3     # consecutive failures before alert + restart

_fail_count = 0
_alert_sent = False

def send(chat_id, text):
    try:
        requests.post(f"{API}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10)
    except Exception:
        pass

def tcp_ok(host, port):
    try:
        s = socket.create_connection((host, port), timeout=5)
        s.close()
        return True
    except Exception:
        return False

def container_status():
    try:
        r = subprocess.run(
            ["docker", "inspect", "--format",
             "{{.State.Status}} | started: {{.State.StartedAt}}", "telemt"],
            capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except Exception:
        return "unknown"

def do_restart():
    subprocess.run(
        ["docker", "compose", "-f", "/root/proxy/docker-compose.yml", "restart"],
        timeout=30, capture_output=True)

def icon(ok):
    return "\u2705" if ok else "\u274c"

def status_text():
    nginx_ok  = tcp_ok("127.0.0.1", 443)
    telemt_ok = tcp_ok("127.0.0.1", 8443)
    cstatus   = container_status()
    overall   = nginx_ok and telemt_ok
    return (
        f"{icon(overall)} *MTProxy*\n"
        f"nginx :443 \u2014 {icon(nginx_ok)}\n"
        f"telemt :8443 \u2014 {icon(telemt_ok)}\n"
        f"Container: `{cstatus}`"
    )

def health_loop():
    global _fail_count, _alert_sent
    while True:
        # Check telemt directly — nginx can be alive while telemt is broken
        ok = tcp_ok("127.0.0.1", 8443)
        if not ok:
            _fail_count += 1
            if _fail_count >= FAIL_THRESHOLD and not _alert_sent:
                send(ADMIN_ID, f"\U0001f6a8 *Proxy down* (telemt :8443) \u2014 {_fail_count} checks failed. Restarting...")
                do_restart()
                time.sleep(10)
                if tcp_ok("127.0.0.1", 8443):
                    send(ADMIN_ID, "\u2705 Auto-restarted successfully")
                    _fail_count = 0
                    _alert_sent = False
                else:
                    send(ADMIN_ID, "\u274c Auto-restart failed. Manual check needed.")
                    _alert_sent = True
        else:
            if _fail_count >= FAIL_THRESHOLD:
                send(ADMIN_ID, "\u2705 Proxy is back online")
            _fail_count = 0
            _alert_sent = False
        time.sleep(CHECK_INTERVAL)

def poll_loop():
    offset = None
    while True:
        try:
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset
            r = requests.get(f"{API}/getUpdates", params=params, timeout=35)
            for upd in r.json().get("result", []):
                offset = upd["update_id"] + 1
                msg     = upd.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                user_id = msg.get("from", {}).get("id")
                text    = msg.get("text", "")
                if user_id != ADMIN_ID:
                    continue
                if text.startswith("/status"):
                    send(chat_id, status_text())
                elif text.startswith("/restart"):
                    send(chat_id, "\U0001f504 Restarting proxy...")
                    do_restart()
                    time.sleep(8)
                    send(chat_id, status_text())
                elif text.startswith("/start") or text.startswith("/help"):
                    send(chat_id,
                        "\U0001f916 *MTProxy Bot*\n\n"
                        "/status \u2014 proxy health\n"
                        "/restart \u2014 restart proxy\n\n"
                        "Alerts fire automatically when telemt :8443 is unreachable.")
        except Exception:
            time.sleep(5)

if __name__ == "__main__":
    send(ADMIN_ID, "\U0001f916 MTProxy Bot started. /help for commands")
    threading.Thread(target=health_loop, daemon=True).start()
    poll_loop()
