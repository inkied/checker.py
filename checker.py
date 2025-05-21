import os
import random
import asyncio
import aiohttp
from fastapi import FastAPI, Request
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
PROXY_API = f"https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100"

app = FastAPI()

checking = False
proxy_pool = []
usernames = set()

def generate_usernames():
    chars = "abcdefghijklmnopqrstuvwxyz"
    return ["".join(random.sample(chars, 4)) for _ in range(1000)]

async def fetch_proxies():
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(PROXY_API, headers=headers) as resp:
            data = await resp.json()
            proxies = [f"{p['username']}:{p['password']}@{p['proxy_address']}:{p['port']}" for p in data['results']]
            random.shuffle(proxies)
            return proxies

async def check_username(username, proxy, session):
    try:
        proxy_url = f"http://{proxy}"
        url = f"https://www.tiktok.com/@{username}"
        headers = {
            "User-Agent": random.choice([
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                "Mozilla/5.0 (Linux; Android 11; Pixel 5)"
            ]),
            "Accept-Language": "en-US,en;q=0.9",
        }
        async with session.get(url, headers=headers, proxy=proxy_url, timeout=10) as resp:
            if resp.status == 404:
                return username
    except:
        pass
    return None

async def send_telegram(msg, buttons=None):
    data = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}
    if buttons:
        data["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d}] for t, d in buttons]}
    async with aiohttp.ClientSession() as session:
        await session.post(f"{TELEGRAM_API}/sendMessage", json=data)

@app.post("/webhook")
async def telegram_webhook(req: Request):
    body = await req.json()
    message = body.get("message") or body.get("callback_query", {}).get("message")
    query_data = body.get("callback_query", {}).get("data")

    if message and query_data:
        if query_data == "start":
            asyncio.create_task(start_checking())
            await send_telegram("✅ Checking started.")
        elif query_data == "stop":
            global checking
            checking = False
            await send_telegram("⛔️ Checking stopped.")
        elif query_data == "refresh":
            asyncio.create_task(refresh_proxies())
            await send_telegram("🔁 Proxies refreshed.")

    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "Running"}

async def refresh_proxies():
    global proxy_pool
    proxy_pool = await fetch_proxies()

async def start_checking():
    global checking, proxy_pool, usernames
    checking = True
    if not proxy_pool:
        await refresh_proxies()
    usernames = set(generate_usernames())

    async with aiohttp.ClientSession() as session:
        while checking and usernames:
            batch = [usernames.pop() for _ in range(min(20, len(usernames)))]
            tasks = [
                check_username(user, random.choice(proxy_pool), session)
                for user in batch
            ]
            results = await asyncio.gather(*tasks)
            available = [r for r in results if r]
            if available:
                msg = "\n".join([f"<code>{u}</code> — https://tiktok.com/@{u}" for u in available])
                await send_telegram(f"🟢 Available usernames:\n{msg}")
            await asyncio.sleep(random.uniform(0.5, 1.5))

# Telegram start message
@app.on_event("startup")
async def notify_ready():
    await send_telegram(
        "🤖 Bot ready. Use the buttons below:",
        buttons=[("▶️ Start", "start"), ("⏹ Stop", "stop"), ("🔁 Refresh Proxies", "refresh")]
    )
