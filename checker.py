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

async def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    async with aiohttp.ClientSession() as session:
        await session.post(url, json=payload)

def random_user_agent():
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)...",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)...",
        # Add more realistic user agents
    ]
    return random.choice(user_agents)

async def update_proxy_health(proxy, success):
    if proxy not in proxies_health:
        proxies_health[proxy] = {"success": 0, "fail": 0}
    if success:
        proxies_health[proxy]["success"] += 1
    else:
        proxies_health[proxy]["fail"] += 1

    # Remove proxy if it failed 3 times consecutively
    if proxies_health[proxy]["fail"] >= 3:
        if proxy in proxies:
            proxies.remove(proxy)
        await send_telegram(f"Removed bad proxy: {proxy} (Failures: {proxies_health[proxy]['fail']})")

async def fetch_proxies():
    url = "https://proxy.webshare.io/api/proxy/list/"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            data = await resp.json()
            new_proxies = []
            for item in data.get("results", [])[:100]:
                proxy_str = f"http://{item['proxy_address']}:{item['ports']['http']}"
                new_proxies.append(proxy_str)
            return new_proxies

async def replenish_proxies():
    global proxies
    new_proxies = await fetch_proxies()
    added = 0
    for p in new_proxies:
        if p not in proxies:
            proxies.append(p)
            added += 1
    await send_telegram(f"Replenished proxies: added {added}, total now {len(proxies)}")

async def check_username(username, proxy):
    """Check if a TikTok username is available using a proxy."""
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
    logger.info(f"Starting check for {total_to_check} usernames...")
    while checking and checked_count < total_to_check and current_index < len(usernames):
        username = usernames[current_index]
        current_index += 1
        proxy = random.choice(proxies)
        available = await check_username(username, proxy)
        checked_count += 1
        if available:
            available_usernames.append(username)
            await send_telegram(f"Available: {username}")
        if len(proxies) < 50:
            await replenish_proxies()
        # Update status every 10 checks
        if checked_count % 10 == 0 or checked_count == total_to_check:
            elapsed = time.time() - start_time
            eta = (elapsed / checked_count) * (total_to_check - checked_count)
            await send_telegram(f"Checked {checked_count}/{total_to_check} usernames. ETA: {int(eta)}s")
    checking = False
    await send_telegram("Checking complete!")

async def stop_checking():
    global checking
    checking = False
    await send_telegram("Checking stopped.")

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

# Telegram bot command handlers
async def handle_message(message):
    text = message.text
    if text.startswith("/start"):
        try:
            parts = text.split()
            total = int(parts[1]) if len(parts) > 1 else 1000
        except:
            total = 1000
        await send_telegram(f"Starting username check for {total} usernames.")
        asyncio.create_task(start_checking(total))
    elif text.startswith("/stop"):
        await stop_checking()
    elif text.startswith("/proxies"):
        total_proxies = len(proxies)
        removed = max(0, 100 - total_proxies)
        await send_telegram(f"Proxies working: {total_proxies}/100, removed: {removed}")

@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    if "message" in data:
        await handle_message(data["message"])
    return JSONResponse(content={"ok": True})

if __name__ == "__main__":
    import uvicorn

    # Set your Telegram webhook URL here or in environment variables
    TELEGRAM_WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL")

    # Set webhook on startup (optional, if not set externally)
    async def set_webhook():
        async with aiohttp.ClientSession() as session:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
            params = {"url": TELEGRAM_WEBHOOK_URL}
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    print("Webhook set successfully.")
                else:
                    print("Failed to set webhook.")

    import asyncio
    asyncio.run(set_webhook())

    # Start FastAPI app with Uvicorn
    uvicorn.run("checker:app", host="0.0.0.0", port=8000, log_level="info")


    

