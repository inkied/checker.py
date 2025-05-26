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
webhook_url = os.getenv("WEBHOOK_URL")  # Your Railway webhook URL

logging.basicConfig(level=logging.INFO)

THEMED_WORDLIST_URL = "https://raw.githubusercontent.com/inkied/checker.py/main/themed_words.txt"

app = FastAPI()

proxies = []
themed_words = {}
checking_task = None

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
            logging.info(f"Webhook set successfully: {await resp.text()}")
        else:
            logging.error(f"Failed to set webhook: {resp.status_code} {await resp.text()}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup code here: set webhook and load themed words
    await set_webhook()
    global themed_words
    themed_words = await load_themed_wordlist()
    logging.info(f"Loaded themed words with {sum(len(v) for v in themed_words.values())} total words")
    yield
    # Shutdown code here (if any)

app = FastAPI(lifespan=lifespan)

async def load_themed_wordlist():
    themed_words_local = {}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(THEMED_WORDLIST_URL) as resp:
                if resp.status != 200:
                    logging.error(f"Failed to download wordlist: HTTP {resp.status}")
                    return themed_words_local
                text = await resp.text()

        current_category = None
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.endswith(":"):
                current_category = line[:-1].lower()
                themed_words_local[current_category] = []
            elif current_category:
                words = [w.strip() for w in line.split(",") if w.strip()]
                themed_words_local[current_category].extend(words)
    except Exception as e:
        logging.error(f"Error loading themed wordlist: {e}")
    return themed_words_local

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

def generate_usernames(count=100):
    all_words = []
    for words in themed_words.values():
        all_words.extend(words)
    if not all_words:
        return []
    return random.choices(all_words, k=count)

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
        usernames = generate_usernames(100)
        if not usernames:
            logging.warning("No usernames generated. Waiting to retry.")
            await asyncio.sleep(10)
            continue
        await asyncio.gather(*(check_username(u) for u in usernames))
        await asyncio.sleep(1)

@app.post("/webhook")
async def telegram_webhook(req: Request):
    global checking_task
    data = await req.json()
    if "message" in data:
        text = data["message"].get("text", "")
        if text.lower() == "/start":
            if checking_task and not checking_task.done():
                await send_telegram_message("Checker is already running.")
            else:
                checking_task = asyncio.create_task(start_checking())
                await send_telegram_message("Checker started.")
        elif text.lower() == "/stop":
            if checking_task:
                checking_task.cancel()
                checking_task = None
                await send_telegram_message("Checker stopped.")
            else:
                await send_telegram_message("Checker is not running.")
    return {"ok": True}
