import os
import asyncio
import aiohttp
import time
import random
from collections import deque
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or "your_telegram_token_here"
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID") or 0)
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY") or "your_webshare_api_key_here"
WEBHOOK_URL = os.getenv("WEBHOOK_URL") or "https://yourapp.up.railway.app/webhook"

telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

checking_active = False
proxy_pool = deque()
usernames_batch_current = []
usernames_checked_info = {}
available_usernames_counts = {}

AVAILABLE_USERNAMES_FILE = "available_usernames.txt"

BRAND_BASES = [
    "luxe", "nova", "pique", "vanta", "kuro", "aero", "vela", "mira", "sola", "zara",
    "ryze", "kyro", "zeal", "flux", "kine", "nexa", "orbi", "lyra", "echo", "riva"
]
BRAND_SUFFIXES = ["ly", "io", "ex", "us", "on"]

def generate_brand_usernames(batch_size=50):
    usernames = []
    while len(usernames) < batch_size:
        base = random.choice(BRAND_BASES)
        username = base + random.choice(BRAND_SUFFIXES) if random.random() < 0.6 else base
        if 3 <= len(username) <= 24 and username not in usernames:
            usernames.append(username)
    return usernames

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

@app.on_event("startup")
async def startup_event():
    async with aiohttp.ClientSession() as session:
        await session.post(
            f"{telegram_api_url}/setWebhook",
            params={"url": WEBHOOK_URL}
        )

async def fetch_proxies_webshare():
    url = "https://proxy.webshare.io/api/proxy/list/"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    params = {"page_size": 100}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                return [
                    f"http://{p['username']}:{p['password']}@{p['proxy_address']}:{p['ports']['http']}"
                    for p in data.get("results", [])
                ]
    return []

async def validate_proxy(proxy):
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get("https://www.tiktok.com", proxy=proxy) as resp:
                return resp.status == 200
    except:
        return False

async def refresh_and_validate_proxies():
    global proxy_pool
    await send_telegram("🔄 Refreshing proxies...")
    proxies = await fetch_proxies_webshare()
    results = await asyncio.gather(*(validate_proxy(p) for p in proxies))
    proxy_pool = deque(p for p, valid in zip(proxies, results) if valid)
    await send_telegram(f"✅ {len(proxy_pool)} valid proxies loaded.")

async def check_username_availability(username, proxy=None):
    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url, proxy=proxy, headers=headers) as resp:
                return resp.status == 404
    except:
        return False

def log_available_username(username):
    now = int(time.time())
    count = available_usernames_counts.get(username, 0) + 1
    available_usernames_counts[username] = count

    lines = []
    if os.path.exists(AVAILABLE_USERNAMES_FILE):
        with open(AVAILABLE_USERNAMES_FILE, "r") as f:
            lines = f.readlines()

    updated = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{username} "):
            new_lines.append(
                f"{username} — hits: {count} — last seen: {datetime.utcfromtimestamp(now)} UTC\n"
            )
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(
            f"{username} — hits: {count} — last seen: {datetime.utcfromtimestamp(now)} UTC\n"
        )

    with open(AVAILABLE_USERNAMES_FILE, "w") as f:
        f.writelines(new_lines)

async def checker_loop():
    global checking_active, usernames_batch_current
    await send_telegram("🟢 Checker started.")
    while checking_active:
        if not proxy_pool:
            await send_telegram("⚠️ Proxy pool empty. Refreshing...")
            await refresh_and_validate_proxies()
            if not proxy_pool:
                await asyncio.sleep(10)
                continue

        if not usernames_batch_current:
            usernames_batch_current = generate_brand_usernames(50)
            await send_telegram(f"📦 New batch of {len(usernames_batch_current)} usernames loaded.")

        username = usernames_batch_current.pop(0)
        proxy = proxy_pool[0]
        proxy_pool.rotate(-1)

        if await check_username_availability(username, proxy):
            log_available_username(username)
            msg = f"✅ *{username}* is available!\nHits: {available_usernames_counts[username]}"
            keyboard = {
                "inline_keyboard": [
                    [{"text": "Claim", "callback_data": f"claim:{username}"}],
                    [{"text": "Skip", "callback_data": f"skip:{username}"}]
                ]
            }
            await send_telegram(msg, reply_markup=keyboard)
        await asyncio.sleep(1)
    await send_telegram("⏹️ Checker stopped.")

@app.post("/webhook")
async def telegram_webhook(req: Request):
    global checking_active
    data = await req.json()

    if "message" in data:
        msg = data["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")
        if chat_id != TELEGRAM_CHAT_ID:
            return JSONResponse(content={"ok": True})

        if text == "/start":
            if not checking_active:
                checking_active = True
                asyncio.create_task(checker_loop())
            await send_telegram("Checker started.")
        elif text == "/stop":
            checking_active = False
            await send_telegram("Checker stopping...")
        elif text == "/refreshproxies":
            await refresh_and_validate_proxies()

    elif "callback_query" in data:
        cb = data["callback_query"]
        cb_data = cb["data"]
        cb_id = cb["id"]
        username = cb_data.split(":")[1]
        if cb_data.startswith("claim:"):
            await send_telegram(f"👍 Claimed *{username}*")
        elif cb_data.startswith("skip:"):
            await send_telegram(f"⏩ Skipped *{username}*")
        async with aiohttp.ClientSession() as session:
            await session.post(f"{telegram_api_url}/answerCallbackQuery", json={"callback_query_id": cb_id})

    return JSONResponse(content={"ok": True})
