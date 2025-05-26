import os
import asyncio
import aiohttp
import aiofiles
import logging
import random
import re
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
session = None  # Global aiohttp.ClientSession

NOT_FOUND_PATTERNS = [
    re.compile(r"Sorry, this page isn’t available", re.I),
    re.compile(r"User Not Found", re.I),
    re.compile(r"Page Not Found", re.I),
    re.compile(r"Couldn't find this account", re.I),
]

def generate_random_4letter():
    letters = 'abcdefghijklmnopqrstuvwxyz'
    digits = '0123456789'
    first = random.choice(letters)
    rest = [random.choice(letters + digits) for _ in range(3)]
    return first + ''.join(rest)

async def send_telegram_message(message):
    global session
    if not session or session.closed:
        session = aiohttp.ClientSession()
    try:
        await session.post(f"https://api.telegram.org/bot{TELEGRAM_API}/sendMessage", json={
            "chat_id": CHAT_ID,
            "text": message
        })
    except Exception as e:
        logger.warning(f"Telegram send error: {e}")

async def set_webhook():
    global session
    if not session or session.closed:
        session = aiohttp.ClientSession()
    try:
        await session.post(f"https://api.telegram.org/bot{TELEGRAM_API}/setWebhook", data={"url": WEBHOOK_URL})
    except Exception as e:
        logger.warning(f"Set webhook error: {e}")

async def fetch_proxies():
    url = f"https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    global session
    if not session or session.closed:
        session = aiohttp.ClientSession()
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
    # All proxies max retries, wait and reset counters
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

async def is_proxy_healthy(proxy):
    test_url = "https://www.tiktok.com/@thisusernamedoesnotexist12345"
    global session
    try:
        async with session.get(test_url, proxy=proxy, timeout=10) as res:
            text = await res.text()
            if res.status == 404:
                return True
            if res.status == 200:
                for pattern in NOT_FOUND_PATTERNS:
                    if pattern.search(text):
                        return True
        return False
    except Exception as e:
        logger.debug(f"Proxy health check failed {proxy}: {e}")
        return False

async def filter_healthy_proxies():
    global proxies
    logger.info("Starting proxy health check...")
    healthy = []
    for proxy in proxies:
        if await is_proxy_healthy(proxy):
            healthy.append(proxy)
        else:
            logger.info(f"Removing unhealthy proxy: {proxy}")
    proxies = healthy
    logger.info(f"Proxy health check complete: {len(proxies)} proxies healthy.")

async def check_username(username):
    proxy = await get_proxy()
    if not proxy:
        logger.warning("No proxies available.")
        return

    url = f"https://www.tiktok.com/@{username}"
    global session
    try:
        async with session.get(url, proxy=proxy, timeout=10) as res:
            text = await res.text()
            logger.info(f"Checked @{username} | Status: {res.status} | Proxy: {proxy}")

            if res.status == 404:
                await send_telegram_message(f"Available: @{username}")
            elif res.status == 200:
                if any(pattern.search(text) for pattern in NOT_FOUND_PATTERNS):
                    await send_telegram_message(f"Available (parsed): @{username}")
            elif res.status in (429, 403):
                proxy_retries[proxy] = MAX_RETRIES
                await remove_bad_proxy(proxy)
    except Exception as e:
        logger.warning(f"Proxy error {proxy}: {e}")
        proxy_retries[proxy] = proxy_retries.get(proxy, 0) + 1
        if proxy_retries[proxy] >= MAX_RETRIES:
            await remove_bad_proxy(proxy)

async def check_worker():
    global checking
    while checking:
        if username_queue.empty():
            username = generate_random_4letter()
        else:
            username = await username_queue.get()

        await check_username(username)
        await asyncio.sleep(0)  # yield control

async def start_checking():
    global checking, proxies, session
    if checking:
        logger.info("Already checking.")
        return

    checking = True

    if not session or session.closed:
        session = aiohttp.ClientSession()

    wordlist = await load_wordlist("semi_og_4letter_with_digits.txt")
    await fill_queue(wordlist)

    await filter_healthy_proxies()
    if not proxies:
        logger.error("No healthy proxies available, stopping.")
        checking = False
        return

    logger.info("Starting username checking...")

    concurrency = min(len(proxies), 40)
    workers = [asyncio.create_task(check_worker()) for _ in range(concurrency)]

    await asyncio.gather(*workers)

async def stop_checking():
    global checking, session
    checking = False
    if session and not session.closed:
        await session.close()
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
    global proxies, session
    if not session or session.closed:
        session = aiohttp.ClientSession()
    proxies = await fetch_proxies()
    await set_webhook()
    logger.info(f"Loaded {len(proxies)} proxies and set
