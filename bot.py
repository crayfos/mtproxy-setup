#!/usr/bin/env python3
import os, sys, time, threading, subprocess, socket, requests

# ── защита от двойного запуска ──────────────────────────────────────────────
PIDFILE = "/tmp/mtproxy_bot.pid"

def _check_pidfile():
    if os.path.exists(PIDFILE):
        try:
            old_pid = int(open(PIDFILE).read().strip())
            os.kill(old_pid, 0)          # проверяем что процесс жив
            print(f"[bot] already running as pid {old_pid}, exiting")
            sys.exit(0)
        except (ProcessLookupError, ValueError):
            pass                         # процесс мёртв — затираем файл
    open(PIDFILE, "w").write(str(os.getpid()))

_check_pidfile()
# ────────────────────────────────────────────────────────────────────────────

BOT_TOKEN      = "YOUR_BOT_TOKEN"
ADMIN_ID       = 0                  # your Telegram user ID (get from @userinfobot)
API            = f"https://api.telegram.org/bot{BOT_TOKEN}"
CHECK_INTERVAL = 30
FAIL_THRESHOLD    = 3
ME_ALERT_THRESHOLD = 3

_fail_count    = 0
_me_fail_count = 0
_alert_sent    = False
_me_alert_sent = False

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

def me_pool_ok():
    try:
        r = subprocess.run(
            ["docker", "logs", "telemt", "--since", "3m"],
            capture_output=True, text=True, timeout=10)
        return (r.stdout + r.stderr).count("ME pool is NOT ready") < 2
    except Exception:
        return True

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
    me_ok     = me_pool_ok()
    cstatus   = container_status()
    overall   = nginx_ok and telemt_ok and me_ok
    return (
        f"{icon(overall)} *DW Proxy*\n"
        f"nginx :443 \u2014 {icon(nginx_ok)}\n"
        f"telemt :8443 \u2014 {icon(telemt_ok)}\n"
        f"ME pool \u2014 {icon(me_ok)}\n"
        f"Container: `{cstatus}`"
    )

def health_loop():
    global _fail_count, _me_fail_count, _alert_sent, _me_alert_sent
    while True:
        tcp_alive = tcp_ok("127.0.0.1", 8443)
        if not tcp_alive:
            _fail_count += 1
            _me_fail_count = 0
            _me_alert_sent = False
            if _fail_count >= FAIL_THRESHOLD and not _alert_sent:
                send(ADMIN_ID,
                    f"\U0001f6a8 *DW Proxy: telemt недоступен* ({_fail_count} проверок)\nПерезапускаю...")
                do_restart()
                time.sleep(10)
                if tcp_ok("127.0.0.1", 8443):
                    send(ADMIN_ID, "\u2705 Авторестарт успешен")
                    _fail_count = 0
                    _alert_sent = False
                else:
                    send(ADMIN_ID, "\u274c Авторестарт не помог. Нужна ручная проверка.")
                    _alert_sent = True
        else:
            _fail_count = 0
            me_ok = me_pool_ok()
            if not me_ok:
                _me_fail_count += 1
                if _me_fail_count >= ME_ALERT_THRESHOLD and not _me_alert_sent:
                    send(ADMIN_ID,
                        f"\u26a0\ufe0f *DW Proxy: ME pool деградирован* ({_me_fail_count} проверок)\n"
                        f"TCP жив, новые подключения к Telegram блокируются.\n"
                        f"Жду восстановления само \u2014 если не пройдёт, используй /restart.")
                    _me_alert_sent = True
            else:
                if _me_alert_sent:
                    send(ADMIN_ID, "\u2705 DW Proxy: ME pool восстановлен")
                _me_fail_count = 0
                _me_alert_sent = False
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
                    send(chat_id, "\U0001f504 Перезапускаю прокси...")
                    do_restart()
                    time.sleep(8)
                    send(chat_id, status_text())
                elif text.startswith("/start") or text.startswith("/help"):
                    send(chat_id,
                        "\U0001f916 *DW Proxy Bot*\n\n"
                        "/status \u2014 nginx + telemt + ME pool\n"
                        "/restart \u2014 перезапустить прокси\n\n"
                        "Авторестарт: только при TCP-сбое (1.5 мин).\n"
                        "ME pool деградация \u2014 алерт без рестарта.")
        except Exception:
            time.sleep(5)

if __name__ == "__main__":
    send(ADMIN_ID, "\U0001f916 DW Proxy Bot запущен. /help")
    threading.Thread(target=health_loop, daemon=True).start()
    poll_loop()
