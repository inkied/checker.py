import os
import random
import asyncio
from typing import List

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import aiohttp
from aiohttp import ClientTimeout
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")

PRIORITY_COUNTRIES = {"US", "DE", "NL", "GB", "CA"}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1",
]

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {WEBSHARE_API_KEY}",
}

PROXY_CHECK_TIMEOUT = 8
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2

proxies = []
working_proxies = []
checking = False
checker_task = None
lock = asyncio.Lock()

def filter_proxies_by_country(proxy_list: List[dict]) -> List[dict]:
    return [p for p in proxy_list if p.get("country") in PRIORITY_COUNTRIES]

async def fetch_proxies_from_webshare(session: aiohttp.ClientSession, page: int = 1, page_size: int = 100):
    url = f"https://proxy.webshare.io/api/proxy/list/?page={page}&page_size={page_size}"
    async with session.get(url, headers=HEADERS) as resp:
        if resp.status != 200:
            raise Exception(f"Failed to fetch proxies: {resp.status}")
        data = await resp.json()
        return data.get("results", []), data.get("count", 0)

async def test_proxy(session: aiohttp.ClientSession, proxy: str) -> bool:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            proxy_url = proxy if proxy.startswith("http") else f"http://{proxy}"
            timeout = ClientTimeout(total=PROXY_CHECK_TIMEOUT)
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            async with session.get("https://httpbin.org/ip", proxy=proxy_url, timeout=timeout, headers=headers) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            await asyncio.sleep(RETRY_BACKOFF_BASE ** attempt)
    return False

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

        filtered = filter_proxies_by_country(all_proxies)
        print(f"Total scraped proxies: {len(all_proxies)} | After country filter: {len(filtered)}")

        valid = []
        sem = asyncio.Semaphore(20)

        async def validate(p):
            async with sem:
                proxy_str = f"http://{p['username']}:{p['password']}@{p['proxy_address']}:{p['ports']['http']}"
                if await test_proxy(session, proxy_str):
                    valid.append(proxy_str)

        await asyncio.gather(*[validate(p) for p in filtered])
        proxies = filtered
        working_proxies = valid
        print(f"Working proxies: {len(working_proxies)}")

def generate_semi_og_username():
    consonants = "bcdfghjklmnpqrstvwxyz"
    vowels = "aeiou"
    patterns = ["cvcv", "cvcc", "ccvc", "ccvv", "cvvc"]
    pattern = random.choice(patterns)
    username = ""
    for ch in pattern:
        if ch == "c":
            username += random.choice(consonants)
        elif ch == "v":
            username += random.choice(vowels)
    return username

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
        "disable_web_page_preview": True
    }
    async with aiohttp.ClientSession() as session:
        try:
            await session.post(url, json=payload)
        except Exception as e:
            print(f"Failed to send telegram message: {e}")

async def check_usernames_loop():
    global checking
    checking = True
    print("Username checking started.")
    async with aiohttp.ClientSession() as session:
        while checking:
            if not working_proxies:
                print("No working proxies available, retrying scrape...")
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

async def handle_command(command: str) -> str:
    global checking, checker_task
    async with lock:
        if command == "/start":
            if checking:
                return "Already running."
            checker_task = asyncio.create_task(check_usernames_loop())
            return "Username checking started."
        elif command == "/stop":
            if not checking:
                return "Not running."
            checking = False
            if checker_task:
                await checker_task
            return "Username checking stopped."
        elif command == "/proxies":
            return f"Total proxies scraped: {len(proxies)}\nWorking proxies: {len(working_proxies)}"
        elif command == "/refresh":
            await scrape_and_validate_proxies()
            return f"Proxies refreshed. Working proxies: {len(working_proxies)}"
        else:
            return "Unknown command."

@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    message = data.get("message") or data.get("edited_message")
    if not message:
        return JSONResponse({"ok": True})

    chat_id = message.get("chat", {}).get("id")
    if str(chat_id) != str(TELEGRAM_CHAT_ID):
        return JSONResponse({"ok": True})

    text = message.get("text", "")
    if text.startswith("/"):
        response = await handle_command(text)
        await send_telegram_message(response)

    return JSONResponse({"ok": True})

@app.get("/")
async def root():
    return {"message": "TikTok Username Checker with FastAPI and Telegram Webhook"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("checker:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
