import os
import asyncio
import aiohttp
import time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from collections import deque
from datetime import datetime

app = FastAPI()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or "your_telegram_token_here"
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID") or "your_chat_id_here")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY") or "your_webshare_api_key_here"

telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

checking_active = False
proxy_pool = deque()
proxy_stats = {}  # proxy -> {success, fail, avg_response}

usernames_batch_current = []
usernames_checked_info = {}  # username -> {available_since, last_released, last_checked}


# --- Telegram messaging helper ---
async def send_telegram(text, reply_markup=None):
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    async with aiohttp.ClientSession() as session:
        async with session.post(f"{telegram_api_url}/sendMessage", json=payload) as resp:
            return await resp.json()


# --- Proxy fetching and validation ---
async def fetch_proxies():
    global proxy_pool, proxy_stats
    proxy_pool.clear()
    proxy_stats.clear()
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    url = "https://proxy.webshare.io/api/proxy/list/?limit=100"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                await send_telegram(f"❌ Failed to fetch proxies: HTTP {resp.status}")
                return False
            data = await resp.json()
            items = data.get("results", [])
            count = 0
            for item in items:
                ip = item.get("proxy_address")
                port = item.get("ports", {}).get("http") or item.get("port")
                if ip and port:
                    proxy = f"http://{ip}:{port}"
                    proxy_pool.append(proxy)
                    proxy_stats[proxy] = {"success": 0, "fail": 0, "avg_response": None}
                    count += 1
            await send_telegram(f"✅ Fetched {count} proxies from Webshare.")
            return True


async def validate_proxy(proxy: str, timeout=8):
    test_url = "https://www.tiktok.com"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(test_url, proxy=proxy, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}) as resp:
                return resp.status == 200
    except Exception:
        return False


async def refresh_and_validate_proxies():
    await fetch_proxies()
    valid_proxies = []
    for proxy in list(proxy_pool):
        valid = await validate_proxy(proxy)
        if valid:
            valid_proxies.append(proxy)
        else:
            try:
                proxy_pool.remove(proxy)
                proxy_stats.pop(proxy, None)
            except Exception:
                pass
    await send_telegram(f"🌐 Proxies Validated: {len(valid_proxies)}/{len(proxy_pool) + len(valid_proxies)}")


# --- Username batch generation ---
def generate_usernames_batch(size=50):
    now = int(time.time())
    return [f"user{now + i}" for i in range(size)]


# --- TikTok availability check ---
async def check_username_availability(username: str, proxy: str = None):
    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
                      " Chrome/114.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, proxy=proxy, headers=headers, timeout=10) as resp:
                if resp.status == 404:
                    return True
                elif resp.status == 200:
                    return False
                else:
                    return False
    except Exception:
        return False


# --- Main checker loop ---
async def checker_loop():
    global checking_active, usernames_batch_current
    await send_telegram("🟢 Checker started.")
    while checking_active:
        if not proxy_pool:
            await send_telegram("⚠️ Proxy pool empty, refreshing proxies...")
            await refresh_and_validate_proxies()
            if not proxy_pool:
                await asyncio.sleep(10)
                continue

        if not usernames_batch_current:
            usernames_batch_current = generate_usernames_batch(50)
            await send_telegram(f"🔄 Loaded new batch of {len(usernames_batch_current)} usernames")

        username = usernames_batch_current.pop(0)
        proxy = None
        try:
            proxy = proxy_pool[0]
            proxy_pool.rotate(-1)
        except IndexError:
            proxy = None

        available = await check_username_availability(username, proxy)
        now_ts = int(time.time())
        if available:
            info = usernames_checked_info.get(username)
            if not info:
                usernames_checked_info[username] = {
                    "available_since": now_ts,
                    "last_released": now_ts - 86400,
                    "last_checked": now_ts,
                }
            else:
                usernames_checked_info[username]["last_checked"] = now_ts

            available_since = usernames_checked_info[username]["available_since"]
            duration = now_ts - available_since
            last_released = usernames_checked_info[username]["last_released"]
            msg = f"✅ Username *{username}* is available!\nAvailable for: {duration}s\nLast released: {datetime.utcfromtimestamp(last_released).strftime('%Y-%m-%d %H:%M:%S UTC')}"
            keyboard = {
                "inline_keyboard": [
                    [{"text": "Claim", "callback_data": f"claim:{username}"}],
                    [{"text": "Skip", "callback_data": f"skip:{username}"}],
                ]
            }
            await send_telegram(msg, reply_markup=keyboard)

        else:
            if username in usernames_checked_info:
                usernames_checked_info.pop(username)

        await asyncio.sleep(1)
    await send_telegram("⏹️ Checker stopped.")


# --- Telegram webhook handler ---
@app.post("/webhook")
async def telegram_webhook(request: Request):
    global checking_active
    data = await request.json()

    if "callback_query" in data:
        callback = data["callback_query"]
        chat_id = callback["message"]["chat"]["id"]
        data_text = callback["data"]

        if chat_id != TELEGRAM_CHAT_ID:
            return JSONResponse({"status": "ignored"})

        if data_text.startswith("claim:"):
            username = data_text.split(":", 1)[1]
            await send_telegram(f"🎉 Claimed username: *{username}*")
            return JSONResponse({"status": "claimed"})

        if data_text.startswith("skip:"):
            username = data_text.split(":", 1)[1]
            await send_telegram(f"⏭️ Skipped username: *{username}*")
            return JSONResponse({"status": "skipped"})

        return JSONResponse({"status": "callback processed"})

    message = data.get("message") or data.get("edited_message") or {}
    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip().lower()

    if chat_id != TELEGRAM_CHAT_ID:
        return JSONResponse({"status": "ignored"})

    global checker_task

    if text == "/startchecker":
        if checking_active:
            await send_telegram("⚠️ Checker already running.")
        else:
            checking_active = True
            checker_task = asyncio.create_task(checker_loop())
            await send_telegram("🟢 Checker started by command.")
        return JSONResponse({"status": "checker started"})

    if text == "/stopchecker":
        if checking_active:
            checking_active = False
            await send_telegram("⏹️ Checker stopping...")
        else:
            await send_telegram("⚠️ Checker is not running.")
        return JSONResponse({"status": "checker stopped"})

    if text == "/refreshproxies":
        await refresh_and_validate_proxies()
        return JSONResponse({"status": "proxies refreshed"})

    return JSONResponse({"status": "command ignored"})


# --- Startup event ---
@app.on_event("startup")
async def startup_event():
    global checking_active
    checking_active = False
    await send_telegram("🚀 Bot deployed and ready.")


# For Railway or any ASGI server to run this
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("checker:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), log_level="info")
