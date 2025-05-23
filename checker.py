import os
import sys
import asyncio
import aiohttp
import random
from collections import deque
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")

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
    exit_with_error("TELEGRAM_CHAT_ID must be an integer")

telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

app = FastAPI()

aiohttp_session = None
proxies = deque()
proxies_lock = asyncio.Lock()
usernames_queue = asyncio.Queue()
checking = False
user_agents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.1 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Mobile Safari/537.36",
]

def generate_pronounceable_username(length=4):
    consonants = "bcdfghjklmnpqrstvwxyz"
    vowels = "aeiou"
    # Alternate consonant and vowel for pronounceability
    username = ''.join([consonants[i % 2] if i % 2 == 0 else random.choice(vowels) for i in range(length)])
    return username

@app.on_event("startup")
async def startup_event():
    global aiohttp_session
    aiohttp_session = aiohttp.ClientSession()
    await refresh_proxies()

@app.on_event("shutdown")
async def shutdown_event():
    global aiohttp_session
    if aiohttp_session:
        await aiohttp_session.close()

async def scrape_proxies():
    global aiohttp_session
    url = "https://proxy.webshare.io/api/proxy/list/?page=1&page_size=100"
    headers = {
        "Authorization": f"Bearer {WEBSHARE_API_KEY}"
    }
    proxies_list = []
    try:
        async with aiohttp_session.get(url, headers=headers, timeout=15) as resp:
            if resp.status == 200:
                data = await resp.json()
                for item in data.get("results", []):
                    proxy = item.get("proxy_address")
                    port = item.get("port")
                    username = item.get("username")
                    password = item.get("password")
                    protocol = item.get("type", "http").lower()
                    if username and password:
                        proxy_url = f"{protocol}://{username}:{password}@{proxy}:{port}"
                    else:
                        proxy_url = f"{protocol}://{proxy}:{port}"
                    proxies_list.append(proxy_url)
            else:
                print(f"Failed to scrape proxies, status {resp.status}")
    except Exception as e:
        print(f"Exception scraping proxies: {e}")
    return proxies_list

async def validate_proxy(proxy_url):
    test_urls = [
        ("http", "http://httpbin.org/ip"),
        ("https", "https://httpbin.org/ip"),
    ]
    timeout = aiohttp.ClientTimeout(total=10)
    for protocol, test_url in test_urls:
        try:
            async with aiohttp_session.get(test_url, proxy=proxy_url, timeout=timeout) as resp:
                if resp.status == 200:
                    return proxy_url
        except:
            continue
    return None

async def refresh_proxies():
    global proxies
    async with proxies_lock:
        raw_proxies = await scrape_proxies()
        validated = []
        for p in raw_proxies:
            valid = await validate_proxy(p)
            if valid:
                validated.append(valid)
            await asyncio.sleep(0.2)
        proxies = deque(validated)
        print(f"Refreshed proxies. Total working proxies: {len(proxies)}")

async def check_username(username, proxy=None):
    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.tiktok.com/",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
        "Upgrade-Insecure-Requests": "1",
    }
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp_session.get(url, headers=headers, proxy=proxy, timeout=timeout) as resp:
            if resp.status == 404:
                return True
            if resp.status == 200:
                return False
            return None
    except Exception:
        return None

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

async def username_worker():
    global checking
    while checking:
        try:
            username = await asyncio.wait_for(usernames_queue.get(), timeout=3)
        except asyncio.TimeoutError:
            break

        async with proxies_lock:
            if not proxies:
                await send_telegram_message("⚠️ Proxy list empty, refreshing...")
                await refresh_proxies()
            proxy = proxies[0]
            proxies.rotate(-1)

        result = await check_username(username, proxy=proxy)
        if result is True:
            await send_telegram_message(f"✅ Username available: *{username}*")
            print(f"[AVAILABLE] {username}")
        elif result is False:
            print(f"[TAKEN] {username}")
        else:
            print(f"[ERROR] Checking {username} failed, retrying with different proxy")
            retry_success = False
            for _ in range(3):
                async with proxies_lock:
                    if not proxies:
                        await refresh_proxies()
                    proxy = proxies[0]
                    proxies.rotate(-1)
                result_retry = await check_username(username, proxy=proxy)
                if result_retry is not None:
                    retry_success = True
                    if result_retry:
                        await send_telegram_message(f"✅ Username available (retry): *{username}*")
                        print(f"[AVAILABLE RETRY] {username}")
                    else:
                        print(f"[TAKEN RETRY] {username}")
                    break
                await asyncio.sleep(1)
            if not retry_success:
                print(f"[FAILED] {username} could not be checked after retries")
        usernames_queue.task_done()
        await asyncio.sleep(random.uniform(0.5, 1.0))

async def fill_username_queue(count=50):
    for _ in range(count):
        uname = generate_pronounceable_username()
        await usernames_queue.put(uname)

@app.post("/webhook")
async def telegram_webhook(request: Request):
    global checking
    update = await request.json()
    message = update.get("message", {})
    text = message.get("text", "").strip()
    chat_id = message.get("chat", {}).get("id")

    if chat_id != TELEGRAM_CHAT_ID:
        return JSONResponse({"status": "ignored"})

    if text.startswith("/start"):
        if checking:
            await send_telegram_message("⚠️ Already checking usernames.")
        else:
            checking = True
            await fill_username_queue(100)
            asyncio.create_task(username_worker())
            await send_telegram_message("▶️ Started checking usernames.")
    elif text.startswith("/stop"):
        checking = False
        await send_telegram_message("⏸️ Stopped checking usernames.")
    elif text.startswith("/proxies"):
        async with proxies_lock:
            await send_telegram_message(f"🔍 {len(proxies)} working proxies loaded.")
    else:
        await send_telegram_message("❓ Unknown command. Use /start, /stop, or /proxies.")

    return JSONResponse({"status": "ok"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("tiktok_checker:app", host="0.0.0.0", port=8000, log_level="info")
