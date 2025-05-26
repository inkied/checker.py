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
webhook_url = os.getenv("WEBHOOK_URL")  # e.g. https://your-app.up.railway.app/webhook

logging.basicConfig(level=logging.INFO)

if not telegram_api or not chat_id:
    logging.error("Telegram API token or chat ID not set in environment variables!")

async def send_telegram_message(message):
    if not telegram_api or not chat_id:
        logging.error("Telegram API token or chat ID missing. Cannot send message.")
        return
    url = f"https://api.telegram.org/bot{telegram_api}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logging.error(f"Failed to send telegram message: {resp.status} {text}")
    except Exception as e:
        logging.error(f"Exception sending telegram message: {e}")

async def set_webhook():
    if not webhook_url:
        logging.error("WEBHOOK_URL env variable not set!")
        return
    if not telegram_api:
        logging.error("Telegram API token not set!")
        return
    url = f"https://api.telegram.org/bot{telegram_api}/setWebhook"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, params={"url": webhook_url})
        if resp.status_code == 200:
            logging.info(f"Webhook set successfully: {resp.text}")
        else:
            logging.error(f"Failed to set webhook: {resp.status_code} {resp.text}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await set_webhook()
    yield
    # Could add shutdown code here if needed

app = FastAPI(lifespan=lifespan)

proxies = []

async def validate_proxies(proxy_list):
    valid = []
    for proxy in proxy_list:
        try:
            connector = aiohttp.ProxyConnector.from_url(f"http://{proxy}")
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.get("https://www.tiktok.com") as resp:
                    if resp.status == 200:
                        valid.append(proxy)
        except Exception:
            continue
    return valid

async def scrape_webshare():
    global proxies
    if not webshare_key:
        logging.error("WEBSHARE_API_KEY not set in environment variables!")
        return
    try:
        url = "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100"
        headers = {"Authorization": f"Token {webshare_key}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as resp:
                try:
                    data = await resp.json()
                except Exception as json_err:
                    logging.error(f"Failed to parse JSON from Webshare: {json_err}")
                    return

                if "results" not in data:
                    logging.error(f"Webshare API error or invalid response: {data}")
                    return

                raw = [
                    f"{x['username']}:{x['password']}@{x['proxy_address']}:{x['port']}"
                    for x in data["results"]
                ]

        proxies = await validate_proxies(raw)
        logging.info(f"Validated {len(proxies)} proxies from Webshare")
    except Exception as e:
        logging.error(f"Webshare scraping error: {e}")

async def check_username(username):
    proxy = random.choice(proxies) if proxies else None
    proxy_url = f"http://{proxy}" if proxy else None
    url = f"https://www.tiktok.com/@{username}"
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, proxy=proxy_url) as resp:
                if resp.status == 404:
                    await send_telegram_message(f"Available: `{username}`")
                elif resp.status != 200:
                    logging.warning(f"Unexpected status {resp.status} for {username}")
    except Exception as e:
        logging.warning(f"Error checking username '{username}': {e}")

def generate_usernames():
    letters = 'abcdefghijklmnopqrstuvwxyz'
    return [''.join(random.choices(letters, k=4)) for _ in range(100)]

check_task = None  # Global task to avoid multiple starts

async def start_checking():
    global check_task
    if check_task and not check_task.done():
        logging.info("Checker already running")
        return
    await scrape_webshare()
    logging.info("Starting username checks...")
    while True:
        usernames = generate_usernames()
        await asyncio.gather(*(check_username(u) for u in usernames))
        await asyncio.sleep(1)

@app.post("/webhook")
async def telegram_webhook(req: Request):
    data = await req.json()
    if "message" in data:
        text = data["message"].get("text", "")
        if text.lower() == "/start":
            global check_task
            if not check_task or check_task.done():
                check_task = asyncio.create_task(start_checking())
                await send_telegram_message("Checker started.")
            else:
                await send_telegram_message("Checker is already running.")
    return {"ok": True}
