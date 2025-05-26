import os
import random
import asyncio
import aiohttp
import logging
from fastapi import FastAPI, Request
from dotenv import load_dotenv

load_dotenv()

telegram_api = os.getenv("TELEGRAM_API_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")
webshare_key = os.getenv("WEBSHARE_API_KEY")

app = FastAPI()
proxies = []

logging.basicConfig(level=logging.INFO)

async def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{telegram_api}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    async with aiohttp.ClientSession() as session:
        await session.post(url, json=payload)

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
                text = await resp.text()
                try:
                    data = await resp.json()
                except Exception as json_err:
                    logging.error(f"Failed to parse JSON: {json_err}")
                    return

                if "results" not in data:
                    logging.error(f"Webshare API error: {data}")
                    return

                raw = [
                    f"{x['username']}:{x['password']}@{x['proxy_address']}:{x['port']}"
                    for x in data["results"]
                ]

        proxies = await validate_proxies(raw)
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

def generate_usernames():
    letters = 'abcdefghijklmnopqrstuvwxyz'
    return [''.join(random.choices(letters, k=4)) for _ in range(100)]

async def start_checking():
    await scrape_webshare()
    while True:
        usernames = generate_usernames()
        await asyncio.gather(*(check_username(u) for u in usernames))
        await asyncio.sleep(1)

@app.post("/webhook")
async def telegram_webhook(req: Request):
    data = await req.json()
    if "message" in data:
        text = data["message"].get("text", "")
        if text.lower() == "start":
            asyncio.create_task(start_checking())
            await send_telegram_message("Checker started.")
    return {"ok": True}
