import os
import aiohttp
from fastapi import FastAPI, Request
from dotenv import load_dotenv
import uvicorn

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
APP_URL = os.getenv("APP_URL")  # e.g. https://your-app-name.up.railway.app

app = FastAPI()

async def send_telegram_message(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    async with aiohttp.ClientSession() as session:
        await session.post(url, json=payload)

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    if "message" in data:
        message = data["message"]
        text = message.get("text", "")
        chat_id = message["chat"]["id"]

        # Only respond to your chat ID to avoid spam
        if str(chat_id) != str(TELEGRAM_CHAT_ID):
            return {"ok": True}

        if text.startswith("/start"):
            await send_telegram_message(chat_id, "✅ Bot started! Ready to check usernames.")
        elif text.startswith("/stop"):
            await send_telegram_message(chat_id, "🛑 Bot stopped.")

    return {"ok": True}

@app.on_event("startup")
async def startup_event():
    # Set webhook to your /webhook endpoint on Railway
    webhook_url = f"{APP_URL}/webhook"
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
    payload = {"url": webhook_url}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            result = await resp.json()
            if result.get("ok"):
                print(f"✅ Webhook set to {webhook_url}")
            else:
                print(f"❌ Failed to set webhook: {result}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
