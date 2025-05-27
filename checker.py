import os
import aiohttp
import asyncio
import random
from fastapi import FastAPI, Request
from dotenv import load_dotenv
from typing import List
import uvicorn

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
APP_URL = os.getenv("APP_URL")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")

app = FastAPI()

proxies: List[str] = []
usernames: List[str] = []
active = False

async def fetch_proxies():
    global proxies
    url = "https://proxy.webshare.io/api/v2/proxy/list/download/"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            proxy_list = await resp.text()
            proxies = list(filter(None, proxy_list.splitlines()))[:100]

async def check_username(session, username: str, proxy: str):
    proxy_url = f"http://{proxy}"
    try:
        async with session.head(f"https://www.tiktok.com/@{username}", proxy=proxy_url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status == 404:
                await send_telegram_message(f"✅ Available: {username}")
                async with aiofiles.open("Available.txt", "a") as f:
                    await f.write(username + "\n")
            elif r.status == 200:
                pass  # Unavailable
    except:
        if proxy in proxies:
            proxies.remove(proxy)

async def checker_loop():
    global active, usernames
    await fetch_proxies()
    async with aiohttp.ClientSession() as session:
        for username in usernames:
            if not active:
                break
            if len(proxies) < 10:
                await fetch_proxies()
            proxy = random.choice(proxies)
            await check_username(session, username, proxy)
            await asyncio.sleep(random.uniform(0.5, 1.2))

async def send_telegram_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    async with aiohttp.ClientSession() as session:
        await session.post(url, json=payload)

@app.post("/webhook")
async def webhook(request: Request):
    global active
    data = await request.json()
    message = data.get("message", {})
    text = message.get("text", "")
    chat_id = message["chat"]["id"]

    if str(chat_id) != str(TELEGRAM_CHAT_ID):
        return {"ok": True}

    if text.startswith("/start"):
        if not active:
            active = True
            await send_telegram_message("✅ Starting checker.")
            asyncio.create_task(checker_loop())
        else:
            await send_telegram_message("🔁 Checker is already running.")
    elif text.startswith("/stop"):
        active = False
        await send_telegram_message("🛑 Checker stopped.")
    elif text.startswith("/proxies"):
        total = 100
        removed = total - len(proxies)
        await send_telegram_message(f"🔌 Proxy health:\nTotal: 100\nRemoved: {removed}\nRemaining: {len(proxies)}")
        if len(proxies) < 10:
            await fetch_proxies()
            await send_telegram_message("♻️ Proxies replenished.")

    return {"ok": True}

@app.on_event("startup")
async def on_startup():
    global usernames
    webhook_url = f"{APP_URL}/webhook"
    set_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
    async with aiohttp.ClientSession() as session:
        await session.post(set_url, json={"url": webhook_url})
    # Load usernames on startup
    if os.path.exists("usernames.txt"):
        with open("usernames.txt", "r", encoding="utf-8") as f:
            usernames = [line.strip() for line in f if line.strip()]

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
