import os
import asyncio
import aiohttp
import aiofiles
import logging
import random
import time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("tiktok-checker")
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

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
total_usernames = 0
checked_count = 0
available_count = 0

batch_size = 5000
batch_file = "wordlist_5k.txt"
last_position_file = "last_position.txt"

start_time = None

# --- Utilities ---
def generate_random_4letter():
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

async def load_wordlist(path, start_pos=0):
    async with aiofiles.open(path, mode="r") as f:
        lines = await f.readlines()
        return [line.strip() for line in lines[start_pos:] if line.strip()]

async def save_last_position(pos):
    async with aiofiles.open(last_position_file, mode="w") as f:
        await f.write(str(pos))

async def load_last_position():
    if os.path.exists(last_position_file):
        async with aiofiles.open(last_position_file, mode="r") as f:
            content = await f.read()
            return int(content) if content.isdigit() else 0
    return 0

async def fill_queue(usernames):
    global total_usernames
    total_usernames = len(usernames)
    for username in usernames:
        await username_queue.put(username)
    logger.info(f"Enqueued {len(usernames)} usernames for checking.")

async def get_proxy():
    global proxies, proxy_retries
    for _ in range(len(proxies)):
        proxy = random.choice(proxies)
        retries = proxy_retries.get(proxy, 0)
        if retries < MAX_RETRIES:
            return proxy
    # If all proxies hit max retries, wait a bit and reset retries
    await asyncio.sleep(5)
    proxy_retries.clear()
    return random.choice(proxies) if proxies else None

async def remove_bad_proxy(proxy):
    global proxies, proxy_retries
    if proxy in proxies:
        proxies.remove(proxy)
    if proxy in proxy_retries:
        del proxy_retries[proxy]
    logger.warning(f"Removed a bad proxy. Proxies left: {len(proxies)}")

async def check_username(username):
    global checked_count, available_count

    proxy = await get_proxy()
    if not proxy:
        logger.warning("No proxies available.")
        return

    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
                      " Chrome/114.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, proxy=proxy, headers=headers, timeout=10) as res:
                status = res.status
                text = await res.text()

                logger.debug(f"Checked @{username} | Status: {status} | Proxy: {proxy}")

                if status == 404:
                    available_count += 1
                    await send_telegram_message(f"Available: @{username}")
                elif status in (429, 403):
                    # Proxy likely banned, remove it
                    proxy_retries[proxy] = MAX_RETRIES
                    await remove_bad_proxy(proxy)
                elif status == 200:
                    # TikTok page might be taken, fallback check content for hints
                    if "Sorry, this page isn't available." in text or "User not found" in text:
                        available_count += 1
                        await send_telegram_message(f"Available (fallback): @{username}")
                # else assume taken or unknown status
    except Exception as e:
        logger.warning(f"Proxy error {proxy}: {e}")
        proxy_retries[proxy] = proxy_retries.get(proxy, 0) + 1
        if proxy_retries[proxy] >= MAX_RETRIES:
            await remove_bad_proxy(proxy)

    checked_count += 1

async def check_worker():
    global checking
    while checking:
        if username_queue.empty():
            # No usernames to check, wait and refill queue
            await asyncio.sleep(2)
            continue

        username = await username_queue.get()
        await check_username(username)
        await save_last_position(checked_count)
        await asyncio.sleep(0)  # yield control

async def replenish_wordlist():
    # Generate fresh 5k batch, replace file contents
    letters = 'abcdefghijklmnopqrstuvwxyz'
    digits = '0123456789'
    new_usernames = []
    while len(new_usernames) < batch_size:
        first = random.choice(letters)
        rest = ''.join(random.choice(letters + digits) for _ in range(3))
        new_usernames.append(first + rest)

    async with aiofiles.open(batch_file, mode="w") as f:
        await f.write("\n".join(new_usernames))

    logger.info(f"Replenished wordlist file with fresh {batch_size} usernames.")

async def monitor_progress():
    global checked_count, total_usernames, available_count, checking, start_time

    last_checked = 0
    while checking:
        elapsed = time.time() - start_time if start_time else 0
        speed = (checked_count - last_checked) / 10 if elapsed > 0 else 0  # per 10 seconds
        last_checked = checked_count

        eta = (total_usernames - checked_count) / speed if speed > 0 else float('inf')

        proxy_health_pct = (len(proxies) / 100) * 100  # Assuming starting proxies = 100

        log_msg = (f"Progress: {checked_count}/{total_usernames} checked | "
                   f"Available found: {available_count} | "
                   f"Speed: {speed:.1f} usernames/10s | "
                   f"ETA: {eta/60:.1f} minutes | "
                   f"Proxy health: {proxy_health_pct:.1f}%")

        logger.info(log_msg)
        await asyncio.sleep(10)

async def start_checking():
    global checking, proxies, start_time, checked_count, total_usernames, available_count

    if checking:
        logger.info("Already checking.")
        return

    # Load proxies
    proxies = await fetch_proxies()
    logger.info(f"Loaded {len(proxies)} proxies.")

    # If wordlist file does not exist or too small, replenish
    if not os.path.exists(batch_file) or sum(1 for _ in open(batch_file)) < batch_size:
        await replenish_wordlist()

    # Load last position to resume
    start_pos = await load_last_position()
    logger.info(f"Resuming from position {start_pos}.")

    # Load usernames from file starting at last position
    usernames = await load_wordlist(batch_file, start_pos=start_pos)
    if not usernames:
        logger.info("No usernames left to check, replenishing wordlist.")
        await replenish_wordlist()
        usernames = await load_wordlist(batch_file)

    # Reset counters
    checked_count = start_pos
    total_usernames = len(usernames) + start_pos
    available_count = 0

    # Fill queue
    await fill_queue(usernames)

    checking = True
    start_time = time.time()

    # Start progress monitor
    asyncio.create_task(monitor_progress())

    # Start workers
    concurrency = min(len(proxies), 40)
    workers = [asyncio.create_task(check_worker()) for _ in range(concurrency)]
    logger.info(f"Started {concurrency} workers.")

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
        asyncio.create_task(start_checking
