import os
import re
import asyncio
import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
from typing import Set, List

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")
TWO_CAPTCHA_KEY = os.getenv("TWO_CAPTCHA_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL") or "https://checkerpy-production-a7e1.up.railway.app/webhook"

app = FastAPI()

# Globals
checking = False
proxies: List[str] = []
username_queue: asyncio.Queue = asyncio.Queue()
active_tasks = set()

# Load themed wordlist (full words, no length limit)
def load_wordlist(file_path="wordlist.txt") -> List[str]:
    if not os.path.isfile(file_path):
        print(f"Wordlist file {file_path} not found!")
        return []
    with open(file_path, "r", encoding="utf-8") as f:
        words = [line.strip() for line in f if line.strip()]
    print(f"Loaded {len(words)} usernames from wordlist.")
    return words

# Telegram API helpers
async def send_telegram_message(text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()

async def answer_callback_query(callback_id, text=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()

async def set_telegram_webhook():
    print(f"Setting Telegram webhook to {WEBHOOK_URL}...")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
    params = {"url": WEBHOOK_URL}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            result = await resp.json()
            if result.get("ok"):
                print(f"Telegram webhook set successfully.")
            else:
                print(f"Failed to set webhook: {result}")

# Proxy scraping from Webshare
async def scrape_proxies():
    print("Scraping proxies from Webshare...")
    url = "https://proxy.webshare.io/api/proxy/list/"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    proxies_local = []
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                for proxy_data in data.get("results", []):
                    ip = proxy_data.get("proxy_address")
                    port = proxy_data.get("proxy_port")
                    ptype = proxy_data.get("proxy_type").lower()
                    if ip and port and ptype:
                        proxies_local.append(f"{ptype}://{ip}:{port}")
                print(f"Scraped {len(proxies_local)} proxies.")
            else:
                print(f"Failed to scrape proxies, status {resp.status}")
    return proxies_local

# Validate proxies (simple TCP connect test could be added; here just basic filtering)
async def validate_proxies(raw_proxies):
    print("Validating proxies...")
    valid = []
    for p in raw_proxies:
        # Basic format validation
        if re.match(r"^(http|socks4|socks5)://\d+\.\d+\.\d+\.\d+:\d+$", p):
            valid.append(p)
    print(f"Validated {len(valid)} proxies.")
    return valid

# Username availability check for TikTok
async def check_username(session, username, proxy=None):
    url = f"https://www.tiktok.com/@{username}"
    try:
        proxy_opt = {"proxy": proxy} if proxy else {}
        async with session.get(url, **proxy_opt, timeout=10) as resp:
            if resp.status == 404:
                return True  # Available
            else:
                return False
    except Exception:
        return False

# Worker task: consume usernames from queue and check availability
async def worker():
    async with aiohttp.ClientSession() as session:
        while checking:
            try:
                username = await asyncio.wait_for(username_queue.get(), timeout=10)
            except asyncio.TimeoutError:
                continue
            proxy = None
            if proxies:
                proxy = proxies.pop(0)
                proxies.append(proxy)  # rotate proxy
            available = await check_username(session, username, proxy)
            if available:
                # Send Telegram alert with inline Claim/Skip buttons
                buttons = {
                    "inline_keyboard": [
                        [
                            {"text": "Claim", "callback_data": f"claim:{username}"},
                            {"text": "Skip", "callback_data": f"skip:{username}"},
                        ]
                    ]
                }
                await send_telegram_message(f"✅ Username available: <b>{username}</b>", reply_markup=buttons)
            username_queue.task_done()

# Fill queue with usernames from wordlist
async def fill_queue(usernames):
    for u in usernames:
        await username_queue.put(u)

# Handle Telegram webhook updates
@app.post("/webhook")
async def telegram_webhook(req: Request):
    data = await req.json()
    # Handle callback query (button presses)
    if "callback_query" in data:
        cq = data["callback_query"]
        cid = cq["id"]
        data_text = cq["data"]
        if data_text.startswith("claim:"):
            username = data_text.split("claim:")[1]
            await answer_callback_query(cid, text=f"Attempting to claim {username}...")
            # Implement claim logic here or notify user
            await send_telegram_message(f"🟢 Trying to claim username: {username}")
        elif data_text.startswith("skip:"):
            username = data_text.split("skip:")[1]
            await answer_callback_query(cid, text=f"Skipped {username}")
        return JSONResponse({"ok": True})
    
    # Handle commands or messages
    message = data.get("message") or data.get("edited_message")
    if message and "text" in message:
        text = message["text"].lower()
        chat_id = message["chat"]["id"]
        if chat_id != int(CHAT_ID):
            return JSONResponse({"ok": True})  # Ignore others
        if text == "/start":
            global checking
            if checking:
                await send_telegram_message("Already running.")
            else:
                checking = True
                await send_telegram_message("Starting TikTok username checking...")
                # Start proxy scraping and queue filling in background
                asyncio.create_task(main_check_loop())
        elif text == "/stop":
            checking = False
            await send_telegram_message("Stopped TikTok username checking.")
    return JSONResponse({"ok": True})

# Main check loop: scrape proxies, validate, fill username queue, run workers
async def main_check_loop():
    global proxies
    # Scrape proxies
    raw = await scrape_proxies()
    proxies = await validate_proxies(raw)
    if not proxies:
        await send_telegram_message("⚠️ No valid proxies found. Stopping.")
        return
    # Load usernames
    usernames = load_wordlist()
    if not usernames:
        await send_telegram_message("⚠️ No usernames to check. Stopping.")
        return
    # Fill queue
    await fill_queue(usernames)
    # Launch worker tasks
    workers = [asyncio.create_task(worker()) for _ in range(20)]
    # Wait until queue is empty or stopped
    while checking and not username_queue.empty():
        await asyncio.sleep(1)
    # Cancel workers
    for w in workers:
        w.cancel()
    await send_telegram_message("✅ Finished checking usernames.")

# Startup event: set webhook
@app.on_event("startup")
async def startup_event():
    await set_telegram_webhook()

if __name__ == "__main__":
    # Run with: uvicorn scriptname:app --host 0.0.0.0 --port 8000
    uvicorn.run checker:app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
