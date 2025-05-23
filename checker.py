import os
import asyncio
import aiohttp
import random
import time
from aiohttp import ClientTimeout
from fastapi import FastAPI, Request
from dotenv import load_dotenv
from typing import List

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")

WEBHOOK_DOMAIN = "https://checkerpy-production-a7e1.up.railway.app"
WEBHOOK_PATH = f"/telegram_webhook/{TELEGRAM_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_DOMAIN}{WEBHOOK_PATH}"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
    " Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)"
    " Version/16.1 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko)"
    " Version/15.0 Mobile/15E148 Safari/604.1",
]

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {WEBSHARE_API_KEY}",
}

PROXY_CHECK_TIMEOUT = 8
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds

app = FastAPI()

proxies = []
working_proxies = []
checking = False

def generate_semi_og_username():
    consonants = "bcdfghjklmnpqrstvwxyz"
    vowels = "aeiou"
    patterns = ["cvcv", "cvcc", "ccvc", "ccvv", "cvvc"]
    pattern = random.choice(patterns)
    username = ""
    for ch in pattern:
        username += random.choice(consonants) if ch == "c" else random.choice(vowels)
    return username

async def fetch_proxies_from_webshare(session: aiohttp.ClientSession, page: int = 1, page_size: int = 100):
    url = f"https://proxy.webshare.io/api/proxy/list/?page={page}&page_size={page_size}"
    async with session.get(url, headers=HEADERS) as resp:
        if resp.status != 200:
            raise Exception(f"Failed to fetch proxies: {resp.status}")
        data = await resp.json()
        return data.get("results", []), data.get("count", 0)

async def test_proxy(session: aiohttp.ClientSession, proxy: str) -> (bool, float):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            proxy_url = proxy if proxy.startswith("http") else f"http://{proxy}"
            timeout = ClientTimeout(total=PROXY_CHECK_TIMEOUT)
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            start = time.perf_counter()
            async with session.get("https://httpbin.org/ip", proxy=proxy_url, timeout=timeout, headers=headers) as resp:
                if resp.status == 200:
                    speed = time.perf_counter() - start
                    return True, speed
        except Exception:
            await asyncio.sleep(RETRY_BACKOFF_BASE ** attempt)
    return False, 0.0

async def scrape_and_validate_proxies():
    global proxies, working_proxies
    async with aiohttp.ClientSession() as session:
        all_proxies = []
        page = 1
        while True:
            try:
                results, count = await fetch_proxies_from_webshare(session, page=page)
            except Exception as e:
                print(f"Error scraping proxies: {e}")
                break
            if not results:
                break
            all_proxies.extend(results)
            if len(all_proxies) >= count:
                break
            page += 1
        print(f"Scraped total proxies: {len(all_proxies)}")

        valid = []
        sem = asyncio.Semaphore(20)

        async def validate(p):
            async with sem:
                # Use any available port from 'ports' dict, try them until success
                ports = p.get("ports", {})
                proxy_address = p.get("proxy_address")
                username = p.get("username")
                password = p.get("password")
                for port in ports.values():
                    proxy_str = f"http://{username}:{password}@{proxy_address}:{port}"
                    ok, speed = await test_proxy(session, proxy_str)
                    if ok:
                        valid.append((proxy_str, speed))
                        break

        await asyncio.gather(*[validate(p) for p in all_proxies])

        # Sort by measured speed (lower is better)
        valid.sort(key=lambda x: x[1])
        working_proxies = [v[0] for v in valid]
        proxies = all_proxies
        print(f"Working proxies: {len(working_proxies)}")

async def check_username_availability(session: aiohttp.ClientSession, username: str, proxy: str = None) -> bool:
    url = f"https://www.tiktok.com/@{username}"
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    try:
        timeout = ClientTimeout(total=7)
        async with session.get(url, proxy=proxy, headers=headers, timeout=timeout, allow_redirects=False) as resp:
            if resp.status == 404:
                return True
            return False
    except Exception:
        return False

async def send_telegram_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    async with aiohttp.ClientSession() as session:
        try:
            await session.post(url, json=payload)
        except Exception as e:
            print(f"Failed to send telegram message: {e}")

async def check_usernames_loop():
    global checking
    checking = True
    async with aiohttp.ClientSession() as session:
        while checking:
            if not working_proxies:
                print("No working proxies, scraping again...")
                await scrape_and_validate_proxies()
                if not working_proxies:
                    print("Still no working proxies, waiting 30 seconds...")
                    await asyncio.sleep(30)
                    continue
            username = generate_semi_og_username()
            proxy = random.choice(working_proxies)
            is_available = await check_username_availability(session, username, proxy=proxy)
            if is_available:
                print(f"Available username found: {username}")
                await send_telegram_message(f"✅ Available: @{username}")
            await asyncio.sleep(random.uniform(0.7, 1.5))

async def handle_command(command: str):
    global checking
    if command == "/start":
        if checking:
            return "Already running."
        asyncio.create_task(check_usernames_loop())
        return "Username checking started."
    elif command == "/stop":
        checking = False
        return "Username checking stopped."
    elif command == "/proxies":
        return f"Total scraped proxies: {len(proxies)}\nWorking proxies: {len(working_proxies)}"
    elif command == "/refresh":
        await scrape_and_validate_proxies()
        return f"Proxies refreshed. Working proxies: {len(working_proxies)}"
    else:
        return "Unknown command."

@app.on_event("startup")
async def startup_event():
    async with aiohttp.ClientSession() as session:
        set_webhook_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={WEBHOOK_URL}"
        try:
            async with session.get(set_webhook_url) as resp:
                data = await resp.json()
                if data.get("ok"):
                    print(f"Webhook set successfully: {WEBHOOK_URL}")
                else:
                    print(f"Failed to set webhook: {data}")
        except Exception as e:
            print(f"Exception setting webhook: {e}")
    # Scrape proxies at startup
    await scrape_and_validate_proxies()

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    data = await request.json()
    message = data.get("message")
    if not message:
        return {"ok": True}
    text = message.get("text", "")
    chat_id = message["chat"]["id"]
    if chat_id != int(TELEGRAM_CHAT_ID):
        return {"ok": True}
    if text.startswith("/"):
        response = await handle_command(text)
        await send_telegram_message(response)
    return {"ok": True}
    return {"ok": True}
