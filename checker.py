import os
import asyncio
import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
import random
import time

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")
CAPTCHA_API_KEY = os.getenv("CAPTCHA_API_KEY")

themes = {
    "racing": ["drift", "turbo", "grip", "engine", "revved"],
    "gambling": ["vegas", "poker", "slots", "casino", "chips"],
    "sports": ["soccer", "hoops", "tennis", "goals", "track"],
    "driving": ["drive", "cruise", "speed", "shift", "motor"],
    "school": ["class", "study", "grade", "books", "pupil"],
    "philosophy": ["ethics", "logic", "stoic", "truth", "reason"],
    "science": ["atoms", "quantum", "neuron", "space", "fusion"],
    "anime": ["naruto", "sakura", "goku", "manga", "otaku"],
    "history": ["roman", "empire", "medieval", "caesar", "revolt"],
    "spanish": ["hola", "amigo", "gracias", "fiesta", "loco"],
    "german": ["hallo", "danke", "bier", "liebe", "schnitzel"],
    "french": ["bonjour", "merci", "baguette", "paris", "fromage"],
    "dark": ["void", "abyss", "shade", "grim", "mourn"],
    "fantasy": ["dragon", "mage", "sword", "myth", "spell"],
    "movies": ["matrix", "avenger", "joker", "cinema", "flick"],
    "careers": ["doctor", "lawyer", "pilot", "chef", "artist"],
    "army": ["soldier", "combat", "ranks", "drill", "warrior"],
    "military": ["tanks", "base", "navy", "airforce", "marine"],
    "learning": ["read", "focus", "learn", "mind", "note"],
    "politics": ["vote", "party", "debate", "policy", "law"]
}

proxy_list = []
active_checker = False
current_theme = ""
current_batch = []

app = FastAPI()
bot = Bot(token=TELEGRAM_TOKEN)

async def fetch_proxies():
    global proxy_list
    url = "https://proxy.webshare.io/api/v2/proxy/list/download/"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            text = await resp.text()
            proxy_list = [line.strip() for line in text.splitlines() if line.strip()]
    print(f"Fetched {len(proxy_list)} proxies.")

async def check_username(username, session, proxy):
    url = f"https://www.tiktok.com/@{username}"
    try:
        async with session.get(url, proxy=proxy, timeout=10) as resp:
            if resp.status == 404:
                return "available"
            return "taken"
    except:
        return "error"

async def process_batch(theme, batch):
    global proxy_list
    results = []
    async with aiohttp.ClientSession() as session:
        for username in batch:
            proxy = random.choice(proxy_list) if proxy_list else None
            proxy_uri = f"http://{proxy}" if proxy else None
            status = await check_username(username, session, proxy_uri)
            results.append((username, status))
            await asyncio.sleep(random.uniform(0.4, 1.0))
    return results

async def checker_loop():
    global active_checker, current_theme, current_batch
    while active_checker:
        for theme, words in themes.items():
            current_theme = theme
            current_batch = random.sample(words, min(5, len(words)))
            results = await process_batch(theme, current_batch)
            msg = f"ð Checking *{theme.title()}* theme:
"
            for username, status in results:
                emoji = "â" if status == "available" else "â" if status == "taken" else "â ï¸"
                msg += f"{emoji} `{username}`
"
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="Markdown")
            await asyncio.sleep(random.uniform(20, 40))

@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    if "message" in data:
        text = data["message"].get("text", "")
        if text == "/start":
            global active_checker
            active_checker = True
            asyncio.create_task(checker_loop())
            return JSONResponse({"ok": True})
        elif text == "/stop":
            active_checker = False
            return JSONResponse({"ok": True})
        elif text == "/proxies":
            await fetch_proxies()
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"ð Proxies refreshed: {len(proxy_list)} active.")
            return JSONResponse({"ok": True})
        elif text == "/usernames":
            msg = f"ð¯ Current batch ({current_theme}):
"
            msg += "
".join([f"`{u}`" for u in current_batch])
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="Markdown")
            return JSONResponse({"ok": True})
    return JSONResponse({"ok": True})

@app.on_event("startup")
async def on_startup():
    await fetch_proxies()
    if WEBHOOK_URL:
        await bot.set_webhook(url=WEBHOOK_URL)

if __name__ == "__main__":
    uvicorn.run("checker:app", host="0.0.0.0", port=8000)
