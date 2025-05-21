import os
import asyncio
import aiohttp
import random
import string
from fastapi import FastAPI, Request
from typing import List
import uvicorn

app = FastAPI()

TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("CHAT_ID")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")
BOT_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
WEBHOOK_URL = "https://checkerpy-production-a7e1.up.railway.app/webhook"

CHECKER_RUNNING = False
PROXIES = []
proxy_index = 0
available_usernames = []

def get_next_proxy():
    global proxy_index
    if not PROXIES:
        return None
    proxy = PROXIES[proxy_index]
    proxy_index = (proxy_index + 1) % len(PROXIES)
    return proxy

def generate_better_username():
    vowels = 'aeiou'
    consonants = 'bcdfghjklmnpqrstvwxyz'
    patterns = [
        lambda: random.choice(consonants) + random.choice(vowels) + random.choice(consonants) + random.choice(vowels),
        lambda: random.choice(vowels) + random.choice(consonants) + random.choice(consonants) + random.choice(vowels),
        lambda: random.choice(consonants) + random.choice(consonants) + random.choice(vowels) + random.choice(consonants),
        lambda: ''.join(random.choices(string.ascii_lowercase, k=4))
    ]
    return random.choice(patterns)()

async def fetch_webshare_proxies():
    global PROXIES
    if not WEBSHARE_API_KEY:
        return
    url = "https://proxy.webshare.io/api/proxy/list/"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    params = {"page": 1, "type": "http", "last_check": 3600}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
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
    except:
        pass

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
                return resp.status == 404
    except:
        if proxy in PROXIES:
            PROXIES.remove(proxy)
        return False

async def send_batch_alert(usernames: List[str]):
    if not usernames:
        return
    caption = "\n".join([f"<b>@{u}</b>" for u in usernames])
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"🔥 Available TikTok usernames:\n\n{caption}",
        "parse_mode": "HTML"
    }
    async with aiohttp.ClientSession() as session:
        await session.post(f"{BOT_API_URL}/sendMessage", json=data)

def save_to_file(username: str):
    with open("available.txt", "a") as f:
        f.write(username + "\n")

async def run_checker_loop():
    global CHECKER_RUNNING, available_usernames
    CHECKER_RUNNING = True
    while CHECKER_RUNNING:
        if not PROXIES:
            await fetch_webshare_proxies()
            await asyncio.sleep(5)
            continue
        username = generate_better_username()
        is_available = await check_username(username)
        if is_available:
            available_usernames.append(username)
            save_to_file(username)
            if len(available_usernames) >= 5:
                await send_batch_alert(available_usernames)
                available_usernames = []
        await asyncio.sleep(1)
    CHECKER_RUNNING = False

@app.post("/webhook")
async def telegram_webhook(request: Request):
    global CHECKER_RUNNING
    data = await request.json()
    if "message" in data:
        text = data["message"].get("text", "")
        if text == "/start":
            if not CHECKER_RUNNING:
                asyncio.create_task(run_checker_loop())
        elif text == "/stop":
            CHECKER_RUNNING = False
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "running"}

@app.on_event("startup")
async def startup_event():
    await fetch_webshare_proxies()
    async with aiohttp.ClientSession() as session:
        await session.post(f"{BOT_API_URL}/setWebhook", json={"url": WEBHOOK_URL})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
