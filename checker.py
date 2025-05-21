import os
import asyncio
import aiohttp
from fastapi import FastAPI, Request
import uvicorn

app = FastAPI()

# --- Config from environment variables ---
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("CHAT_ID")
BOT_API_URL = f"https://api.telegram.org/bot7527264620:AAGG5qpYqV3o0h0NidwmsTOKxqVsmRIaX1A"
WEBHOOK_URL = "https://checkerpy-production-a7e1.up.railway.app/webhook"

# --- State ---
CHECKER_RUNNING = False

# Example usernames to check
USERNAME_LIST = ["tsla", "kurv", "loco", "vibe", "zest"]

# --- Telegram Send Message ---
async def send_message(text):
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    async with aiohttp.ClientSession() as session:
        await session.post(f"{BOT_API_URL}/sendMessage", json=data)

# --- Dummy Username Checker ---
async def check_username(username):
    await asyncio.sleep(0.5)
    import random
    return random.choice([True, False])

# --- Checker Loop ---
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

# --- Webhook Endpoint ---
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

# --- Root Route for Railway Uptime Check ---
@app.get("/")
async def root():
    return {"status": "running"}

# --- Set and Verify Telegram Webhook ---
@app.on_event("startup")
async def setup_webhook():
    async with aiohttp.ClientSession() as session:
        # Set the webhook
        set_url = f"{BOT_API_URL}/setWebhook"
        set_resp = await session.post(set_url, json={"url": WEBHOOK_URL})
        print("Set webhook response:", await set_resp.json())

        # Check webhook status
        info_url = f"{BOT_API_URL}/getWebhookInfo"
        info_resp = await session.get(info_url)
        info_data = await info_resp.json()
        print("Current webhook info:", info_data)

# --- Run Uvicorn ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting server on port: {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
