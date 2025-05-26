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
    logger.error("Missing environment variables.")
    raise SystemExit(1)

# --- Globals ---
app = FastAPI()
checking = False
proxies = []
proxy_index = 0
proxy_retries = {}
MAX_RETRIES = 3
wordlist = []

# --- Load Wordlist ---
def load_wordlist():
    path = "hyperclean_fastlist.txt"
    if os.path.exists(path):
        with open(path) as f:
            return [line.strip() for line in f if line.strip()]
    return []

# --- Username Generation ---
def generate_random_4char():
    first = random.choice("abcdefghijklmnopqrstuvwxyz")
    rest = ''.join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=3))
    return first + rest

# --- Telegram ---
async def send_telegram(message):
    async with aiohttp.ClientSession() as session:
        await session.post(f"https://api.telegram.org/bot{TELEGRAM_API}/sendMessage", json={
            "chat_id": CHAT_ID,
            "text": message
        })

async def set_webhook():
    async with aiohttp.ClientSession() as session:
        await session.post(f"https://api.telegram.org/bot{TELEGRAM_API}/setWebhook", data={"url": WEBHOOK_URL})

# --- Proxy Handling ---
async def fetch_proxies():
    url = "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as res:
            data = await res.json()
            return [f"http://{p['username']}:{p['password']}@{p['proxy_address']}:{p['port']}" for p in data['results']]

async def get_proxy():
    global proxy_index
    start_index = proxy_index
    while True:
        proxy = proxies[proxy_index % len(proxies)]
        retries = proxy_retries.get(proxy, 0)
        if retries < MAX_RETRIES:
            proxy_index += 1
            return proxy
        proxy_index += 1
        if proxy_index % len(proxies) == start_index:
            await asyncio.sleep(2)

# --- Check Logic ---
async def check_username(username):
    url = f"https://www.tiktok.com/@{username}"
    proxy = await get_proxy()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, proxy=proxy, timeout=10) as res:
                logger.info(f"Checking @{username} | Status: {res.status}")
                if res.status == 404:
                    await send_telegram(f"✅ Available: @{username}")
    except Exception as e:
        logger.warning(f"Proxy failed: {proxy} | {str(e)}")
        proxy_retries[proxy] = proxy_retries.get(proxy, 0) + 1

# --- Checker ---
async def batch_check():
    global checking, wordlist
    wordlist_index = 0
    while checking:
        batch = []
        for _ in range(5):
            if wordlist_index < len(wordlist):
                username = wordlist[wordlist_index]
                wordlist_index += 1
            else:
                username = generate_random_4char()
            batch.append(check_username(username))
        await asyncio.gather(*batch)
        await asyncio.sleep(random.uniform(0.2, 0.4))

# --- Webhook ---
@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    message = data.get("message", {}).get("text", "")
    if message.strip() == "/start":
        global checking
        if not checking:
            checking = True
            asyncio.create_task(batch_check())
            return JSONResponse({"ok": True})
    elif message.strip() == "/stop":
        checking = False
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": False})

@app.on_event("startup")
async def on_startup():
    global proxies, wordlist
    proxies = await fetch_proxies()
    wordlist = load_wordlist()
    await set_webhook()
    logger.info("Ready. Webhook set and proxies loaded.")
