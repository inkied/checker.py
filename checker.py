from fastapi import FastAPI, Request
import aiohttp
import os
import asyncio

app = FastAPI()

# Your Telegram Bot credentials
TELEGRAM_TOKEN = "7698527405:AAE8z3q9epDTXZFZMNZRW9ilU-ayevMQKVA"
TELEGRAM_CHAT_ID = "7755395640"
TELEGRAM_API = f"https://api.telegram.org/bot7698527405:AAE8z3q9epDTXZFZMNZRW9ilU-ayevMQKVA"

# ========== ROUTES ==========

@app.get("/")
async def root():
    return {"status": "✅ Server running"}

@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        print("📨 Incoming update:", data)

        message = data.get("message") or data.get("edited_message")
        if not message:
            return {"ok": True}

        text = message.get("text", "").strip()
        chat_id = message["chat"]["id"]

        if text.lower() == "/start":
            await send_message(chat_id, "✅ Checker bot is active and listening!")

        return {"ok": True}
    except Exception as e:
        print("❌ Webhook error:", e)
        return {"ok": False, "error": str(e)}

# ========== SEND MESSAGE ==========

async def send_message(chat_id, text):
    async with aiohttp.ClientSession() as session:
        await session.post(f"{TELEGRAM_API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text
        })

# ========== RUN ==========

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("checker:app", host="0.0.0.0", port=8000)
