import asyncio
import aiohttp
from fastapi import FastAPI, Request

app = FastAPI()

TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

semi_og_words = ["tsla", "kurv", "vibe", "lcky", "loky"]

checking = False

@app.post("/webhook")
async def telegram_webhook(request: Request):
    global checking
    data = await request.json()
    message = data.get("message")
    if not message:
        return {"ok": True}

    text = message.get("text", "").lower()
    chat_id = message["chat"]["id"]

    if text == "/start" and not checking:
        checking = True
        await send_message(chat_id, "Checker is starting...")
        asyncio.create_task(run_checker(chat_id))
    elif text == "/stop" and checking:
        checking = False
        await send_message(chat_id, "Checker stopped.")

    return {"ok": True}

async def send_message(chat_id, text):
    async with aiohttp.ClientSession() as session:
        await session.post(f"{TELEGRAM_API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text
        })

async def run_checker(chat_id):
    global checking
    while checking:
        for username in semi_og_words:
            if not checking:
                break
            available = await check_username(username)
            if available:
                await send_message(chat_id, f"Username @{username} is available!")
            await asyncio.sleep(2)  # small delay between checks
        await asyncio.sleep(5)  # delay before looping over usernames again

async def check_username(username):
    url = f"https://www.tiktok.com/@{username}"
    headers = {"User-Agent": "Mozilla/5.0"}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, allow_redirects=False) as resp:
                return resp.status == 404
        except:
            return False
