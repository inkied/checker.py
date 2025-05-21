import os
import asyncio
import aiohttp
import time
from collections import deque
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or "your_telegram_token_here"
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID") or "your_chat_id_here")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY") or "your_webshare_api_key_here"

telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

checking_active = False
proxy_pool = deque()
proxy_stats = {}  # proxy -> {success, fail, avg_response}

usernames_batch_current = []
usernames_checked_info = {}  # username -> {available_since, last_released, last_checked}
available_usernames_counts = {}  # username -> count of availability hits

AVAILABLE_USERNAMES_FILE = "available_usernames.txt"

# --- Telegram messaging helper ---
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

# --- Log or update available username info in a file ---
def log_available_username(username):
    now = int(time.time())
    count = available_usernames_counts.get(username, 0) + 1
    available_usernames_counts[username] = count

    # Read existing lines
    lines = []
    if os.path.exists(AVAILABLE_USERNAMES_FILE):
        with open(AVAILABLE_USERNAMES_FILE, "r") as f:
            lines = f.readlines()

    # Update or add the username line
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

    with open(AVAILABLE_USERNAMES_FILE, "w") as f:
        f.writelines(new_lines)

# --- Proxy scraping and validation ---
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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
                      " Chrome/114.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            start = time.time()
            async with session.get(test_url, proxy=proxy, headers=headers) as resp:
                if resp.status == 200:
                    elapsed = time.time() - start
                    return True, elapsed
    except:
        pass
    return False, None

async def refresh_and_validate_proxies():
    global proxy_pool, proxy_stats
    await send_telegram("🔄 Refreshing proxies from Webshare...")
    proxies = await fetch_proxies_webshare()
    valid_proxies = deque()
    new_proxy_stats = {}
    tasks = []
    for p in proxies:
        tasks.append(validate_proxy(p))
    results = await asyncio.gather(*tasks)
    for i, (valid, resp_time) in enumerate(results):
        if valid:
            p = proxies[i]
            valid_proxies.append(p)
            new_proxy_stats[p] = {"success": 0, "fail": 0, "avg_response": resp_time}
    proxy_pool = valid_proxies
    proxy_stats = new_proxy_stats
    await send_telegram(f"✅ Proxies refreshed and validated: {len(proxy_pool)} available.")

# --- Username generation (example: random 4-letter lowercase) ---
def generate_usernames_batch(batch_size=50):
    import random
    import string
    batch = []
    while len(batch) < batch_size:
        username = ''.join(random.choices(string.ascii_lowercase, k=4))
        batch.append(username)
    return batch

# --- TikTok availability check ---
async def check_username_availability(username: str, proxy: str = None):
    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
                      " Chrome/114.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, proxy=proxy, headers=headers, timeout=10) as resp:
                if resp.status == 404:
                    return True
                elif resp.status == 200:
                    return False
                else:
                    return False
    except Exception:
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
            info = usernames_checked_info.get(username)
            if not info:
                usernames_checked_info[username] = {
                    "available_since": now_ts,
                    "last_released": now_ts - 86400,
                    "last_checked": now_ts,
                }
            else:
                usernames_checked_info[username]["last_checked"] = now_ts

            # Increment and log availability count
            log_available_username(username)

            available_since = usernames_checked_info[username]["available_since"]
            duration = now_ts - available_since
            last_released = usernames_checked_info[username]["last_released"]
            msg = f"✅ Username *{username}* is available!\nAvailable for: {duration}s\nLast released: {datetime.utcfromtimestamp(last_released).strftime('%Y-%m-%d %H:%M:%S UTC')}\nAvailability hits: {available_usernames_counts[username]}"
            keyboard = {
                "inline_keyboard": [
                    [{"text": "Claim", "callback_data": f"claim:{username}"}],
                    [{"text": "Skip", "callback_data": f"skip:{username}"}],
                ]
            }
            await send_telegram(msg, reply_markup=keyboard)

        else:
            if username in usernames_checked_info:
                usernames_checked_info.pop(username)

        await asyncio.sleep(1)
    await send_telegram("⏹️ Checker stopped.")

# --- Telegram webhook handler for inline button presses ---
@app.post("/webhook")
async def telegram_webhook(req: Request):
    data = await req.json()
    if "callback_query" in data:
        callback = data["callback_query"]
        user_id = callback["from"]["id"]
        data_text = callback["data"]
        message_id = callback["message"]["message_id"]
        chat_id = callback["message"]["chat"]["id"]

        if data_text.startswith("claim:"):
            username = data_text.split("claim:")[1]
            # You can add your claim logic here
            await send_telegram(f"User {user_id} claimed username: {username}")
            # Optionally answer callback query
            return JSONResponse({"method": "answerCallbackQuery", "callback_query_id": callback["id"], "text": f"Claimed {username}!"})
        elif data_text.startswith("skip:"):
            username = data_text.split("skip:")[1]
            # Logic for skipping username if needed
            await send_telegram(f"User {user_id} skipped username: {username}")
            return JSONResponse({"method": "answerCallbackQuery", "callback_query_id": callback["id"], "text": f"Skipped {username}."})

    return JSONResponse({"status": "ok"})

# --- Start/stop commands for checking ---
@app.post("/start")
async def start_checking():
    global checking_active
    if not checking_active:
        checking_active = True
        asyncio.create_task(checker_loop())
        return {"status": "started"}
    return {"status": "already running"}

@app.post("/stop")
async def stop_checking():
    global checking_active
    checking_active = False
    return {"status": "stopped"}

# --- Main entry for local testing ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
