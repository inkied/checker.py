import os
import aiohttp
import asyncio
import random
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_API = os.getenv("TELEGRAM_API")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

THEMED_WORDS_URL = "https://raw.githubusercontent.com/inkied/checker.py/main/themed_words.txt"

RUNNING = False
AVAILABLE_USERNAMES = []

app = FastAPI()

# Fetch and parse themed words
async def fetch_themed_words():
    async with aiohttp.ClientSession() as session:
        async with session.get(THEMED_WORDS_URL) as resp:
            text = await resp.text()
    words = []
    for line in text.splitlines():
        if line and not line.endswith(":"):
            words.extend([w.strip() for w in line.split(",")])
    return list(set(words))

# Check if a username is available on TikTok
async def is_available(username, session):
    try:
        url = f"https://www.tiktok.com/@{username}"
        async with session.get(url, timeout=10) as resp:
            return resp.status == 404
    except:
        return False

# Send batched results to Telegram
async def notify_telegram_batch(usernames):
    if not TELEGRAM_API or not TELEGRAM_CHAT_ID:
        return
    text = "✅ Available TikTok usernames:\n" + "\n".join(usernames)
    url = f"https://api.telegram.org/bot{TELEGRAM_API}/sendMessage"
    async with aiohttp.ClientSession() as session:
        await session.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text
        })

# Username checking loop
async def check_loop():
    global RUNNING
    words = await fetch_themed_words()
    async with aiohttp.ClientSession() as session:
        while RUNNING:
            username = random.choice(words).lower()
            if await is_available(username, session):
                AVAILABLE_USERNAMES.append(username)
                if len(AVAILABLE_USERNAMES) >= 5:
                    await notify_telegram_batch(AVAILABLE_USERNAMES[:])
                    AVAILABLE_USERNAMES.clear()
            await asyncio.sleep(0.5)

# Telegram webhook to start/stop
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

@app.get("/")
async def root():
    words = await fetch_themed_words()
    return {"sample": words[:10], "count": len(words)}

@app.on_event("startup")
async def on_startup():
    if TELEGRAM_API and WEBHOOK_URL:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"https://api.telegram.org/bot{TELEGRAM_API}/setWebhook",
                params={"url": WEBHOOK_URL}
            )
