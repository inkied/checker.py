import os
import aiohttp
import asyncio
import random
import time
from fastapi import FastAPI, Request
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")

proxies = []
proxies_health = {}
usernames = []
available_usernames = []
checking = False
checked_count = 0
current_index = 0

app = FastAPI()

def random_user_agent():
    return "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

async def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    async with aiohttp.ClientSession() as session:
        await session.post(url, json=payload)

async def update_proxy_health(proxy, success):
    if proxy not in proxies_health:
        proxies_health[proxy] = 0
    proxies_health[proxy] += 1 if success else -1
    if proxies_health[proxy] < -3:
        if proxy in proxies:
            proxies.remove(proxy)

async def replenish_proxies():
    url = "https://proxy.webshare.io/api/v2/proxy/list/download/"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as r:
            if r.status == 200:
                text = await r.text()
                new_proxies = [f"http://{line.strip()}" for line in text.splitlines()]
                proxies.extend(p for p in new_proxies if p not in proxies)
                for p in new_proxies:
                    proxies_health[p] = 0

def load_usernames():
    global usernames
    if os.path.exists("wordlist.txt"):
        with open("wordlist.txt") as f:
            usernames = [line.strip() for line in f if line.strip()]
    else:
        usernames = []

async def check_username(username, proxy):
    url = f"https://www.tiktok.com/@{username}"
    headers = {"User-Agent": random_user_agent()}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, proxy=proxy, timeout=10) as resp:
                if resp.status == 404:
                    await update_proxy_health(proxy, True)
                    return True
                else:
                    await update_proxy_health(proxy, True)
                    return False
    except Exception:
        await update_proxy_health(proxy, False)
        return False

async def start_checking(total_to_check):
    global checking, checked_count, available_usernames, current_index
    checking = True
    checked_count = 0
    available_usernames.clear()
    start_time = time.time()
    await send_telegram(f"🔍 Starting check for {total_to_check} usernames...")
    while checking and checked_count < total_to_check and current_index < len(usernames):
        username = usernames[current_index]
        current_index += 1
        proxy = random.choice(proxies)
        available = await check_username(username, proxy)
        checked_count += 1
        if available:
            available_usernames.append(username)
            await send_telegram(f"✅ Available: {username}")
        if len(proxies) < 50:
            await replenish_proxies()
        if checked_count % 10 == 0 or checked_count == total_to_check:
            elapsed = time.time() - start_time
            eta = (elapsed / checked_count) * (total_to_check - checked_count)
            await send_telegram(f"Progress: {checked_count}/{total_to_check} usernames | ETA: {int(eta)}s")
    checking = False
    await send_telegram("🎯 Username checking complete!")

async def stop_checking():
    global checking
    checking = False
    await send_telegram("🛑 Checking stopped.")

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    data = await request.json()
    message = data.get("message", {})
    text = message.get("text", "")
    if text.startswith("/start"):
        try:
            total = int(text.split()[1]) if len(text.split()) > 1 else 1000
        except:
            total = 1000
        asyncio.create_task(start_checking(total))
    elif text.startswith("/stop"):
        await stop_checking()
    elif text.startswith("/proxies"):
        total_proxies = len(proxies)
        removed = max(0, 100 - total_proxies)
        await send_telegram(f"⚙️ Proxies working: {total_proxies}/100 | Removed: {removed}")
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    load_usernames()
    asyncio.run(replenish_proxies())
    uvicorn.run("checker:app", host="0.0.0.0", port=8000)
