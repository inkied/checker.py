import os
import aiohttp
import asyncio
import random
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_API = os.getenv("TELEGRAM_API")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

app = FastAPI()
RUNNING = False
WORDLIST_URL = "https://raw.githubusercontent.com/inkied/checker.py/main/themed_words.txt"

# Auto-set Telegram webhook
async def set_webhook():
    if not TELEGRAM_API or not WEBHOOK_URL:
        raise ValueError("Missing TELEGRAM_API or WEBHOOK_URL environment variable")
    url = f"https://api.telegram.org/bot{TELEGRAM_API}/setWebhook"
    async with aiohttp.ClientSession() as session:
        await session.post(url, params={"url": WEBHOOK_URL})

@app.on_event("startup")
async def lifespan():
    print("Setting Telegram webhook...")
    await set_webhook()

# Fetch words from your GitHub wordlist
async def load_words():
    async with aiohttp.ClientSession() as session:
        async with session.get(WORDLIST_URL) as r:
            raw = await r.text()
            words = []
            for line in raw.splitlines():
                if not line or ":" in line:
                    continue
                words.extend(w.strip() for w in line.split(",") if w.strip())
            return words

# Check username (mock placeholder)
async def is_available(username):
    await asyncio.sleep(random.uniform(0.1, 0.4))
    return random.random() < 0.001

# Check loop
async def check_loop():
    global RUNNING
    words = await load_words()
    while RUNNING:
        word = random.choice(words)
        if await is_available(word):
            msg = f"✅ Available: `{word}`"
            url = f"https://api.telegram.org/bot{TELEGRAM_API}/sendMessage"
            await aiohttp.ClientSession().post(url, json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": msg,
                "parse_mode": "Markdown"
            })
        await asyncio.sleep(random.uniform(0.3, 1))

@app.post("/webhook")
async def telegram_webhook(request: Request):
    global RUNNING
    data = await request.json()
    message = data.get("message", {})
    text = message.get("text", "")

    if text == "/start":
        if not RUNNING:
            RUNNING = True
            asyncio.create_task(check_loop())
        return JSONResponse({"status": "started"})
    elif text == "/stop":
        RUNNING = False
        return JSONResponse({"status": "stopped"})
    return JSONResponse({"status": "ignored"})
