import os
import sys
import asyncio
import aiohttp
import time
import random
from collections import deque
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

# === LOAD AND VALIDATE ENV ===
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://checker.up.railway.app/webhook")

def exit_with_error(msg):
    print(f"❌ ENV ERROR: {msg}")
    sys.exit(1)

if not TELEGRAM_TOKEN:
    exit_with_error("Missing TELEGRAM_TOKEN in .env")
if not TELEGRAM_CHAT_ID:
    exit_with_error("Missing TELEGRAM_CHAT_ID in .env")
if not WEBSHARE_API_KEY:
    exit_with_error("Missing WEBSHARE_API_KEY in .env")

try:
    TELEGRAM_CHAT_ID = int(TELEGRAM_CHAT_ID)
except ValueError:
    exit_with_error("TELEGRAM_CHAT_ID must be a valid integer")

telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# === FastAPI app ===
app = FastAPI()

# === Global aiohttp session for reuse ===
aiohttp_session = None

@app.on_event("startup")
async def startup_event():
    global aiohttp_session
    aiohttp_session = aiohttp.ClientSession()

@app.on_event("shutdown")
async def shutdown_event():
    global aiohttp_session
    if aiohttp_session:
        await aiohttp_session.close()

# === Proxy scraping from Webshare ===
async def scrape_proxies():
    proxies = []
    headers = {"Authorization": f"Bearer {WEBSHARE_API_KEY}"}
    url = "https://proxy.webshare.io/api/proxy/list/?page=1&page_size=100"
    async with aiohttp_session.get(url, headers=headers, timeout=10) as resp:
        if resp.status == 200:
            data = await resp.json()
            for item in data.get("results", []):
                proxy = item.get("proxy_address")
                port = item.get("port")
                username = item.get("username")
                password = item.get("password")
                if username and password:
                    proxy_url = f"http://{username}:{password}@{proxy}:{port}"
                else:
                    proxy_url = f"http://{proxy}:{port}"
                proxies.append(proxy_url)
    return proxies

# === TikTok username availability check ===
async def check_username(username, proxy=None):
    # TikTok username check URL and headers
    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/114.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp_session.get(url, headers=headers, proxy=proxy, timeout=timeout) as resp:
            if resp.status == 404:
                return True  # username available (profile not found)
            elif resp.status == 200:
                return False  # username taken (profile exists)
            else:
                return None  # unknown status
    except Exception:
        return None

# === Send message to Telegram ===
async def send_telegram_message(text):
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        async with aiohttp_session.post(f"{telegram_api_url}/sendMessage", json=payload, timeout=10) as resp:
            return await resp.json()
    except Exception as e:
        print(f"Telegram send error: {e}")
        return None

# === Username checking worker ===
async def username_worker(usernames_queue: asyncio.Queue, proxies: deque):
    while not usernames_queue.empty():
        username = await usernames_queue.get()
        proxy = None
        if proxies:
            proxy = proxies[0]
            proxies.rotate(-1)
        available = await check_username(username, proxy)
        if available is True:
            print(f"[AVAILABLE] {username}")
            await send_telegram_message(f"✅ Username available: *{username}*")
        elif available is False:
            print(f"[TAKEN] {username}")
        else:
            print(f"[ERROR] Could not check {username}")
        await asyncio.sleep(random.uniform(0.5, 1.5))
        usernames_queue.task_done()

# === Main route to start checking usernames ===
@app.post("/start")
async def start_check(request: Request):
    data = await request.json()
    usernames = data.get("usernames")
    if not usernames or not isinstance(usernames, list):
        return JSONResponse({"error": "Missing or invalid 'usernames' list"}, status_code=400)

    proxies_list = await scrape_proxies()
    proxies = deque(proxies_list)

    usernames_queue = asyncio.Queue()
    for username in usernames:
        usernames_queue.put_nowait(username.lower())

    workers = []
    concurrency = min(20, usernames_queue.qsize())  # max 20 concurrent tasks
    for _ in range(concurrency):
        workers.append(asyncio.create_task(username_worker(usernames_queue, proxies)))

    await usernames_queue.join()
    for w in workers:
        w.cancel()

    return {"status": "completed", "checked_usernames": len(usernames)}

# === Telegram webhook handler ===
@app.post("/webhook")
async def telegram_webhook(request: Request):
    update = await request.json()
    message = update.get("message", {})
    text = message.get("text", "").strip()
    chat_id = message.get("chat", {}).get("id")

    if chat_id != TELEGRAM_CHAT_ID:
        return JSONResponse({"status": "ignored"})

    if text.startswith("/check "):
        username = text[7:].strip().lower()
        if not username.isalnum():
            await send_telegram_message("Invalid username. Use only letters and numbers.")
            return JSONResponse({"status": "invalid username"})
        available = await check_username(username)
        if available is True:
            await send_telegram_message(f"✅ Username available: *{username}*")
        elif available is False:
            await send_telegram_message(f"❌ Username taken: *{username}*")
        else:
            await send_telegram_message(f"⚠️ Could not check username: *{username}*")
        return JSONResponse({"status": "ok"})

    if text == "/start":
        await send_telegram_message("Send /check <username> to check a TikTok username.")
        return JSONResponse({"status": "ok"})

    return JSONResponse({"status": "ignored"})

# === Health check endpoint ===
@app.get("/health")
async def health():
    return {"status": "ok"}

# === ASGI app object (Railway compatibility) ===
# Run with: uvicorn checker:app --host 0.0.0.0 --port 8000
