import os
import random
import asyncio
import aiohttp
import logging
from fastapi import FastAPI, Request
from dotenv import load_dotenv
import httpx
from contextlib import asynccontextmanager

load_dotenv()

telegram_api = os.getenv("TELEGRAM_API_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")
webshare_key = os.getenv("WEBSHARE_API_KEY")
webhook_url = os.getenv("WEBHOOK_URL")

logging.basicConfig(level=logging.INFO)

# Themed wordlists (expand as needed)
racing_words = ["drift", "speed", "turbo", "circuit", "track", "pitstop"]
anime_words = ["senpai", "kawaii", "manga", "anime", "otaku", "sakura"]
language_words = ["english", "grammar", "syntax", "accent", "slang"]
crypto_words = ["bitcoin", "crypto", "ledger", "wallet", "token", "block"]
medical_words = ["nurse", "surgery", "clinic", "medkit", "vitals"]
gaming_words = ["frag", "loot", "respawn", "noob", "gamer", "clan"]

all_themes = [
    ("racing", racing_words),
    ("anime", anime_words),
    ("language", language_words),
    ("crypto", crypto_words),
    ("medical", medical_words),
    ("gaming", gaming_words)
]

async def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{telegram_api}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    async with aiohttp.ClientSession() as session:
        await session.post(url, json=payload)

async def set_webhook():
    if not webhook_url:
        logging.error("WEBHOOK_URL env variable not set!")
        return
    url = f"https://api.telegram.org/bot{telegram_api}/setWebhook"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, params={"url": webhook_url})
        if resp.status_code == 200:
            logging.info(f"Webhook set successfully: {await resp.aread()}")
        else:
            logging.error(f"Failed to set webhook: {resp.status_code} {await resp.aread()}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await set_webhook()
    yield

app = FastAPI(lifespan=lifespan)
proxies = []

async def validate_proxies(proxy_list):
    valid = []
    for proxy in proxy_list:
        try:
            conn = aiohttp.ProxyConnector.from_url(f"http://{proxy}")
            async with aiohttp.ClientSession(connector=conn) as session:
                async with session.get("https://www.tiktok.com", timeout=5):
                    valid.append(proxy)
        except:
            continue
    return valid

async def scrape_webshare():
    global proxies
    try:
        url = "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100"
        headers = {"Authorization": f"Token {webshare_key}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                data = await resp.json()
                if "results" not in data:
                    logging.error(f"Webshare API error: {data}")
                    return
                raw = [
                    f"{x['username']}:{x['password']}@{x['proxy_address']}:{x['port']}"
                    for x in data["results"]
                ]
        proxies = await validate_proxies(raw)
        logging.info(f"Validated {len(proxies)} proxies from Webshare")
    except Exception as e:
        logging.error(f"Webshare error: {e}")

async def check_username(username):
    proxy = random.choice(proxies) if proxies else None
    proxy_url = f"http://{proxy}" if proxy else None
    url = f"https://www.tiktok.com/@{username}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, proxy=proxy_url, timeout=10) as resp:
                if resp.status == 404:
                    await send_telegram_message(f"Available: `{username}`")
    except Exception as e:
        logging.warning(f"Error checking {username}: {e}")

async def start_checking():
    await scrape_webshare()
    while True:
        for theme_name, wordlist in all_themes:
            batch = random.sample(wordlist, min(10, len(wordlist)))
            await send_telegram_message(f"\u23f3 Checking theme: *{theme_name}*...")
            await asyncio.gather(*(check_username(u) for u in batch))
            await asyncio.sleep(1)

@app.post("/webhook")
async def telegram_webhook(req: Request):
    data = await req.json()
    if "message" in data:
        text = data["message"].get("text", "")
        if text.lower() == "/start":
            asyncio.create_task(start_checking())
            await send_telegram_message("Checker started.")
    return {"ok": True}
