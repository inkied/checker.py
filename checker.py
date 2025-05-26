import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import os
import httpx

logging.basicConfig(level=logging.INFO)

telegram_api = os.getenv("TELEGRAM_API")  # Your Telegram bot token, e.g. '7527264620:ABC...'
chat_id = os.getenv("TELEGRAM_CHAT_ID")   # Your chat ID as string
webhook_url = os.getenv("WEBHOOK_URL")    # Your webhook HTTPS URL, e.g. 'https://checker.up.railway.app/webhook'

async def set_webhook():
    if not telegram_api or not webhook_url:
        raise ValueError("Missing TELEGRAM_API or WEBHOOK_URL environment variable")

    url = f"https://api.telegram.org/bot{telegram_api}/setWebhook"
    params = {"url": webhook_url}
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, params=params)
        logging.info(f"Telegram setWebhook response status: {resp.status_code}")
        if resp.status_code != 200:
            raise Exception(f"Failed to set webhook: {resp.text}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        logging.info("Starting app lifespan, setting Telegram webhook...")
        await set_webhook()
        logging.info("Telegram webhook set successfully.")
        yield
    except Exception as e:
        logging.error(f"Lifespan startup error:", exc_info=True)
        raise

app = FastAPI(lifespan=lifespan)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.error(f"Unhandled exception:", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": str(exc)})

@app.get("/")
async def root():
    return {"message": "Hello, world!"}

# Optional startup logging of env vars (remove if sensitive)
@app.on_event("startup")
async def startup_event():
    logging.info(f"Telegram API set: {'yes' if telegram_api else 'no'}")
    logging.info(f"Chat ID set: {'yes' if chat_id else 'no'}")
    logging.info(f"Webhook URL set: {'yes' if webhook_url else 'no'}")
