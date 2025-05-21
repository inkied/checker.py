import os
import asyncio
import aiohttp
import random
import string
from fastapi import FastAPI, Request
import uvicorn

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

# --- Config ---
MIN_REQUEST_INTERVAL = 2
MAX_FAILS = 3

def get_ready_proxies():
    now = asyncio.get_event_loop().time()
    return [p for p in PROXIES if (now - proxy_state[p]['last_used'] >= MIN_REQUEST_INTERVAL and proxy_state[p]['fail_count'] < MAX_FAILS)]

def get_next_proxy():
    ready = get_ready_proxies()
    if not ready:
        now = asyncio.get_event_loop().time()
        for proxy in PROXIES:
            state = proxy_state[proxy]
            if now - state['last_used'] > MIN_REQUEST_INTERVAL * 5:
                state['fail_count'] = 0
        ready = get_ready_proxies()
        if not ready and PROXIES:
            return random.choice(PROXIES)
        return None
    return random.choice(ready)

async def fetch_webshare_proxies():
    global PROXIES, proxy_state
    if not WEBSHARE_API_KEY:
        print("❌ WEBSHARE_API_KEY not set.")
        return

    url = "https://proxy.webshare.io/api/proxy/list/"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    params = {"page": 1, "type": "http", "last_check": 3600}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    print("❌ Proxy fetch failed:", resp.status)
                    return
                data = await resp.json()
                proxies = []
                for proxy in data.get("results", []):
                    p = f"http://{proxy['username']}:{proxy['password']}@{proxy['proxy_address']}:{proxy['ports']['http']}" \
                        if proxy.get("username") else f"http://{proxy['proxy_address']}:{proxy['ports']['http']}"
                    proxies.append(p)
                PROXIES = proxies
                proxy_state = {p: {'fail_count': 0, 'last_used': 0} for p in PROXIES}
                print(f"✅ Loaded {len(PROXIES)} proxies")
    except Exception as e:
        print(f"❌ Error fetching proxies: {e}")

# --- Upgraded username generator with brandable + semi-OG patterns ---
vowels = "aeiou"
consonants = "bcdfghjklmnpqrstvwxyz"

brandable_prefixes = [
    "kur", "lok", "ruk", "vak", "tik", "zik", "buk", "cak", "dok", "fik",
    "lak", "mok", "nak", "pak", "rak", "sak", "tak", "vak", "wak", "yuk"
]

brandable_suffixes = [
    "y", "i", "o", "u", "a", "e"
]

semi_og_patterns = [
    lambda: random.choice(consonants) + random.choice(vowels) + random.choice(consonants) + random.choice(vowels),
    lambda: random.choice(consonants) + random.choice(consonants) + random.choice(vowels) + random.choice(consonants),
    lambda: random.choice(consonants) + random.choice(vowels) + random.choice(vowels) + random.choice(consonants),
    lambda: random.choice(consonants) + random.choice(vowels) + random.choice(consonants) + random.choice(consonants),
    lambda: random.choice(consonants) * 2 + random.choice(vowels) + random.choice(consonants),
]

def generate_username():
    choice = random.choices(
        ["brandable", "semi_og", "random"], weights=[0.4, 0.4, 0.2], k=1
    )[0]

    if choice == "brandable":
        prefix = random.choice(brandable_prefixes)
        suffix = random.choice(brandable_suffixes)
        username = (prefix + suffix)[:4]
        return username

    elif choice == "semi_og":
        username = random.choice(semi_og_patterns)()
        return username

    else:
        letters = consonants + vowels
        return ''.join(random.choices(letters, k=4))

async def send_message(text):
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    async with aiohttp.ClientSession() as session:
        await session.post(f"{BOT_API_URL}/sendMessage", json=data)

async def check_username(username, retry=True):
    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64)...",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X)...",
            "Mozilla/5.0 (Windows NT 10.0; WOW64)..."
        ]),
        "Accept-Language": "en-US,en;q=0.9"
    }

    proxy = get_next_proxy()
    if not proxy:
        print("⚠️ No usable proxies")
        return False

    proxy_state[proxy]['last_used'] = asyncio.get_event_loop().time()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, proxy=proxy, allow_redirects=False, timeout=10) as resp:
                status = resp.status
                print(f"🔍 {username} → HTTP {status}")

                if status == 404:
                    proxy_state[proxy]['fail_count'] = 0
                    return True
                elif status == 200:
                    proxy_state[proxy]['fail_count'] = 0
                    return False
                elif status in (301, 302):
                    proxy_state[proxy]['fail_count'] += 1
                else:
                    proxy_state[proxy]['fail_count'] += 1

    except Exception as e:
        print(f"❌ Proxy error: {proxy} | {e}")
        proxy_state[proxy]['fail_count'] += 1

    if proxy_state[proxy]['fail_count'] >= MAX_FAILS:
        if proxy in PROXIES:
            PROXIES.remove(proxy)
            proxy_state.pop(proxy)
            print(f"❌ Removed bad proxy: {proxy}")

    if retry:
        await asyncio.sleep(5)
        return await check_username(username, retry=False)

    return False

async def run_checker_loop():
    global CHECKER_RUNNING
    CHECKER_RUNNING = True
    await send_message("✅ Checker started")

    while CHECKER_RUNNING:
        if not PROXIES:
            await send_message("⚠️ No proxies, trying to reload...")
            await fetch_webshare_proxies()
            await asyncio.sleep(5)
            continue

        username = generate_username()
        available = await check_username(username)
        if available:
            await send_message(f"🎯 Available: <b>@{username}</b>")
        await asyncio.sleep(random.uniform(0.7, 1.3))

    await send_message("🛑 Checker stopped")

# --- Telegram Webhook ---
@app.post("/webhook")
async def webhook(request: Request):
    global CHECKER_RUNNING
    data = await request.json()
    print("📩 Webhook received:", data)

    if "message" in data:
        text = data["message"].get("text", "")
        if text == "/start":
            if not CHECKER_RUNNING:
                asyncio.create_task(run_checker_loop())
            else:
                await send_message("🔁 Already running.")
        elif text == "/stop":
            CHECKER_RUNNING = False
            await send_message("⛔ Checker stopped.")
        else:
            await send_message("❓ Use /start or /stop")

    return {"ok": True}

@app.on_event("startup")
async def startup():
    await fetch_webshare_proxies()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
