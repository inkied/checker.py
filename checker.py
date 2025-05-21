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
BOT_API_URL = f"https://api.telegram.org/bot7527264620:AAGG5qpYqV3o0h0NidwmsTOKxqVsmRIaX1A"
WEBHOOK_URL = "https://checkerpy-production-a7e1.up.railway.app/webhook"

# --- State ---
CHECKER_RUNNING = False
PROXIES = []
proxy_index = 0

def get_next_proxy():
    global proxy_index
    if not PROXIES:
        return None
    proxy = PROXIES[proxy_index]
    proxy_index = (proxy_index + 1) % len(PROXIES)
    return proxy

async def fetch_webshare_proxies():
    global PROXIES
    url = "https://proxy.webshare.io/api/proxy/list/"
    headers = {
        "Authorization": f"Token {WEBSHARE_API_KEY}"
    }
    params = {
        "page": 1,
        "type": "http",
        "last_check": 3600
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as resp:
            data = await resp.json()
            proxies = []
            for proxy in data.get("results", []):
                if proxy.get("username") and proxy.get("password"):
                    p = f"http://{proxy['username']}:{proxy['password']}@{proxy['proxy_address']}:{proxy['ports']['http']}"
                else:
                    p = f"http://{proxy['proxy_address']}:{proxy['ports']['http']}"
                proxies.append(p)
            PROXIES = proxies
            print(f"Fetched {len(PROXIES)} proxies from Webshare")

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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/114.0.0.0 Safari/537.36"
    }
    proxy = get_next_proxy()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, proxy=proxy, allow_redirects=False, timeout=10) as resp:
                # 404 means username available, 200 means taken
                if resp.status == 404:
                    return True
                else:
                    return False
    except Exception as e:
        print(f"Proxy error on {proxy}: {e}")
        if proxy in PROXIES:
            PROXIES.remove(proxy)
        return False

async def run_checker_loop():
    global CHECKER_RUNNING
    CHECKER_RUNNING = True
    print("Checker started")

    while CHECKER_RUNNING:
        username = generate_username()
        print(f"Checking username: {username}")

        available = await check_username(username)
        if available:
            await send_message(f"Username <b>@{username}</b> is available!")

        await asyncio.sleep(1)

    CHECKER_RUNNING = False
    print("Checker stopped")

@app.post("/webhook")
async def webhook(request: Request):
    global CHECKER_RUNNING
    data = await request.json()
    print(f"Received update: {data}")

    if "message" in data:
        message = data["message"]
        text = message.get("text", "")

        if text == "/start":
            if not CHECKER_RUNNING:
                await send_message("Checker is starting...")
                asyncio.create_task(run_checker_loop())
            else:
                print("Checker already running, ignoring /start command.")

        elif text == "/stop":
            if CHECKER_RUNNING:
                CHECKER_RUNNING = False
                await send_message("Checker stopped.")
            else:
                print("Checker not running, ignoring /stop command.")

    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "running"}

@app.on_event("startup")
async def startup_event():
    await fetch_webshare_proxies()
    async with aiohttp.ClientSession() as session:
        set_url = f"{BOT_API_URL}/setWebhook"
        set_resp = await session.post(set_url, json={"url": WEBHOOK_URL})
        print("Set webhook response:", await set_resp.json())

        info_url = f"{BOT_API_URL}/getWebhookInfo"
        info_resp = await session.get(info_url)
        info_data = await info_resp.json()
        print("Current webhook info:", info_data)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting server on port: {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
