import os
import sys
import asyncio
import aiohttp
import random
import time
from collections import deque
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://yourdomain.com/webhook")

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID or not WEBSHARE_API_KEY:
    print("Missing required environment variables.")
    sys.exit(1)

try:
    TELEGRAM_CHAT_ID = int(TELEGRAM_CHAT_ID)
except Exception:
    print("TELEGRAM_CHAT_ID must be an integer.")
    sys.exit(1)

telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

app = FastAPI()

# Globals
aiohttp_session = None
proxies = deque()
proxy_status = {}  # {proxy_url: {"working": bool, "last_checked": datetime, "type": str, "fail_count": int}}
banned_proxies = set()
user_agents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/16.0 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 13; Pixel 6) AppleWebKit/537.36 Chrome/114.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_4 like Mac OS X) AppleWebKit/605.1.15 Version/16.4 Mobile/15E148 Safari/604.1",
]

username_queue = asyncio.Queue()
checking_tasks = set()
current_usernames = set()
checking_active = False

MAX_RETRIES_PER_PROXY = 3
MAX_FAILS_BEFORE_BAN = 5

TELEGRAM_BATCH_SIZE = 5
TELEGRAM_BATCH_DELAY = 2  # seconds

# Proxy protocol detection
async def detect_proxy_protocol(proxy_url: str) -> str:
    test_url = "http://httpbin.org/ip"
    for proto in ['http', 'socks4', 'socks5']:
        url = f"{proto}://{proxy_url}" if not proxy_url.startswith(("http://", "socks4://", "socks5://")) else proxy_url
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(test_url, proxy=url) as resp:
                    if resp.status == 200:
                        return proto
        except:
            continue
    return "http"

# Scrape proxies from Webshare
async def scrape_proxies():
    global proxies, proxy_status, banned_proxies
    new_proxies = deque()
    proxy_status = {}
    banned_proxies = set()
    headers = {"Authorization": f"Bearer {WEBSHARE_API_KEY}"}
    url = "https://proxy.webshare.io/api/proxy/list/?page=1&page_size=100"
    try:
        async with aiohttp_session.get(url, headers=headers, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                for item in data.get("results", []):
                    addr = item.get("proxy_address")
                    port = item.get("port")
                    user = item.get("username")
                    pwd = item.get("password")
                    proxy_str = f"{user}:{pwd}@{addr}:{port}" if user and pwd else f"{addr}:{port}"
                    protocol = await detect_proxy_protocol(proxy_str)
                    full_proxy = f"{protocol}://{proxy_str}"
                    proxy_status[full_proxy] = {"working": True, "last_checked": None, "type": protocol, "fail_count": 0}
                    new_proxies.append(full_proxy)
            else:
                print(f"Failed to scrape proxies: HTTP {resp.status}")
    except Exception as e:
        print(f"Exception scraping proxies: {e}")
    proxies = new_proxies
    print(f"[PROXY] Loaded {len(proxies)} proxies.")
    return proxies

# Validate proxy by testing connectivity
async def validate_proxy(proxy_url: str) -> bool:
    test_urls = ["http://httpbin.org/ip", "https://httpbin.org/ip"]
    timeout = aiohttp.ClientTimeout(total=7)
    for url in test_urls:
        try:
            async with aiohttp_session.get(url, proxy=proxy_url, timeout=timeout) as resp:
                if resp.status == 200:
                    return True
        except:
            continue
    return False

async def get_healthy_proxy():
    global proxies, proxy_status, banned_proxies
    for _ in range(len(proxies)):
        proxy = proxies[0]
        proxies.rotate(-1)
        status = proxy_status.get(proxy, {})
        if status.get('working', True) and proxy not in banned_proxies:
            return proxy
    return None

async def report_proxy_failure(proxy: str):
    global proxy_status, banned_proxies
    if proxy not in proxy_status:
        return
    proxy_status[proxy]['fail_count'] += 1
    if proxy_status[proxy]['fail_count'] >= MAX_FAILS_BEFORE_BAN:
        banned_proxies.add(proxy)
        proxy_status[proxy]['working'] = False
        print(f"[PROXY] Banned proxy {proxy} after too many failures.")

async def report_proxy_success(proxy: str):
    global proxy_status
    if proxy in proxy_status:
        proxy_status[proxy]['fail_count'] = 0
        proxy_status[proxy]['working'] = True

# Check TikTok username availability
async def check_username(username: str, proxy: str):
    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.tiktok.com/",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp_session.get(url, headers=headers, proxy=proxy, timeout=timeout) as resp:
            if resp.status == 404:
                await report_proxy_success(proxy)
                return True  # available
            elif resp.status == 200:
                await report_proxy_success(proxy)
                return False  # taken
            elif resp.status == 429:
                await report_proxy_failure(proxy)
                return None
            else:
                await report_proxy_failure(proxy)
                return None
    except Exception:
        await report_proxy_failure(proxy)
        return None

# Pronounceable/semi-OG username generator
consonants = "bcdfghjklmnpqrstvwxyz"
vowels = "aeiou"
def generate_semi_og_username(length=4):
    username = ""
    for i in range(length):
        username += consonants[random.randint(0, len(consonants)-1)] if i % 2 == 0 else vowels[random.randint(0, len(vowels)-1)]
    return username

# Username worker task
async def username_worker():
    global checking_active
    while checking_active:
        username = await username_queue.get()
        proxy = await get_healthy_proxy()
        if proxy is None:
            print("[CHECKER] No healthy proxies available, waiting...")
            await asyncio.sleep(10)
            username_queue.put_nowait(username)  # Re-queue username
            continue

        available = await check_username(username, proxy)
        if available is True:
            print(f"[AVAILABLE] {username}")
            await send_telegram_message(f"✅ Username available: @{username}\nClaim now!")
        elif available is False:
            print(f"[TAKEN] {username}")
        else:
            # Unknown, retry once more later
            username_queue.put_nowait(username)

        username_queue.task_done()
        await asyncio.sleep(random.uniform(0.3, 1.0))  # slight delay for stealth

# Telegram send message helper
async def send_telegram_message(text: str):
    async with aiohttp_session.post(f"{telegram_api_url}/sendMessage", json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }) as resp:
        return await resp.json()

# Telegram commands handlers
@app.post("/webhook")
async def telegram_webhook(req: Request):
    data = await req.json()
    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "").strip().lower()
        if chat_id != TELEGRAM_CHAT_ID:
            return JSONResponse({"ok": True})  # Ignore unauthorized chats

        global checking_active

        if text == "/start":
            if not checking_active:
                checking_active = True
                asyncio.create_task(start_checking())
                await send_telegram_message("✅ Checker started.")
            else:
                await send_telegram_message("⚠️ Checker already running.")
        elif text == "/stop":
            checking_active = False
            await send_telegram_message("🛑 Checker stopped.")
        elif text == "/proxies":
            await send_proxies_status()
        elif text == "/usernames":
            await send_usernames_status()
        elif text == "/refreshproxies":
            await scrape_proxies()
            await send_telegram_message("♻️ Proxies refreshed.")
        else:
            await send_telegram_message("Commands:\n/start\n/stop\n/proxies\n/usernames\n/refreshproxies")

    return JSONResponse({"ok": True})

async def send_proxies_status():
    total = len(proxies)
    working = sum(1 for p in proxies if proxy_status.get(p, {}).get("working", False))
    banned = len(banned_proxies)
    msg = f"📡 Proxy status:\nTotal: {total}\nWorking: {working}\nBanned: {banned}"
    await send_telegram_message(msg)

async def send_usernames_status():
    queued = username_queue.qsize()
    msg = f"🔎 Username check queue size: {queued}"
    await send_telegram_message(msg)

# Start username checking - generates some usernames and enqueues them
async def start_checking():
    global checking_active
    # Seed with some semi-OG usernames + generated
    semi_og_seeds = ["tsla", "kurv", "curv", "stak", "lcky", "loky"]
    for name in semi_og_seeds:
        await username_queue.put(name)

    # Add generated usernames forever while active
    while checking_active:
        name = generate_semi_og_username()
        if name not in current_usernames:
            current_usernames.add(name)
            await username_queue.put(name)
        await asyncio.sleep(0.1)

# Startup and shutdown events
@app.on_event("startup")
async def startup_event():
    global aiohttp_session
    aiohttp_session = aiohttp.ClientSession()
    await scrape_proxies()

@app.on_event("shutdown")
async def shutdown_event():
    await aiohttp_session.close()

# Run with `uvicorn checker:app --host 0.0.0.0 --port 8000`
