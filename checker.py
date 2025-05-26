import os
import asyncio
import aiohttp
import aiofiles
import logging
import random
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("tiktok-checker")
logging.basicConfig(level=logging.INFO)

TELEGRAM_API = os.getenv("TELEGRAM_API_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")

if not all([TELEGRAM_API, CHAT_ID, WEBHOOK_URL, WEBSHARE_API_KEY]):
    logger.error("Missing one or more required environment variables.")
    raise SystemExit(1)

app = FastAPI()
checking = False
proxies = []
proxy_retries = {}
MAX_RETRIES = 3

username_queue = asyncio.Queue()

# --- Utilities ---
def generate_random_4letter():
    # Random 4-letter with letter start, digits allowed 2-4 pos
    letters = 'abcdefghijklmnopqrstuvwxyz'
    digits = '0123456789'
    first = random.choice(letters)
    rest = [random.choice(letters + digits) for _ in range(3)]
    return first + ''.join(rest)

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

async def load_wordlist(path):
    async with aiofiles.open(path, mode="r") as f:
        lines = await f.readlines()
        return [line.strip() for line in lines if line.strip()]

async def fill_queue(wordlist):
    for username in wordlist:
        await username_queue.put(username)
    logger.info(f"Enqueued {len(wordlist)} usernames for checking.")

async def get_proxy():
    global proxies, proxy_retries
    for _ in range(len(proxies)):
        proxy = random.choice(proxies)
        retries = proxy_retries.get(proxy, 0)
        if retries < MAX_RETRIES:
            return proxy
    # If all proxies hit max retries, wait a bit and reset
    await asyncio.sleep(5)
    proxy_retries.clear()
    return random.choice(proxies) if proxies else None

async def remove_bad_proxy(proxy):
    global proxies, proxy_retries
    if proxy in proxies:
        proxies.remove(proxy)
    if proxy in proxy_retries:
        del proxy_retries[proxy]
    logger.warning(f"Removed bad proxy: {proxy}. Proxies left: {len(proxies)}")

async def check_username(username):
    proxy = await get_proxy()
    if not proxy:
        logger.warning("No proxies available.")
        return

    url = f"https://www.tiktok.com/@{username}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, proxy=proxy, timeout=10) as res:
                logger.info(f"Checked @{username} | Status: {res.status} | Proxy: {proxy}")
                if res.status == 404:
                    # Username available
                    await send_telegram_message(f"Available: @{username}")
                elif res.status in (429, 403):
                    # Proxy likely banned, remove it
                    proxy_retries[proxy] = MAX_RETRIES
                    await remove_bad_proxy(proxy)
                else:
                    # Username taken or unknown status
                    pass
    except Exception as e:
        logger.warning(f"Proxy error {proxy}: {e}")
        proxy_retries[proxy] = proxy_retries.get(proxy, 0) + 1
        if proxy_retries[proxy] >= MAX_RETRIES:
            await remove_bad_proxy(proxy)

async def check_worker():
    global checking
    while checking:
        if username_queue.empty():
            # fallback to live generation when queue exhausted
            username = generate_random_4letter()
        else:
            username = await username_queue.get()

        await check_username(username)
        await asyncio.sleep(0)  # yield control

async def start_checking():
    global checking, proxies
    if checking:
        logger.info("Already checking.")
        return

    checking = True
    wordlist = await load_wordlist("semi_og_4letter_with_digits.txt")
    await fill_queue(wordlist)
    logger.info("Starting username checking...")

    # Start workers based on proxies count, max 40
    concurrency = min(len(proxies), 40)
    workers = [asyncio.create_task(check_worker()) for _ in range(concurrency)]

    await asyncio.gather(*workers)

async def stop_checking():
    global checking
    checking = False
    logger.info("Stopped username checking.")

@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    message = data.get("message", {}).get("text", "")
    if message == "/start":
        asyncio.create_task(start_checking())
    elif message == "/stop":
        await stop_checking()
    return JSONResponse({"ok": True})

@app.on_event("startup")
async def on_startup():
    global proxies
    proxies = await fetch_proxies()
    await set_webhook()
    logger.info(f"Loaded {len(proxies)} proxies and set webhook.")
