import asyncio
import aiohttp
import random
import json
from fastapi import FastAPI, Request, HTTPException
import uvicorn

app = FastAPI()

TELEGRAM_TOKEN = "7527264620:AAGG5qpYqV3o0h0NidwmsTOKxqVsmRIaX1A"
TELEGRAM_CHAT_ID = "7755395640"
BOT_API_URL = f"https://api.telegram.org/bot7527264620:AAGG5qpYqV3o0h0NidwmsTOKxqVsmRIaX1A"

CHECKER_RUNNING = False

USERNAME_LIST = [
    "tsla", "kurv", "loco", "vibe", "zest", "flux", "nova", "drip"
]

PROXIES = ["http://example:proxy@1.2.3.4:8080"]  # Replace with real proxies

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
    try:
        async with session.get(f"https://www.tiktok.com/@{username}", proxy=proxy, timeout=10) as resp:
            return resp.status == 404
    except:
        return None

async def run_checker():
    global CHECKER_RUNNING
    CHECKER_RUNNING = True
    await send_message("✅ Checker started.")

    if not PROXIES:
        await send_message("❌ No proxies available.")
        CHECKER_RUNNING = False
        return

    async with aiohttp.ClientSession() as session:
        while CHECKER_RUNNING:
            username = generate_username()
            proxy = random.choice(PROXIES)

            result = await check_username(session, username, proxy)
            if result:
                await send_message(f"<b>@{username}</b> is available!")

            await asyncio.sleep(random.uniform(0.5, 1.0))

@app.post("/webhook")
async def telegram_webhook(request: Request):
    global CHECKER_RUNNING
    try:
        data = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    message = data.get("message", {})
    text = message.get("text", "")

    if text == "/start" and not CHECKER_RUNNING:
        asyncio.create_task(run_checker())
        return {"ok": True}

    return {"ok": True}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
