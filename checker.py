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

# Webhook setup
async def set_telegram_webhook():
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
    payload = {"url": WEBHOOK_PATH}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    print("✅ Webhook set successfully.")
                else:
                    error_text = await resp.text()
                    print(f"❌ Failed to set webhook: {resp.status}, {error_text}")
        except Exception as e:
            print(f"❌ Exception setting webhook: {e}")

@app.on_event("startup")
async def startup_event():
    await set_telegram_webhook()
    await fetch_proxies()
    print("✅ Startup complete.")

# Proxy fetching
async def fetch_proxies():
    global proxies
    url = "https://proxy.webshare.io/api/proxy/list/"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            data = await resp.json()
            new_proxies = []
            for item in data.get("results", []):
                proxy_str = f"http://{item['proxy_address']}:{item['ports']['http']}"
                new_proxies.append(proxy_str)
            proxies = new_proxies
            for p in proxies:
                proxies_health[p] = 1.0

# Proxy health
async def update_proxy_health(proxy, success):
    health = proxies_health.get(proxy, 1.0)
    health = min(1.0, health + 0.1) if success else max(0, health - 0.2)
    proxies_health[proxy] = health
    if health <= 0:
        proxies.remove(proxy)
        proxies_health.pop(proxy, None)

# User agent
def random_user_agent():
    agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)...",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)...",
    ]
    return random.choice(agents)

# Telegram message
async def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    async with aiohttp.ClientSession() as session:
        try:
            await session.post(url, json=payload)
        except Exception as e:
            print(f"Telegram send error: {e}")

# Check TikTok username
async def check_username(username, proxy):
    url = f"https://www.tiktok.com/@{username}"
    headers = {"User-Agent": random_user_agent()}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, proxy=proxy, timeout=10) as resp:
                await update_proxy_health(proxy, True)
                return resp.status == 404
    except Exception:
        await update_proxy_health(proxy, False)
        return False

# Replenish proxies
async def replenish_proxies_if_needed():
    if len(proxies) < 50:
        await send_telegram(f"Proxy count low ({len(proxies)}). Replenishing proxies...")
        await fetch_proxies()
        await send_telegram(f"Proxies replenished. Total now: {len(proxies)}")

# Start checking
async def start_checking(total_to_check):
    global checking, checked_count, available_usernames, current_index
    checking = True
    checked_count = 0
    available_usernames.clear()
    start_time = time.time()
    await send_telegram(f"Starting check for {total_to_check} usernames...")

    while checking and checked_count < total_to_check and current_index < len(usernames):
        username = usernames[current_index]
        current_index += 1
        proxy = random.choice(proxies) if proxies else None
        if not proxy:
            await send_telegram("No proxies available. Waiting 5 seconds...")
            await asyncio.sleep(5)
            await replenish_proxies_if_needed()
            continue
        available = await check_username(username, proxy)
        checked_count += 1
        if available:
            available_usernames.append(username)
            await send_telegram(f"Available: {username}")
        await replenish_proxies_if_needed()
        if checked_count % 10 == 0 or checked_count == total_to_check:
            elapsed = time.time() - start_time
            eta = (elapsed / checked_count) * (total_to_check - checked_count)
            await send_telegram(f"Checked {checked_count}/{total_to_check} usernames. ETA: {int(eta)}s")

    checking = False
    await send_telegram("✅ Checking complete!")

# Stop checking
async def stop_checking():
    global checking
    checking = False
    await send_telegram("🛑 Checking stopped.")

# Telegram webhook handler
@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    if "message" in data:
        message = data["message"]
        text = message.get("text", "")
        chat_id = message["chat"]["id"]
        if str(chat_id) != str(TELEGRAM_CHAT_ID):
            return {"ok": True}
        if text.startswith("/start"):
            parts = text.split()
            try:
                total = int(parts[1]) if len(parts) > 1 else 1000
            except:
                total = 1000
            await send_telegram(f"▶️ Starting username check for {total} usernames.")
            asyncio.create_task(start_checking(total))
        elif text.startswith("/stop"):
            await stop_checking()
        elif text.startswith("/proxies"):
            total_proxies = len(proxies)
            removed = max(0, 100 - total_proxies)
            await send_telegram(f"Proxies working: {total_proxies}/100, removed: {removed}")
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("checker:app", host="0.0.0.0", port=8000, reload=True)
