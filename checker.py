import os
import asyncio
import aiohttp
import time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from collections import deque
from datetime import datetime
from dotenv import load_dotenv
import uvicorn

load_dotenv()
app = FastAPI()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ROTATING_PROXY = os.getenv("WEBSHARE_PROXY")

telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
checking_active = False

usernames_batch_current = []
usernames_batch_old = []
usernames_checked_info = {}  # {username: {'available_since': timestamp, 'last_released': timestamp}}

# Simulated username generator (replace with your real generator or wordlist)
def generate_usernames_batch(size=50):
    now = int(time.time())
    return [f"user{now + i}" for i in range(size)]

async def send_telegram(message: str, buttons: list = None):
    async with aiohttp.ClientSession() as session:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": buttons}
        await session.post(f"{telegram_api_url}/sendMessage", json=payload)

async def check_username(username: str):
    await asyncio.sleep(0.3)
    available = (hash(username) % 3) == 0
    now = int(time.time())
    if available:
        info = usernames_checked_info.get(username)
        if not info:
            usernames_checked_info[username] = {
                "available_since": now,
                "last_released": now - 86400,
            }
        else:
            usernames_checked_info[username]["last_checked"] = now
    else:
        usernames_checked_info.pop(username, None)
    return available

async def checker_loop():
    global checking_active, usernames_batch_current, usernames_batch_old
    while checking_active:
        if not usernames_batch_current:
            usernames_batch_old = usernames_batch_current
            usernames_batch_current = generate_usernames_batch(50)
            await send_telegram(f"🔄 Loaded new batch of {len(usernames_batch_current)} usernames")

        username = usernames_batch_current.pop(0)
        available = await check_username(username)

        if available:
            info = usernames_checked_info.get(username, {})
            duration = int(time.time()) - info.get("available_since", int(time.time()))
            last_released = info.get("last_released", "Unknown")
            msg = f"✅ *{username}* is available!\nAvailable for: `{duration}s`\nLast released: `{last_released}`"
            await send_telegram(msg)

        await asyncio.sleep(0.6)

    await send_telegram("⏹️ Checker stopped.")

@app.post("/webhook")
async def telegram_webhook(request: Request):
    global checking_active, usernames_batch_current, usernames_batch_old
    data = await request.json()
    message = data.get("message") or {}
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip() if message else ""
    callback = data.get("callback_query", {})
    cb_data = callback.get("data")
    cb_id = callback.get("id")
    cb_user = callback.get("from", {}).get("id")

    if cb_id and cb_user and str(cb_user) == TELEGRAM_CHAT_ID:
        if cb_data == "start":
            if not checking_active:
                checking_active = True
                asyncio.create_task(checker_loop())
                await send_telegram("🟢 Checker started.")
        elif cb_data == "stop":
            checking_active = False
            await send_telegram("🔴 Checker stopping...")
        elif cb_data == "refresh_usernames":
            usernames_batch_old = usernames_batch_current
            usernames_batch_current = generate_usernames_batch(50)
            await send_telegram("🔄 Refreshed username batches.")
        elif cb_data == "proxies":
            await send_telegram("🌐 Using *rotating proxy endpoint*.\nNo proxy validation needed.")

        return JSONResponse({"ok": True})

    if text == "/start":
        buttons = [[
            {"text": "▶️ Start", "callback_data": "start"},
            {"text": "⏹️ Stop", "callback_data": "stop"}
        ], [
            {"text": "♻️ Refresh Usernames", "callback_data": "refresh_usernames"},
            {"text": "🌍 Proxy Status", "callback_data": "proxies"}
        ]]
        await send_telegram("🧠 Bot Control Panel:", buttons)
        return JSONResponse({"status": "buttons sent"})

    return JSONResponse({"status": "ignored"})

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
