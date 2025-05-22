import os
import asyncio
import aiohttp
import time
import random
import string
from collections import deque
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

load_dotenv()
app = FastAPI()

# Environment variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

checking_active = False
proxy_pool = deque()
usernames_batch_current = []
usernames_checked_info = {}
available_usernames_counts = {}

AVAILABLE_USERNAMES_FILE = "available_usernames.txt"

# Send Telegram message
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

# Set Telegram webhook on startup
@app.on_event("startup")
async def startup_event():
    async with aiohttp.ClientSession() as session:
        set_url = f"{telegram_api_url}/setWebhook"
        params = {"url": WEBHOOK_URL}
        async with session.post(set_url, params=params) as resp:
            res = await resp.json()
            print("Webhook response:", res)
            if res.get("ok"):
                print(f"✅ Webhook set: {WEBHOOK_URL}")
            else:
                print(f"❌ Failed to set webhook: {res}")

# Proxy scraping
async def fetch_proxies_webshare():
    url = "https://proxy.webshare.io/api/proxy/list/"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    params = {"page_size": 100}
    proxies = []
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                for p in data.get("results", []):
                    proxy = f"http://{p['username']}:{p['password']}@{p['proxy_address']}:{p['ports']['http']}"
                    proxies.append(proxy)
    return proxies

async def validate_proxy(proxy):
    test_url = "https://www.tiktok.com"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/114 Safari/537.36",
        "Accept": "text/html",
        "Accept-Language": "en-US",
    }
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(test_url, proxy=proxy, headers=headers) as resp:
                return resp.status == 200
    except:
        return False

async def refresh_and_validate_proxies():
    global proxy_pool
    await send_telegram("🔄 Refreshing proxies from Webshare...")
    proxies = await fetch_proxies_webshare()
    valid_proxies = deque()
    tasks = [validate_proxy(p) for p in proxies]
    results = await asyncio.gather(*tasks)
    for i, valid in enumerate(results):
        if valid:
            valid_proxies.append(proxies[i])
    proxy_pool = valid_proxies
    await send_telegram(f"✅ {len(proxy_pool)} working proxies loaded.")

# Username generation
def generate_usernames_batch(batch_size=50):
    return [''.join(random.choices(string.ascii_lowercase, k=4)) for _ in range(batch_size)]

# Check availability
async def check_username_availability(username: str, proxy: str = None):
    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/114 Safari/537.36",
        "Accept": "text/html",
    }
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url, proxy=proxy, headers=headers) as resp:
                return resp.status == 404
    except:
        return False

# Log available usernames
def log_available_username(username):
    now = int(time.time())
    count = available_usernames_counts.get(username, 0) + 1
    available_usernames_counts[username] = count

    updated = False
    new_lines = []
    if os.path.exists(AVAILABLE_USERNAMES_FILE):
        with open(AVAILABLE_USERNAMES_FILE, "r") as f:
            lines = f.readlines()
            for line in lines:
                if line.startswith(f"{username} "):
                    new_lines.append(f"{username} — hits: {count} — last seen: {datetime.utcfromtimestamp(now)}\n")
                    updated = True
                else:
                    new_lines.append(line)

    if not updated:
        new_lines.append(f"{username} — hits: {count} — last seen: {datetime.utcfromtimestamp(now)}\n")

    with open(AVAILABLE_USERNAMES_FILE, "w") as f:
        f.writelines(new_lines)

# Checker loop
async def checker_loop():
    global checking_active, usernames_batch_current
    await send_telegram("🟢 Checker started.")
    while checking_active:
        if not proxy_pool:
            await refresh_and_validate_proxies()
            if not proxy_pool:
                await asyncio.sleep(10)
                continue

        if not usernames_batch_current:
            usernames_batch_current = generate_usernames_batch(50)

        username = usernames_batch_current.pop(0)
        proxy = proxy_pool[0]
        proxy_pool.rotate(-1)

        if await check_username_availability(username, proxy):
            now_ts = int(time.time())
            usernames_checked_info[username] = {
                "available_since": now_ts,
                "last_checked": now_ts
            }
            log_available_username(username)

            keyboard = {
                "inline_keyboard": [
                    [{"text": "Claim", "callback_data": f"claim:{username}"}],
                    [{"text": "Skip", "callback_data": f"skip:{username}"}]
                ]
            }
            await send_telegram(f"✅ Username *{username}* is available!\nHits: {available_usernames_counts[username]}", reply_markup=keyboard)

        await asyncio.sleep(1)
    await send_telegram("⏹️ Checker stopped.")

# Telegram webhook
@app.post("/webhook")
async def telegram_webhook(req: Request):
    global checking_active
    try:
        data = await req.json()

        if "message" in data:
            message = data["message"]
            chat_id = message["chat"]["id"]
            text = message.get("text", "").lower()

            if chat_id != TELEGRAM_CHAT_ID:
                return JSONResponse({"ok": True})  # Ignore others

            if text == "/start":
                if not checking_active:
                    checking_active = True
                    asyncio.create_task(checker_loop())
                    await send_telegram("Started checking...")
                else:
                    await send_telegram("Checker already running.")
            elif text == "/stop":
                checking_active = False
                await send_telegram("Stopping checker...")
            elif text == "/refreshproxies":
                await refresh_and_validate_proxies()
            else:
                await send_telegram("Commands:\n/start\n/stop\n/refreshproxies")

        elif "callback_query" in data:
            cb = data["callback_query"]
            action, username = cb["data"].split(":")
            if action == "claim":
                await send_telegram(f"🟢 Claimed: {username}")
            elif action == "skip":
                await send_telegram(f"⏭ Skipped: {username}")

            cb_id = cb["id"]
            async with aiohttp.ClientSession() as session:
                await session.post(f"{telegram_api_url}/answerCallbackQuery", json={"callback_query_id": cb_id})

        return JSONResponse({"ok": True})

    except Exception as e:
        print("❌ Webhook error:", str(e))
        return JSONResponse({"ok": False, "error": str(e)}, status_code=200)
