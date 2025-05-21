import os
import asyncio
import aiohttp
import random
import string
import time
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
proxy_index = 0

PROXY_REFRESH_INTERVAL = 15 * 60  # 15 minutes in seconds

def get_next_proxy():
    global proxy_index
    if not PROXIES:
        return None
    proxy = PROXIES[proxy_index]
    proxy_index = (proxy_index + 1) % len(PROXIES)
    return proxy

async def fetch_webshare_proxies():
    global PROXIES
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

async def check_username(username):
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
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, proxy=proxy, allow_redirects=False, timeout=10) as resp:
                print(f"🔍 {username} → HTTP {resp.status} | Proxy: {proxy}")

                if resp.status == 404:
                    print(f"✅ Available: {username}")
                    return True
                elif resp.status == 200:
                    print(f"❌ Taken: {username}")
                    return False
                elif resp.status in [301, 302]:
                    print(f"⚠️ Redirected (likely blocked by TikTok) — HTTP {resp.status}")
                else:
                    print(f"⚠️ Unknown response for {username}: HTTP {resp.status}")
                return False

    except Exception as e:
        print(f"❌ Proxy error on {proxy}: {e}")
        if proxy in PROXIES:
            PROXIES.remove(proxy)
            print(f"⚠️ Removed bad proxy: {proxy}. {len(PROXIES)} proxies left.")
        return False

async def run_checker_loop():
    global CHECKER_RUNNING
    CHECKER_RUNNING = True
    print("✅ Checker started")

    last_proxy_refresh = time.time()

    while CHECKER_RUNNING:
        # Refresh proxies every 15 minutes or if fewer than 20 proxies remain
        if time.time() - last_proxy_refresh > PROXY_REFRESH_INTERVAL or len(PROXIES) < 20:
            print("🌀 Refreshing proxies...")
            await fetch_webshare_proxies()
            last_proxy_refresh = time.time()
            if not PROXIES:
                print("❌ No proxies after refresh, sleeping 30 seconds...")
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

        await asyncio.sleep(1)  # moderate delay, not too fast

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
                asyncio.create_task(run_checker_loop())
            else:
                print("⚠️ Checker already running, ignoring /start command.")

        elif text == "/stop":
            if CHECKER_RUNNING:
                CHECKER_RUNNING = False
                await send_message("🛑 Checker stopped.")
            else:
                print("⚠️ Checker not running, ignoring /stop command.")

    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "running"}

async def test_proxy(proxy):
    test_url = "https://httpbin.org/ip"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(test_url, proxy=proxy, timeout=10) as resp:
                print(f"✅ Proxy working: {await resp.text()}")
    except Exception as e:
        print(f"❌ Proxy failed: {proxy} - {e}")

@app.on_event("startup")
async def startup_event():
    print(f"Using Webshare API key (start): {WEBSHARE_API_KEY[:5]}...")
    await fetch_webshare_proxies()
    if PROXIES:
        await test_proxy(PROXIES[0])

    async with aiohttp.ClientSession() as session:
        set_url = f"{BOT_API_URL}/setWebhook"
        set_resp = await session.post(set_url, json={"url": WEBHOOK_URL})
        print("🔗 Set webhook response:", await set_resp.json())

        info_url = f"{BOT_API_URL}/getWebhookInfo"
        info_resp = await session.get(info_url)
        info_data = await info_resp.json()
        print("ℹ️ Current webhook info:", info_data)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Starting server on port: {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
