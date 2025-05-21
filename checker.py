from fastapi import FastAPI, Request
import aiohttp
import asyncio
import random
import string
import logging

app = FastAPI()

# Telegram Bot config
TELEGRAM_TOKEN = "7698527405:AAE8z3q9epDTXZFZMNZRW9ilU-ayevMQKVA"
TELEGRAM_CHAT_ID = "7755395640"
TELEGRAM_API = f"https://api.telegram.org/bot7698527405:AAE8z3q9epDTXZFZMNZRW9ilU-ayevMQKVA"

# Globals for state tracking
checking_active = False
proxy_list = []
user_agent_list = []
semaphore = asyncio.Semaphore(20)  # Limit concurrency

# Sample wordlist for username fallback (can be replaced by file load)
username_wordlist = ["coolname", "funuser", "test1234", "semiog", "brandx"]

# Setup logging
logging.basicConfig(level=logging.INFO)

# ========== UTILS ==========

async def fetch_proxies():
    # Placeholder for proxy scraping logic
    # Replace with your proxy source or scraping
    global proxy_list
    proxy_list = [
        "http://123.123.123.123:8080",
        "http://111.111.111.111:3128"
    ]
    logging.info(f"Proxies updated: {len(proxy_list)}")

def generate_username():
    # Live 4-char username generator (a-z, 0-9)
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(4))

async def check_tiktok_username(username, proxy=None):
    # Simulate checking TikTok username availability
    # Replace this URL with actual TikTok API or web check URL
    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": random.choice(user_agent_list) if user_agent_list else "Mozilla/5.0"
    }
    try:
        async with semaphore:
            async with aiohttp.ClientSession() as session:
                if proxy:
                    connector = aiohttp.ProxyConnector.from_url(proxy)
                else:
                    connector = None
                async with session.get(url, headers=headers, proxy=proxy, timeout=10) as resp:
                    # TikTok returns 404 if username is available
                    if resp.status == 404:
                        logging.info(f"Username AVAILABLE: {username}")
                        return True
                    else:
                        logging.info(f"Username taken: {username}")
                        return False
    except Exception as e:
        logging.error(f"Error checking {username}: {e}")
        return False

async def send_telegram_message(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with aiohttp.ClientSession() as session:
        await session.post(f"{TELEGRAM_API}/sendMessage", json=payload)

# ========== TELEGRAM INLINE BUTTONS ==========

def build_inline_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "Claim", "callback_data": "claim"}],
            [{"text": "Skip", "callback_data": "skip"}]
        ]
    }

# ========== BOT LOGIC ==========

async def username_check_loop(chat_id):
    global checking_active
    while checking_active:
        # Generate or get username from wordlist
        username = generate_username()
        is_available = await check_tiktok_username(username, proxy=random.choice(proxy_list) if proxy_list else None)
        if is_available:
            msg = f"✅ Username available: *{username}*"
            keyboard = build_inline_keyboard()
            await send_telegram_message(chat_id, msg, reply_markup=keyboard)
        await asyncio.sleep(random.uniform(0.5, 1.5))  # random delay

# ========== FASTAPI ROUTES ==========

@app.get("/")
async def root():
    return {"status": "✅ Server running"}

@app.post("/webhook")
async def telegram_webhook(request: Request):
    global checking_active
    data = await request.json()
    logging.info(f"Incoming update: {data}")

    # Telegram updates structure varies
    message = data.get("message") or data.get("callback_query")
    if not message:
        return {"ok": True}

    # Handle callback queries (inline buttons)
    if "callback_query" in data:
        callback = data["callback_query"]
        chat_id = callback["message"]["chat"]["id"]
        data_payload = callback["data"]

        if data_payload == "claim":
            await send_telegram_message(chat_id, "🚀 You claimed the username!")
        elif data_payload == "skip":
            await send_telegram_message(chat_id, "⏭️ Skipped.")

        return {"ok": True}

    # Handle text messages
    text = message.get("text", "").lower()
    chat_id = message["chat"]["id"]

    if text == "/start":
        await send_telegram_message(chat_id, "✅ Checker bot is active and listening!")
    elif text == "/check":
        if not checking_active:
            checking_active = True
            asyncio.create_task(username_check_loop(chat_id))
            await send_telegram_message(chat_id, "🔎 Started checking usernames...")
        else:
            await send_telegram_message(chat_id, "⚠️ Already checking usernames.")
    elif text == "/stop":
        checking_active = False
        await send_telegram_message(chat_id, "🛑 Stopped checking usernames.")
    elif text == "/proxies":
        await fetch_proxies()
        await send_telegram_message(chat_id, f"🕵️‍♂️ Fetched {len(proxy_list)} proxies.")
    else:
        await send_telegram_message(chat_id, "❓ Unknown command. Use /start, /check, /stop, /proxies.")

    return {"ok": True}
