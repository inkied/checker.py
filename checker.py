import os
import asyncio
import aiohttp
from fastapi import FastAPI, Request
import uvicorn

app = FastAPI()

# --- Config from environment variables ---
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("CHAT_ID")
BOT_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# --- State ---
CHECKER_RUNNING = False

# Example usernames to check
USERNAME_LIST = ["tsla", "kurv", "loco", "vibe", "zest"]

async def send_message(text):
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    async with aiohttp.ClientSession() as session:
        await session.post(f"{BOT_API_URL}/sendMessage", json=data)

async def check_username(username):
    # Dummy check: 50% chance available
    await asyncio.sleep(0.5)
    import random
    return random.choice([True, False])

async def run_checker_loop():
    global CHECKER_RUNNING
    CHECKER_RUNNING = True
    print("Checker started")

    while CHECKER_RUNNING and USERNAME_LIST:
        username = USERNAME_LIST.pop(0)
        print(f"Checking username: {username}")

        available = await check_username(username)
        if available:
            await send_message(f"Username <b>@{username}</b> is available!")

        await asyncio.sleep(1)

    CHECKER_RUNNING = False
    print("Checker stopped")

@app.post("/webhook")
async def webhook(request: Request):
    global CHECKER_RUNNING
    data = await request.json()
    print(f"Received update: {data}")

    if "message" in data:
        message = data["message"]
        text = message.get("text", "")

        if text == "/start":
            await send_message("Checker is starting...")
            if not CHECKER_RUNNING:
                asyncio.create_task(run_checker_loop())

    return {"ok": True}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting server on port: {port}")  # <-- This log confirms port Railway uses
    uvicorn.run(app, host="0.0.0.0", port=port)
