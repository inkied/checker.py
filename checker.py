import os
import asyncio
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
from typing import List, Optional

logging.basicConfig(level=logging.INFO)
app = FastAPI()

# Environment variables
TG_API_TOKEN = os.getenv("TELEGRAM_API")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not all([TG_API_TOKEN, WEBHOOK_URL, WEBSHARE_API_KEY, TG_CHAT_ID]):
    raise ValueError("Missing required environment variables")

TG_API_URL = f"https://api.telegram.org/bot{TG_API_TOKEN}"
THEMED_WORDS_URL = "https://raw.githubusercontent.com/inkied/checker.py/main/themed_words.txt"

# Global state
checking = False
proxies: List[str] = []
usernames_to_check: List[str] = []

MAX_CONCURRENT_CHECKS = 5  # healthy concurrency for mobile

# --- Helpers ---

async def set_telegram_webhook():
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{TG_API_URL}/setWebhook", params={"url": WEBHOOK_URL})
        if resp.status_code == 200:
            logging.info("✅ Telegram webhook set successfully")
        else:
            logging.error(f"Failed to set webhook: {resp.status_code} {resp.text}")

async def get_webshare_proxies() -> List[str]:
    url = "https://proxy.webshare.io/api/proxy/list/"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            proxy_list = []
            for p in data["results"]:
                proto = "http" if "http" in p["protocols"] else p["protocols"][0]
                proxy_list.append(f"{proto}://{p['username']}:{p['password']}@{p['proxy_address']}:{p['ports'][proto]}")
            logging.info(f"Loaded {len(proxy_list)} proxies from Webshare")
            return proxy_list
        else:
            logging.error(f"Failed to fetch proxies: {resp.status_code} {resp.text}")
            return []

async def fetch_themed_usernames() -> List[str]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(THEMED_WORDS_URL)
        if resp.status_code == 200:
            lines = resp.text.splitlines()
            names = []
            for line in lines:
                if ":" in line:
                    _, words = line.split(":", 1)
                    names.extend(w.strip() for w in words.split(","))
            logging.info(f"Loaded {len(names)} themed usernames")
            return names
        else:
            logging.error(f"Failed to load themed usernames: {resp.status_code}")
            return []

async def check_username(username: str, proxy: Optional[str]) -> bool:
    url = f"https://www.tiktok.com/@{username}"
    timeout = httpx.Timeout(10.0, connect=5.0)
    async with httpx.AsyncClient(proxies=proxy, timeout=timeout) as client:
        try:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 404:
                return True
            elif resp.status_code == 200:
                return False
            else:
                logging.warning(f"Unexpected status {resp.status_code} for {username}")
                return False
        except Exception as e:
            logging.warning(f"Error checking {username} with proxy {proxy}: {e}")
            return False

async def send_telegram_message(text: str):
    async with httpx.AsyncClient() as client:
        await client.post(f"{TG_API_URL}/sendMessage", data={"chat_id": TG_CHAT_ID, "text": text})

async def proxy_health_check(proxy: str) -> bool:
    test_url = "https://www.google.com"
    timeout = httpx.Timeout(10.0, connect=5.0)
    async with httpx.AsyncClient(proxies=proxy, timeout=timeout) as client:
        try:
            resp = await client.get(test_url)
            return resp.status_code == 200
        except:
            return False

async def refresh_proxies():
    global proxies
    fresh_proxies = await get_webshare_proxies()
    healthy_proxies = []
    for p in fresh_proxies:
        if await proxy_health_check(p):
            healthy_proxies.append(p)
    proxies = healthy_proxies
    logging.info(f"Refreshed proxies. {len(proxies)} healthy proxies loaded.")

async def username_checker_worker(worker_id: int):
    global checking
    proxy_index = worker_id
    while checking:
        if not usernames_to_check:
            await asyncio.sleep(2)
            continue
        username = usernames_to_check.pop(0)
        proxy = proxies[proxy_index % len(proxies)] if proxies else None
        proxy_index += MAX_CONCURRENT_CHECKS
        available = await check_username(username, proxy)
        if available:
            await send_telegram_message(f"✅ Available username: {username}")
        await asyncio.sleep(1)  # rate limit

async def start_checking():
    global checking
    checking = True
    # Refresh proxies before starting
    await refresh_proxies()
    # Load usernames fresh
    global usernames_to_check
    usernames_to_check = await fetch_themed_usernames()

    # Start workers
    tasks = []
    for i in range(MAX_CONCURRENT_CHECKS):
        tasks.append(asyncio.create_task(username_checker_worker(i)))

    await asyncio.gather(*tasks)

# --- FastAPI routes ---

@app.on_event("startup")
async def startup():
    logging.info("App starting up...")
    await set_telegram_webhook()

@app.post("/webhook")
async def telegram_webhook(req: Request):
    global checking
    data = await req.json()
    if "message" in data:
        msg = data["message"]
        text = msg.get("text", "").strip().lower()
        if text == "/start":
            if checking:
                await send_telegram_message("Already running.")
            else:
                await send_telegram_message("Starting username checks...")
                asyncio.create_task(start_checking())
        elif text == "/stop":
            if checking:
                checking = False
                await send_telegram_message("Stopped username checking.")
            else:
                await send_telegram_message("Not currently running.")
        else:
            await send_telegram_message("Send /start to begin checking and /stop to stop.")
    return JSONResponse({"ok": True})
