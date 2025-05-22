import os
import asyncio
import aiohttp
import time
import random
import string
from collections import deque
from datetime import datetime
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse

app = FastAPI()

# Load from env or replace here
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or "your_telegram_token_here"
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID") or "your_chat_id_here")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY") or "your_webshare_api_key_here"

telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

checking_active = False
proxy_pool = deque()
available_usernames_counts = {}
usernames_batch_current = []
usernames_checked_info = {}

AVAILABLE_USERNAMES_FILE = "available_usernames.txt"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.5735.131 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]

# --- Telegram message sender ---
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

# --- Log available usernames to file ---
def log_available_username(username):
    now = int(time.time())
    count = available_usernames_counts.get(username, 0) + 1
    available_usernames_counts[username] = count

    lines = []
    if os.path.exists(AVAILABLE_USERNAMES_FILE):
        with open(AVAILABLE_USERNAMES_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()

    updated = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{username} "):
            new_line = f"{username} — available hits: {count} — last seen: {datetime.utcfromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            new_lines.append(new_line)
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_line = f"{username} — available hits: {count} — last seen: {datetime.utcfromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        new_lines.append(new_line)

    with open(AVAILABLE_USERNAMES_FILE, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

# --- Fetch proxies from Webshare ---
async def fetch_proxies_webshare():
    url = "https://proxy.webshare.io/api/proxy/list/"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    params = {"page_size": 100}
    proxies = []
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for p in data.get("results", []):
                        proxy_str = f"http://{p['username']}:{p['password']}@{p['proxy_address']}:{p['ports']['http']}"
                        proxies.append(proxy_str)
        except Exception:
            pass
    return proxies

# --- Validate proxies by pinging TikTok homepage ---
async def validate_proxy(proxy):
    url = "https://www.tiktok.com"
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, proxy=proxy, headers=headers) as resp:
                if resp.status == 200:
                    return True
    except:
        pass
    return False

async def refresh_and_validate_proxies():
    global proxy_pool
    await send_telegram("🔄 Refreshing proxies from Webshare...")
    proxies = await fetch_proxies_webshare()
    valid_proxies = deque()
    tasks = []
    for p in proxies:
        tasks.append(validate_proxy(p))
    results = await asyncio.gather(*tasks)
    for i, valid in enumerate(results):
        if valid:
            valid_proxies.append(proxies[i])
    proxy_pool = valid_proxies
    await send_telegram(f"✅ Proxies refreshed and validated: {len(proxy_pool)} available.")

# --- Generate random 4-letter usernames ---
def generate_usernames_batch(batch_size=50):
    chars = string.ascii_lowercase
    batch = []
    while len(batch) < batch_size:
        username = ''.join(random.choices(chars, k=4))
        batch.append(username)
    return batch

# --- Check TikTok username availability ---
async def check_username_availability(username: str, proxy: str = None):
    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, proxy=proxy, headers=headers, timeout=10) as resp:
                if resp.status == 404:
                    return True
                return False
    except:
        return False

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
            usernames_batch_current = generate_usernames_batch(50)
            await send_telegram(f"🔄 Loaded new batch of {len(usernames_batch_current)} usernames")

        username = usernames_batch_current.pop(0)
        proxy = None
        try:
            proxy = proxy_pool[0]
            proxy_pool.rotate(-1)
        except IndexError:
            proxy = None

        available = await check_username_availability(username, proxy)
        now_ts = int(time.time())
        if available:
            count = available_usernames_counts.get(username, 0) + 1
            available_usernames_counts[username] = count
            log_available_username(username)

            msg = (f"✅ Username *{username}* is available!\n"
                   f"Availability hits: {count}\n"
                   f"[Claim](https://www.tiktok.com/@{username})")

            keyboard = {
                "inline_keyboard": [
                    [{"text": "Claim", "url": f"https://www.tiktok.com/@{username}"}],
                ]
            }
            await send_telegram(msg, reply_markup=keyboard)

        await asyncio.sleep(1)
    await send_telegram("⏹️ Checker stopped.")

# --- Handle Telegram commands and button callbacks ---
@app.post("/webhook")
async def telegram_webhook(req: Request, background_tasks: BackgroundTasks):
    data = await req.json()

    # Handle commands sent via chat message
    if "message" in data and "text" in data["message"]:
        text = data["message"]["text"]
        chat_id = data["message"]["chat"]["id"]
        if chat_id != TELEGRAM_CHAT_ID:
            return JSONResponse({"ok": True})

        if text == "/startchecker":
            global checking_active
            if not checking_active:
                checking_active = True
                background_tasks.add_task(checker_loop)
                await send_telegram("▶️ Checker started.")
            else:
                await send_telegram("⚠️ Checker already running.")

        elif text == "/stopchecker":
            checking_active = False
            await send_telegram("⏹️ Checker stopped.")

        elif text == "/refreshproxies":
            background_tasks.add_task(refresh_and_validate_proxies)

        else:
            await send_telegram("Commands:\n/startchecker\n/stopchecker\n/refreshproxies")

    # Handle inline callback queries (Claim / Skip buttons)
    if "callback_query" in data:
        callback = data["callback_query"]
        data_str = callback.get("data", "")
        from_id = callback["from"]["id"]
        message_id = callback["message"]["message_id"]
        chat_id = callback["message"]["chat"]["id"]

        # Only allow authorized chat
        if chat_id != TELEGRAM_CHAT_ID:
            return JSONResponse({"ok": True})

        # For demo, just answer callback query
        # You can add real claim/skip logic here
        if data_str.startswith("claim:"):
            username = data_str.split(":")[1]
            await send_telegram(f"Claim requested for username: {username}")
        elif data_str.startswith("skip:"):
            username = data_str.split(":")[1]
            await send_telegram(f"Skip requested for username: {username}")

        # Respond to Telegram so loading spinner disappears
        async with aiohttp.ClientSession() as session:
            await session.post(f"{telegram_api_url}/answerCallbackQuery", json={
                "callback_query_id": callback["id"],
                "text": "Action received!",
                "show_alert": False,
            })

    return JSONResponse({"ok": True})

# --- Root endpoint for testing ---
@app.get("/")
def root():
    return {"status": "TikTok Checker bot running"}

# --- On startup, refresh proxies ---
@app.on_event("startup")
async def startup_event():
    await refresh_and_validate_proxies()

# To run locally:
# uvicorn this_script_name:app --host 0.0.0.0 --port 8000
