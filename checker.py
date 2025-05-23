import os
import random
import time
import asyncio
from typing import List, Dict

from fastapi import FastAPI, Request
from dotenv import load_dotenv
from aiohttp import ClientSession, ClientTimeout

load_dotenv()

app = FastAPI()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1",
]

checking = False
working_proxies = []
proxies = []


def generate_semi_og_username():
    c = "bcdfghjklmnpqrstvwxyz"
    v = "aeiou"
    patterns = ["cvcv", "cvcc", "ccvc", "cvvc"]
    pattern = random.choice(patterns)
    return "".join(random.choice(c if ch == "c" else v) for ch in pattern)


async def fetch_proxies(session: ClientSession, page=1, page_size=100):
    url = f"https://proxy.webshare.io/api/proxy/list/?page={page}&page_size={page_size}"
    async with session.get(url, headers={"Authorization": f"Bearer {WEBSHARE_API_KEY}"}) as resp:
        data = await resp.json()
        return data.get("results", [])


async def test_proxy(session: ClientSession, p: Dict):
    try:
        # Dynamic port for HTTP proxy
        ports = p.get("ports", {})
        port = ports.get("http") or list(ports.values())[0]
        proxy_url = f"http://{p['username']}:{p['password']}@{p['proxy_address']}:{port}"
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        start = time.monotonic()
        timeout = ClientTimeout(total=6)
        async with session.get("https://httpbin.org/ip", proxy=proxy_url, headers=headers, timeout=timeout) as resp:
            if resp.status == 200:
                return {"proxy": proxy_url, "speed": time.monotonic() - start}
    except:
        return None


async def scrape_and_sort_proxies():
    global working_proxies, proxies
    working_proxies.clear()
    proxies.clear()
    async with ClientSession() as session:
        proxy_data = await fetch_proxies(session)
        proxies.extend(proxy_data)
        results = await asyncio.gather(*[test_proxy(session, p) for p in proxy_data])
        good = [r for r in results if r]
        sorted_proxies = sorted(good, key=lambda x: x["speed"])
        working_proxies.extend(p["proxy"] for p in sorted_proxies)


async def check_username(session: ClientSession, username: str, proxy: str):
    url = f"https://www.tiktok.com/@{username}"
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    try:
        timeout = ClientTimeout(total=7)
        async with session.get(url, proxy=proxy, headers=headers, timeout=timeout, allow_redirects=False) as resp:
            # 404 means username available
            return resp.status == 404
    except:
        return False


async def send_telegram_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with ClientSession() as session:
        await session.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
        })


async def username_loop():
    global checking
    async with ClientSession() as session:
        while checking:
            if not working_proxies:
                await scrape_and_sort_proxies()
                if not working_proxies:
                    await asyncio.sleep(10)
                    continue

            username = generate_semi_og_username()
            proxy = random.choice(working_proxies)

            if await check_username(session, username, proxy):
                await send_telegram_message(f"✅ Available: <b>@{username}</b>")
            await asyncio.sleep(random.uniform(0.6, 1.2))


@app.post("/webhook")
async def telegram_webhook(req: Request):
    global checking
    data = await req.json()
    message = data.get("message", {})
    chat_id = str(message.get("chat", {}).get("id"))
    if chat_id != TELEGRAM_CHAT_ID:
        return {"ok": False}

    text = message.get("text", "")
    if text == "/start":
        if not checking:
            checking = True
            asyncio.create_task(username_loop())
            await send_telegram_message("✅ Started username checking.")
        else:
            await send_telegram_message("⚠ Already running.")
    elif text == "/stop":
        checking = False
        await send_telegram_message("🛑 Stopped.")
    elif text == "/proxies":
        await send_telegram_message(f"Scraped: {len(proxies)} | Working: {len(working_proxies)}")
    elif text == "/refresh":
        await scrape_and_sort_proxies()
        await send_telegram_message(f"♻ Refreshed proxies. Working: {len(working_proxies)}")
    else:
        await send_telegram_message("❓ Unknown command.")
    return {"ok": True}
