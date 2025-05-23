import os
import asyncio
import aiohttp
import time
import random
from collections import deque
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

# === CONFIGURATION ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or "your_telegram_token_here"
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID") or "your_chat_id_here")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY") or "your_webshare_api_key_here"
WEBHOOK_URL = os.getenv("WEBHOOK_URL") or "https://checker.up.railway.app/webhook"  # Your deployed webhook URL

telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

checking_active = False
proxy_pool = deque()
usernames_batch_current = []
usernames_checked_info = {}
available_usernames_counts = {}

AVAILABLE_USERNAMES_FILE = "available_usernames.txt"

# --- Brand-style username generator ---
BRAND_BASES = [
    "luxe", "nova", "pique", "vanta", "kuro", "aero", "vela", "mira", "sola", "zara",
    "ryze", "kyro", "zeal", "flux", "kine", "nexa", "orbi", "lyra", "echo", "riva"
]
BRAND_SUFFIXES = ["ly", "io", "ex", "us", "on"]

def generate_brand_usernames(batch_size=50):
    usernames = []
    while len(usernames) < batch_size:
        base = random.choice(BRAND_BASES)
        if random.random() < 0.6:
            suffix = random.choice(BRAND_SUFFIXES)
            username = base + suffix
        else:
            username = base
        if 3 <= len(username) <= 24 and username not in usernames:
            usernames.append(username)
    return usernames

# --- Telegram send helper ---
async def send_telegram(text, reply_markup=None):
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    async with aiohttp.ClientSession() as session:
        async with session.post(f"{telegram_api_url}/sendMessage", json=payload) as resp:
            return await resp.json()

# --- Set Telegram webhook on startup ---
@app.on_event("startup")
async def startup_event():
    print("Starting up, setting webhook...")
    async with aiohttp.ClientSession() as session:
        set_url = f"{telegram_api_url}/setWebhook"
        params = {"url": WEBHOOK_URL}
        async with session.post(set_url, params=params) as resp:
            res = await resp.json()
            if res.get("ok"):
                print(f"Webhook set successfully: {WEBHOOK_URL}")
            else:
                print(f"Failed to set webhook: {res}")

# --- Proxy fetch and validation from Webshare ---
async def fetch_proxies_webshare():
    url = "https://proxy.webshare.io/api/proxy/list/"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    params = {"page_size": 100}
    proxies = []
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                for p in data.get("results", []):
                    proxy_str = f"http://{p['username']}:{p['password']}@{p['proxy_address']}:{p['ports']['http']}"
                    proxies.append(proxy_str)
    return proxies

async def validate_proxy(proxy):
    test_url = "https://www.tiktok.com"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(test_url, proxy=proxy, headers=headers) as resp:
                return resp.status == 200
    except:
        return False

async def refresh_and_validate_proxies():
    global proxy_pool
    await send_telegram("🔄 Refreshing proxies from Webshare...")
    proxies = await fetch_proxies_webshare()
    valid_proxies = deque()
    tasks = [validate_proxy(p) for p in proxies]
    results = await asyncio.gather(*tasks)
    for i, valid in enumerate(results):
        if valid:
            valid_proxies.append(proxies[i])
    proxy_pool = valid_proxies
    await send_telegram(f"✅ Proxies refreshed and validated: {len(proxy_pool)} available.")

# --- Check TikTok username availability ---
async def check_username_availability(username: str, proxy: str = None):
    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, proxy=proxy, headers=headers, timeout=10) as resp:
                if resp.status == 404:
                    return True
                else:
                    return False
    except:
        return False

# --- Log available usernames to file (optional) ---
def log_available_username(username):
    now = int(time.time())
    count = available_usernames_counts.get(username, 0) + 1
    available_usernames_counts[username] = count

    lines = []
    if os.path.exists(AVAILABLE_USERNAMES_FILE):
        with open(AVAILABLE_USERNAMES_FILE, "r") as f:
            lines = f.readlines()

    updated = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{username} "):
            new_lines.append(f"{username} — hits: {count} — last seen: {datetime.utcfromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{username} — hits: {count} — last seen: {datetime.utcfromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")

    with open(AVAILABLE_USERNAMES_FILE, "w") as f:
        f.writelines(new_lines)

# --- Main checker loop ---
async def checker_loop():
    global checking_active, usernames_batch_current
    await send_telegram("🟢 Checker started.")
    while checking_active:
        if not proxy_pool:
            await send_telegram("⚠️ Proxy pool empty, refreshing proxies...")
            await refresh_and_validate_proxies()
            if not proxy_pool:
                await asyncio.sleep(10)
                continue

        if not usernames_batch_current:
            usernames_batch_current = generate_brand_usernames(50)
            await send_telegram(f"🔄 Loaded new batch of {len(usernames_batch_current)} usernames")

        username = usernames_batch_current.pop(0)
        proxy = proxy_pool[0]
        proxy_pool.rotate(-1)

        available = await check_username_availability(username, proxy)
        now_ts = int(time.time())
        if available:
            if username not in usernames_checked_info:
                usernames_checked_info[username] = {"available_since": now_ts, "last_checked": now_ts}
            else:
                usernames_checked_info[username]["last_checked"] = now_ts

            log_available_username(username)

            msg = f"✅ Username *{username}* is available!\nAvailability hits: {available_usernames_counts[username]}"
            keyboard = {
                "inline_keyboard": [
                    [{"text": "Claim", "callback_data": f"claim:{username}"}],
                    [{"text": "Skip", "callback_data": f"skip:{username}"}]
                ]
            }
            await send_telegram(msg, reply_markup=keyboard)
        else:
            usernames_checked_info.pop(username, None)

        await asyncio.sleep(1)
    await send_telegram("⏹️ Checker stopped.")

# --- Root path for Railway health check ---
@app.get("/")
async def root():
    return {"status": "running"}

# --- Telegram webhook endpoint ---
@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        print(f"Webhook data received: {data}")

        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")

            global checking_active

            if text == "/start":
                if not checking_active:
                    checking_active = True
                    asyncio.create_task(checker_loop())
                    await send_telegram("✅ Checker started.")
                else:
                    await send_telegram("⚠️ Checker already running.")

            elif text == "/stop":
                if checking_active:
                    checking_active = False
                    await send_telegram("⏹️ Checker stopping...")
                else:
                    await send_telegram("⚠️ Checker is not running.")

            elif text == "/refreshproxies":
                await refresh_and_validate_proxies()

            else:
                await send_telegram("🤖 Commands:\n/start - start checker\n/stop - stop checker\n/refreshproxies - refresh proxies")

        elif "callback_query" in data:
            # Handle inline button presses here if you want
            await send_telegram("Callback received, but not implemented.")

        return JSONResponse({"ok": True})

    except Exception as e:
        print(f"Error in webhook: {e}")
        return JSONResponse({"ok": False})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("checker:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), log_level="info")
