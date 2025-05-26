import os
import asyncio
import aiohttp
import logging
import random
import time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

# --- Logging Setup ---
logger = logging.getLogger("tiktok-checker")
logging.basicConfig(level=logging.INFO)

# --- Environment Variables ---
TELEGRAM_API = os.getenv("TELEGRAM_API_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")

if not all([TELEGRAM_API, CHAT_ID, WEBHOOK_URL, WEBSHARE_API_KEY]):
    logger.error("Missing one or more required environment variables.")
    raise SystemExit(1)

# --- Globals ---
app = FastAPI()
checking = False
proxies = []
proxy_usage = {}
proxy_cooldowns = {}
proxy_retries = {}
MAX_RETRIES = 3
MAX_PROXY_USAGE = 20
PROXY_COOLDOWN = 300  # 5 minutes cooldown in seconds
MAX_CONCURRENT_CHECKS = 40

used_wordlist = set()
taken_usernames = set()

# --- Load and prepare wordlist ---
def load_wordlist():
    # Try loading wordlist.txt file with 20k usernames (letters and digits)
    path = "wordlist.txt"
    if not os.path.exists(path):
        logger.error(f"{path} not found. Please provide a wordlist.txt file with usernames.")
        raise SystemExit(1)
    with open(path, "r") as f:
        words = [line.strip().lower() for line in f if line.strip()]
    random.shuffle(words)
    logger.info(f"Loaded wordlist with {len(words)} usernames.")
    return words

wordlist = load_wordlist()

# --- Telegram Messaging ---
async def send_telegram_message(message):
    async with aiohttp.ClientSession() as session:
        try:
            await session.post(f"https://api.telegram.org/bot{TELEGRAM_API}/sendMessage", json={
                "chat_id": CHAT_ID,
                "text": message
            })
        except Exception as e:
            logger.warning(f"Failed to send Telegram message: {e}")

async def set_webhook():
    async with aiohttp.ClientSession() as session:
        try:
            await session.post(f"https://api.telegram.org/bot{TELEGRAM_API}/setWebhook", data={"url": WEBHOOK_URL})
            logger.info("Telegram webhook set successfully.")
        except Exception as e:
            logger.error(f"Failed to set Telegram webhook: {e}")

# --- Proxy Management ---
def get_available_proxy():
    now = time.time()
    available = [p for p in proxies if
                 proxy_usage.get(p, 0) < MAX_PROXY_USAGE and
                 proxy_retries.get(p, 0) < MAX_RETRIES and
                 proxy_cooldowns.get(p, 0) <= now]
    if not available:
        return None
    return random.choice(available)

def mark_proxy_usage(proxy):
    proxy_usage[proxy] = proxy_usage.get(proxy, 0) + 1
    if proxy_usage[proxy] >= MAX_PROXY_USAGE:
        proxy_cooldowns[proxy] = time.time() + PROXY_COOLDOWN
        proxy_usage[proxy] = 0
        logger.info(f"Proxy cooldown activated: {proxy}")

def mark_proxy_failure(proxy):
    proxy_retries[proxy] = proxy_retries.get(proxy, 0) + 1
    if proxy_retries[proxy] >= MAX_RETRIES:
        proxy_cooldowns[proxy] = time.time() + PROXY_COOLDOWN
        proxy_retries[proxy] = 0
        logger.info(f"Proxy banned/failed and cooldown started: {proxy}")

async def fetch_proxies():
    url = f"https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as res:
            data = await res.json()
            return [f"http://{p['username']}:{p['password']}@{p['proxy_address']}:{p['port']}" for p in data['results']]

# --- Username generation from wordlist or fallback ---
def generate_username():
    while wordlist:
        candidate = wordlist.pop(0)
        if candidate not in taken_usernames and candidate not in used_wordlist:
            used_wordlist.add(candidate)
            return candidate
    # fallback random 4 chars letters + digits
    while True:
        candidate = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=4))
        if candidate not in taken_usernames and candidate not in used_wordlist:
            used_wordlist.add(candidate)
            return candidate

# --- Checking usernames ---
async def check_username(semaphore):
    async with semaphore:
        username = generate_username()
        proxy = None
        for _ in range(5):
            proxy = get_available_proxy()
            if proxy:
                break
            await asyncio.sleep(1)
        if not proxy:
            # No proxies available, wait and retry later
            await asyncio.sleep(5)
            return

        mark_proxy_usage(proxy)
        url = f"https://www.tiktok.com/@{username}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, proxy=proxy, timeout=10) as res:
                    logger.info(f"Checked @{username} | Status: {res.status}")
                    if res.status == 404:
                        await send_telegram_message(f"Available: @{username}")
                        taken_usernames.add(username)  # Mark as found available
                    else:
                        taken_usernames.add(username)  # Mark as taken to skip next time
        except Exception as e:
            logger.warning(f"Proxy failed: {proxy} | {e}")
            mark_proxy_failure(proxy)

# --- Main checking loop ---
async def start_checking():
    global checking
    checking = True
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)
    while checking:
        await check_username(semaphore)
        # Small sleep to avoid flooding, can tweak here
        await asyncio.sleep(0.05)

async def stop_checking():
    global checking
    checking = False

# --- FastAPI webhook route ---
@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    message = data.get("message", {}).get("text", "")
    if message == "/start":
        if not checking:
            asyncio.create_task(start_checking())
            logger.info("Started checking.")
    elif message == "/stop":
        await stop_checking()
        logger.info("Stopped checking.")
    return JSONResponse({"ok": True})

# --- Startup event ---
@app.on_event("startup")
async def on_startup():
    global proxies
    proxies = await fetch_proxies()
    await set_webhook()
    logger.info(f"Loaded {len(proxies)} proxies and webhook set.")
