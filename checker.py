# checker.py

import asyncio
import aiohttp
import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_API = os.getenv("TELEGRAM_API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not all([TELEGRAM_API, WEBHOOK_URL, WEBSHARE_API_KEY, TELEGRAM_CHAT_ID]):
    logging.error("Missing one or more required environment variables.")
    logging.error("Missing environment variables: TELEGRAM_API_TOKEN, WEBHOOK_URL, WEBSHARE_API_KEY, TELEGRAM_CHAT_ID")
    exit(1)

app = FastAPI()

async def set_webhook():
    async with aiohttp.ClientSession() as session:
        webhook_url = f"https://api.telegram.org/bot{TELEGRAM_API}/setWebhook?url={WEBHOOK_URL}"
        async with session.post(webhook_url) as resp:
            if resp.status == 200:
                logging.info("Webhook set successfully.")
            else:
                logging.error("Failed to set webhook.")

@app.on_event("startup")
async def startup_event():
    logging.info("Starting checker.py lifespan, setting Telegram webhook...")
    await set_webhook()

@app.post("/webhook")
async def telegram_webhook(request: Request):
    body = await request.json()
    message = body.get("message")

    if not message:
        return JSONResponse(content={"status": "no message"})

    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    if text == "/start":
        await send_message("Checker started.")
        # Insert code to start checking
    elif text == "/stop":
        await send_message("Checker stopped.")
        # Insert code to stop checking

    return JSONResponse(content={"status": "ok"})

async def send_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_API}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    async with aiohttp.ClientSession() as session:
        await session.post(url, json=payload)

# You can place your checker logic and proxy rotation here

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("checker:app", host="0.0.0.0", port=8000, reload=True)
