import os
import asyncio
import httpx
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)

app = FastAPI()

TELEGRAM_API_TOKEN = os.getenv("TELEGRAM_API_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")
THEMED_WORDS_URL = "https://raw.githubusercontent.com/inkied/checker.py/main/themed_words.txt"

if not all([TELEGRAM_API_TOKEN, TELEGRAM_CHAT_ID, WEBHOOK_URL, WEBSHARE_API_KEY]):
    logging.error("Missing one or more required environment variables.")
    exit(1)

http_client = httpx.AsyncClient(timeout=15)

# State
running = False
usernames_to_check = []
checked_usernames = set()
proxies = []

# Load themed words from GitHub
async def load_themed_words():
    global usernames_to_check
    try:
        r = await http_client.get(THEMED_WORDS_URL)
        r.raise_for_status()
        text = r.text
        words = []
        for line in text.splitlines():
            if ":" in line:
                _, vals = line.split(":", 1)
                words.extend([w.strip() for w in vals.split(",") if w.strip()])
        usernames_to_check = words
        logging.info(f"Loaded {len(usernames_to_check)} themed usernames")
    except Exception as e:
        logging.error(f"Failed to load themed words: {e}")

# Set Telegram webhook and send test message
async def set_webhook():
    r = await http_client.post(f"https://api.telegram.org/bot{TELEGRAM_API_TOKEN}/setWebhook",
                               params={"url": WEBHOOK_URL})
    if r.status_code == 200:
        logging.info("Telegram webhook set successfully.")
    else:
        logging.error(f"Failed to set webhook: {r.status_code} {r.text}")

    # Test message
    msg = await http_client.post(f"https://api.telegram.org/bot{TELEGRAM_API_TOKEN}/sendMessage",
                                 data={"chat_id": TELEGRAM_CHAT_ID, "text": "Bot started and webhook set."})
    if msg.status_code != 200:
        logging.error(f"Failed to send test message: {msg.text}")

# Scrape proxies from Webshare (limit 100)
async def fetch_proxies():
    global proxies
    try:
        headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
        resp = await http_client.get("https://proxy.webshare.io/api/proxy/list/?page=1&page_size=100", headers=headers)
        resp.raise_for_status()
        data = resp.json()
        proxies = [f"http://{p['proxy_address']}:{p['ports']['http']}" for p in data["results"]]
        logging.info(f"Loaded {len(proxies)} proxies")
    except Exception as e:
        logging.error(f"Error fetching proxies: {e}")

# Check username availability on TikTok (basic)
async def check_username(username, proxy=None):
    url = f"https://www.tiktok.com/@{username}"
    try:
        r = await http_client.get(url, proxies={"http": proxy, "https": proxy} if proxy else None)
        # TikTok returns 404 if username is available
        if r.status_code == 404:
            return True
    except Exception:
        pass
    return False

# Send Telegram alert for available username
async def alert_available(username):
    text = f"✅ Username available: @{username}"
    await http_client.post(f"https://api.telegram.org/bot{TELEGRAM_API_TOKEN}/sendMessage",
                           data={"chat_id": TELEGRAM_CHAT_ID, "text": text})

# Checker loop
async def checker_loop():
    global running
    proxy_index = 0
    while running and usernames_to_check:
        username = usernames_to_check.pop(0)
        if username in checked_usernames:
            continue
        proxy = proxies[proxy_index % len(proxies)] if proxies else None
        proxy_index += 1
        available = await check_username(username, proxy)
        if available:
            await alert_available(username)
        checked_usernames.add(username)
        await asyncio.sleep(1)  # throttle requests

@app.on_event("startup")
async def startup_event():
    await set_webhook()
    await load_themed_words()
    await fetch_proxies()

@app.post("/webhook")
async def telegram_webhook(req: Request):
    global running
    data = await req.json()
    message = data.get("message") or data.get("edited_message")
    if not message:
        return JSONResponse({"ok": True})

    text = message.get("text", "").lower()
    chat_id = str(message["chat"]["id"])

    if chat_id != TELEGRAM_CHAT_ID:
        return JSONResponse({"ok": True})  # ignore other chats

    if text == "/start":
        if running:
            await http_client.post(f"https://api.telegram.org/bot{TELEGRAM_API_TOKEN}/sendMessage",
                                   data={"chat_id": TELEGRAM_CHAT_ID, "text": "Already running."})
        else:
            running = True
            asyncio.create_task(checker_loop())
            await http_client.post(f"https://api.telegram.org/bot{TELEGRAM_API_TOKEN}/sendMessage",
                                   data={"chat_id": TELEGRAM_CHAT_ID, "text": "Checker started."})

    elif text == "/stop":
        if not running:
            await http_client.post(f"https://api.telegram.org/bot{TELEGRAM_API_TOKEN}/sendMessage",
                                   data={"chat_id": TELEGRAM_CHAT_ID, "text": "Not running."})
        else:
            running = False
            await http_client.post(f"https://api.telegram.org/bot{TELEGRAM_API_TOKEN}/sendMessage",
                                   data={"chat_id": TELEGRAM_CHAT_ID, "text": "Checker stopped."})

    return JSONResponse({"ok": True})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
