import os
import asyncio
import aiohttp
import random
import string
from fastapi import FastAPI, Request
import uvicorn
import time

app = FastAPI()

# --- Config from environment variables ---
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("CHAT_ID")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")
BOT_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
WEBHOOK_URL = "https://checkerpy-production-a7e1.up.railway.app/webhook"

# --- State ---
CHECKER_RUNNING = False
PROXIES = []
proxy_state = {}  # proxy -> {'fail_count': int, 'last_used': float}

# Configurable parameters
MIN_REQUEST_INTERVAL = 2  # seconds before reusing the same proxy
MAX_FAILS = 3             # max fails before removing proxy

def get_ready_proxies():
    now = asyncio.get_event_loop().time()
    ready = []
    for proxy in PROXIES:
        state = proxy_state.get(proxy, {'fail_count': 0, 'last_used': 0})
        if (now - state['last_used'] >= MIN_REQUEST_INTERVAL) and (state['fail_count'] < MAX_FAILS):
            ready.append(proxy)
    return ready

def get_next_proxy():
    ready_proxies = get_ready_proxies()
    if not ready_proxies:
        # Reset fail counts for proxies with enough cooldown to avoid deadlock
        now = asyncio.get_event_loop().time()
        for proxy in PROXIES:
            state = proxy_state.setdefault(proxy, {'fail_count': 0, 'last_used': 0})
            if now - state['last_used'] > MIN_REQUEST_INTERVAL * 5:
                state['fail_count'] = 0
        ready_proxies = get_ready_proxies()
        if not ready_proxies:
            # Pick any proxy to keep going if still none ready
            if PROXIES:
                return random.choice(PROXIES)
            else:
                return None
    return random.choice(ready_proxies)

async def fetch_webshare_proxies():
    global PROXIES, proxy_state
    if not WEBSHARE_API_KEY:
        print("❌ WEBSHARE_API_KEY not set in environment!")
        return

    url = "https://proxy.webshare.io/api/proxy/list/"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    params = {
        "page": 1,
        "type": "http",
        "last_check": 3600
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    print(f"❌ Failed to fetch proxies: HTTP {resp.status}")
                    text = await resp.text()
                    print("Response text:", text)
                    return
                data = await resp.json()
                proxies = []
                for proxy in data.get("results", []):
                    if proxy.get("username") and proxy.get("password"):
                        p = f"http://{proxy['username']}:{proxy['password']}@{proxy['proxy_address']}:{proxy['ports']['http']}"
                    else:
                        p = f"http://{proxy['proxy_address']}:{proxy['ports']['http']}"
                    proxies.append(p)
                PROXIES = proxies
                # Reset proxy_state for new proxies
                proxy_state = {p: {'fail_count': 0, 'last_used': 0} for p in PROXIES}
                print(f"🌀 Fetched {len(PROXIES)} proxies from Webshare")
                if len(PROXIES) == 0:
                    print("⚠️ No proxies available from Webshare response.")
    except Exception as e:
        print(f"❌ Exception during proxy fetch: {e}")

def generate_username(length=4):
    return ''.join(random.choices(string.ascii_lowercase, k=length))

async def send_message(text):
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    async with aiohttp.ClientSession() as session:
        await session.post(f"{BOT_API_URL}/sendMessage", json=data)

async def check_username(username, retry=True):
    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; WOW64) Gecko/20100101 Firefox/115.0"
        ]),
        "Accept-Language": "en-US,en;q=0.9"
    }

    proxy = get_next_proxy()
    if proxy is None:
        print("⚠️ No proxies available to check username.")
        return False

    proxy_state.setdefault(proxy, {'fail_count': 0, 'last_used': 0})
    proxy_state[proxy]['last_used'] = asyncio.get_event_loop().time()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, proxy=proxy, allow_redirects=False, timeout=10) as resp:
                print(f"🔍 {username} → HTTP {resp.status} | Proxy: {proxy}")

                if resp.status == 404:
                    print(f"✅ Available: {username}")
                    proxy_state[proxy]['fail_count'] = 0
                    return True
                elif resp.status == 200:
                    print(f"❌ Taken: {username}")
                    proxy_state[proxy]['fail_count'] = 0
                    return False
                elif resp.status in [301, 302]:
                    print(f"⚠️ Redirected (likely blocked) — HTTP {resp.status} on proxy {proxy}")
                    proxy_state[proxy]['fail_count'] += 1
                    if proxy_state[proxy]['fail_count'] >= MAX_FAILS:
                        if proxy in PROXIES:
                            PROXIES.remove(proxy)
                            proxy_state.pop(proxy, None)
                            print(f"⚠️ Removed proxy due to redirects: {proxy}. {len(PROXIES)} proxies left.")
                    if retry:
                        print(f"⏳ Waiting 5 seconds before retrying username {username} with new proxy...")
                        await asyncio.sleep(5)
                        return await check_username(username, retry=False)
                    return False
                else:
                    print(f"⚠️ Unknown response for {username}: HTTP {resp.status}")
                    proxy_state[proxy]['fail_count'] += 1
                    if proxy_state[proxy]['fail_count'] >= MAX_FAILS:
                        if proxy in PROXIES:
                            PROXIES.remove(proxy)
                            proxy_state.pop(proxy, None)
                            print(f"⚠️ Removed proxy due to unknown response: {proxy}. {len(PROXIES)} proxies left.")
                    return False

    except Exception as e:
        print(f"❌ Proxy error on {proxy}: {e}")
        proxy_state[proxy]['fail_count'] += 1
        if proxy_state[proxy]['fail_count'] >= MAX_FAILS:
            if proxy in PROXIES:
                PROXIES.remove(proxy)
                proxy_state.pop(proxy, None)
                print(f"⚠️ Removed proxy due to errors: {proxy}. {len(PROXIES)} proxies left.")
        return False

async def run_checker_loop():
    global CHECKER_RUNNING
    CHECKER_RUNNING = True
    print("✅ Checker started")

    while CHECKER_RUNNING:
        if not PROXIES:
            print("⚠️ Proxy list empty, fetching new proxies...")
            await fetch_webshare_proxies()
            if not PROXIES:
                print("❌ Still no proxies available, sleeping 30 seconds before retry...")
                await asyncio.sleep(30)
                continue

        username = generate_username()
        print(f"🔍 Checking username: {username}")

        available = await check_username(username)
        if available:
            print(f"🎯 Sending alert: {username} is available")
            await send_message(f"Username <b>@{username}</b> is available!")
        else:
            print(f"⛔ {username} is taken or check failed")

        await asyncio.sleep(random.uniform(0.7, 1.3))

    CHECKER_RUNNING = False
    print("🛑 Checker stopped")

@app.post("/webhook")
async def webhook(request: Request):
    global CHECKER_RUNNING
    data = await request.json()
    print(f"📩 Received update: {data}")

    if "message" in data:
        message = data["message"]
        text = message.get("text", "")

        if text == "/start":
            if not CHECKER_RUNNING:
                await send_message("⚙️ Checker is starting...")
               
