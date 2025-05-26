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
check_letters_next = True  # To alternate username generation
proxies = []
proxy_index = 0
proxy_retries = {}
MAX_RETRIES = 3

# --- Utilities ---
def generate_clean_4letter():
    vowels = 'aeiou'
    consonants = 'bcdfghjklmnpqrstvwxyz'
    return ''.join([
        random.choice(consonants),
        random.choice(vowels),
        random.choice(consonants),
        random.choice(vowels),
    ])

def generate_clean_4char():
    letters = 'abcdefghijklmnopqrstuvwxyz'
    digits = '0123456789'
    chars = letters + digits
    username = ''.join(random.choices(chars, k=4))
    # Ensure at least one letter in username
    if all(c.isdigit() for c in username):
        pos = random.randint(0, 3)
        username = username[:pos] + random.choice(letters) + username[pos+1:]
    return username

def generate_username():
    global check_letters_next
    if check_letters_next:
        username = generate_clean_4letter()
    else:
        username = generate_clean_4char()
    check_letters_next = not check_letters_next
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
            await asyncio.sleep(5)

async def check_username(username):
    url = f"https://www.tiktok.com/@{username}"
    proxy = await get_proxy()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, proxy=proxy, timeout=10) as res:
                logger.info(f"@{username} | Status: {res.status}")
                if res.status == 404:
                    await send_telegram_message(f"Available username: @{username}")
    except Exception as e:
        logger.warning(f"Proxy failed: {proxy} | {str(e)}")
        proxy_retries[proxy] = proxy_retries.get(proxy, 0) + 1

async def start_checking():
    global checking
    checking = True
    while checking:
        username = generate_username()
        await check_username(username)
        await asyncio.sleep(random.uniform(0.4, 1.2))

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
