import os
import asyncio
import aiohttp
import logging
import random
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
proxy_index = 0
proxy_usage_count = {}
proxy_retries = {}
MAX_PROXY_USAGE = 15
MAX_RETRIES = 3
taken_usernames = set()

# --- Utilities ---
def generate_random_4letter():
    chars = 'abcdefghijklmnopqrstuvwxyz0123456789'
    while True:
        username = ''.join(random.choices(chars, k=4))
        if username not in taken_usernames:
            return username

async def send_telegram_message(message):
    async with aiohttp.ClientSession() as session:
        await session.post(f"https://api.telegram.org/bot{TELEGRAM_API}/sendMessage", json={
            "chat_id": CHAT_ID,
            "text": message
        })

async def set_webhook():
    async with aiohttp.ClientSession() as session:
        await session.post(f"https://api.telegram.org/bot{TELEGRAM_API}/setWebhook", data={"url": WEBHOOK_URL})

async def fetch_proxies():
    url = f"https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as res:
            data = await res.json()
            return [f"http://{p['username']}:{p['password']}@{p['proxy_address']}:{p['port']}" for p in data['results']]

def get_next_proxy():
    global proxy_index
    if not proxies:
        return None

    for _ in range(len(proxies)):
        proxy = proxies[proxy_index % len(proxies)]
        usage = proxy_usage_count.get(proxy, 0)
        retries = proxy_retries.get(proxy, 0)
        if usage < MAX_PROXY_USAGE and retries < MAX_RETRIES:
            proxy_usage_count[proxy] = usage + 1
            proxy_index += 1
            return proxy
        proxy_index += 1

    # Reset if all proxies maxed out or bad
    proxy_usage_count.clear()
    proxy_retries.clear()
    return get_next_proxy()

async def check_username(username):
    proxy = get_next_proxy()
    if not proxy:
        logger.warning("No proxies available, waiting 5 seconds...")
        await asyncio.sleep(5)
        return

    url = f"https://www.tiktok.com/@{username}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, proxy=proxy, timeout=10) as res:
                logger.info(f"@{username} | Status: {res.status}")
                if res.status == 404:
                    await send_telegram_message(f"Available: @{username}")
                else:
                    taken_usernames.add(username)
    except Exception as e:
        logger.warning(f"Proxy failed: {proxy} | {str(e)}")
        proxy_retries[proxy] = proxy_retries.get(proxy, 0) + 1

async def start_checking():
    global checking
    checking = True
    while checking:
        username = generate_random_4letter()
        await check_username(username)
        # No sleep here — max speed with proxy balancing

async def stop_checking():
    global checking
    checking = False

# --- Webhook Routes ---
@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    message = data.get("message", {}).get("text", "")
    if message == "/start":
        if not checking:
            asyncio.create_task(start_checking())
    elif message == "/stop":
        await stop_checking()
    return JSONResponse({"ok": True})

# --- FastAPI Startup ---
@app.on_event("startup")
async def on_startup():
    global proxies
    proxies = await fetch_proxies()
    await set_webhook()
    logger.info("Webhook set and proxies loaded.")
