import asyncio
import aiohttp
import random
import json
from fastapi import FastAPI, Request, HTTPException
import uvicorn

app = FastAPI()

# === CONFIGURATION ===
TELEGRAM_TOKEN = "7527264620:AAGG5qpYqV3o0h0NidwmsTOKxqVsmRIaX1A"
TELEGRAM_CHAT_ID = "7755395640"
BOT_API_URL = f"https://api.telegram.org/bot7527264620:AAGG5qpYqV3o0h0NidwmsTOKxqVsmRIaX1A"
PROXIES_FILE = "proxies.txt"

CHECKER_RUNNING = False
PROXIES = []

USERNAME_LIST = [
    "tsla", "kurv", "loco", "vibe", "zest", "flux", "nova", "drip",
    "glow", "kick", "loop", "muse", "nook", "perk", "quip", "rave",
    "sync", "twix", "viva", "wisp", "yolo", "zeno", "blox", "crux",
    "dusk", "echo", "fizz", "gaze", "halo", "iris", "jolt", "keen"
]

def generate_username():
    if USERNAME_LIST:
        return USERNAME_LIST.pop(0)
    return ''.join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=4))

async def send_message(text):
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    async with aiohttp.ClientSession() as session:
        await session.post(f"{BOT_API_URL}/sendMessage", json=payload)

async def check_username(session, username, proxy):
    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)"
        ])
    }
    try:
        async with session.get(url, proxy=proxy, headers=headers, timeout=10) as resp:
            return resp.status == 404
    except Exception as e:
        print(f"Check username exception for @{username} with proxy {proxy}: {e}")
        return None

async def load_proxies():
    global PROXIES
    try:
        with open(PROXIES_FILE, "r") as f:
            PROXIES = [line.strip() for line in f if line.strip()]
        print(f"Loaded {len(PROXIES)} proxies.")
    except FileNotFoundError:
        PROXIES = []

async def run_checker_loop():
    global CHECKER_RUNNING, PROXIES
    CHECKER_RUNNING = True
    await send_message("Checker started.")
    print("Checker loop started.")

    if not PROXIES:
        await send_message("❌ No proxies loaded. Please add proxies to proxies.txt")
        CHECKER_RUNNING = False
        return

    proxy_pool = PROXIES.copy()

    async with aiohttp.ClientSession() as session:
        while CHECKER_RUNNING:
            if USERNAME_LIST:
                username = USERNAME_LIST.pop(0)
                print(f"Checking wordlist username: {username}")
            else:
                username = generate_username()
                print(f"Generated username: {username}")

            if not proxy_pool:
                await send_message("⚠️ All proxies failed. Stopping checker.")
                CHECKER_RUNNING = False
                break

            proxy = random.choice(proxy_pool)
            print(f"Trying @{username} with proxy {proxy}")

            result = await check_username(session, username, proxy)

            if result is True:
                await send_message(f"✅ @{username} is available!")
            elif result is None:
                print(f"Proxy failed for {proxy}, removing it from pool.")
                proxy_pool.remove(proxy)

            await asyncio.sleep(random.uniform(0.5, 1.5))

    CHECKER_RUNNING = False
    await send_message("Checker stopped.")
    print("Checker loop stopped.")

@app.post("/webhook")
async def telegram_webhook(request: Request):
    global CHECKER_RUNNING
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    message = data.get("message", {})
    text = message.get("text", "").strip().lower()

    if text in ["/start", "start"]:
        if not CHECKER_RUNNING:
            await send_message("Starting checker...")
            await load_proxies()
            asyncio.create_task(run_checker_loop())
        else:
            await send_message("Checker is already running.")

    return {"ok": True}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
