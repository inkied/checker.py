import os
import asyncio
import aiohttp
import time
import random
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from collections import deque
from datetime import datetime
import uvicorn

app = FastAPI()

# Environment config
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or "your_telegram_token_here"
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or "your_chat_id_here"
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY") or "your_webshare_api_key_here"
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Globals
checking_active = False
proxy_pool = deque()
usernames_batch_current = []
usernames_checked_info = {}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)...",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)...",
    "Mozilla/5.0 (Linux; Android 10; SM-G975F)..."
]

def random_user_agent():
    return random.choice(USER_AGENTS)

def generate_usernames_batch(size=50):
    now = int(time.time())
    return [f"u{now + i:x}"[-4:] for i in range(size)]

async def send_telegram(text: str):
    async with aiohttp.ClientSession() as session:
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
        await session.post(f"{TELEGRAM_API}/sendMessage", json=payload)

async def fetch_proxies():
    proxy_pool.clear()
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    url = "https://proxy.webshare.io/api/proxy/list/?mode=direct&limit=100"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                await send_telegram(f"❌ Failed to fetch proxies: HTTP {resp.status}")
                return
            data = await resp.json()
            for item in data.get("results", []):
                ip = item.get("proxy_address")
                port = item.get("port") or item.get("ports", {}).get("http")
                if ip and port:
                    proxy_pool.append(f"http://{ip}:{port}")
    await send_telegram(f"✅ {len(proxy_pool)} proxies loaded.")

async def check_username(username: str, proxy: str = None):
    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": random_user_agent(),
        "Accept-Language": "en-US,en;q=0.9"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, proxy=proxy, timeout=10) as resp:
                if resp.status == 404:
                    now = int(time.time())
                    usernames_checked_info[username] = {
                        "available_since": now,
                        "last_checked": now
                    }
                    return True
    except:
        pass
    usernames_checked_info.pop(username, None)
    return False

async def checker_loop():
    global checking_active
    while checking_active:
        if not usernames_batch_current:
            usernames_batch_current.extend(generate_usernames_batch())

        if not proxy_pool:
            await fetch_proxies()

        username = usernames_batch_current.pop(0)
        proxy = proxy_pool[0] if proxy_pool else None
        proxy_pool.rotate(-1)

        available = await check_username(username, proxy)
        if available:
            info = usernames_checked_info.get(username, {})
            msg = (
                f"✅ *{username}* is available!\n"
                f"Since: {datetime.fromtimestamp(info['available_since']).strftime('%H:%M:%S')}"
            )
            await send_telegram(msg)

        await asyncio.sleep(1.2)
    await send_telegram("⏹️ Checker stopped.")

@app.post("/webhook")
async def telegram_webhook(request: Request):
    global checking_active
    data = await request.json()
    message = data.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "").strip()

    if chat_id != TELEGRAM_CHAT_ID:
        return JSONResponse({"status": "ignored"})

    if text == "/start":
        if not checking_active:
            checking_active = True
            asyncio.create_task(checker_loop())
            await send_telegram("🟢 Started checking usernames.")
        else:
            await send_telegram("Already running.")
    elif text == "/stop":
        checking_active = False
        await send_telegram("🔴 Stopping...")
    elif text == "/refresh":
        usernames_batch_current.clear()
        await send_telegram("🔄 Refreshed username batch.")
    elif text == "/proxies":
        await fetch_proxies()
    else:
        await send_telegram("❓ Unknown command. Use /start /stop /refresh /proxies.")

    return JSONResponse({"status": "ok"})

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
