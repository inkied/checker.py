import os
import aiohttp
import asyncio
import random
import string
import itertools
import logging
from fastapi import FastAPI, Request
from dotenv import load_dotenv
from typing import List
from aiohttp import ClientSession
from starlette.responses import JSONResponse

load_dotenv()

telegram_api = os.getenv("TELEGRAM_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")
webshare_key = os.getenv("WEBSHARE_API_KEY")
telegram_webhook = os.getenv("TELEGRAM_WEBHOOK_URL")

app = FastAPI()

proxies = []
available_usernames = []
running = False
themes = ["career", "philosophy", "gaming", "jail", "nerdy", "feelings", "market"]

MAX_CONCURRENT = 40
BATCH_SIZE = 5
PROXY_TIMEOUT = 7

async def send_telegram_message(text: str, buttons=None):
    url = f"https://api.telegram.org/bot{telegram_api}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    async with aiohttp.ClientSession() as session:
        await session.post(url, json=payload)

async def scrape_webshare():
    global proxies
    try:
        url = "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100"
        headers = {"Authorization": f"Token {webshare_key}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                data = await resp.json()
                raw = [f"{x['username']}:{x['password']}@{x['proxy_address']}:{x['port']}" for x in data["results"]]
        proxies = await validate_proxies(raw)
    except Exception as e:
        logging.error(f"Webshare error: {e}")

async def validate_proxies(proxy_list):
    valid = []
    async def test(proxy):
        try:
            proxy_url = f"http://{proxy}"
            async with aiohttp.ClientSession() as session:
                async with session.get("https://www.tiktok.com", proxy=proxy_url, timeout=PROXY_TIMEOUT):
                    valid.append(proxy_url)
        except:
            pass
    await asyncio.gather(*[test(p) for p in proxy_list])
    return valid

def generate_username(theme):
    base = {
        "career": ["ceo", "law", "dev", "cfo", "biz"],
        "philosophy": ["zen", "dao", "vibe", "life", "mind"],
        "gaming": ["fps", "ggr", "aim", "noob", "clan"],
        "jail": ["cell", "bars", "trap", "fel", "unit"],
        "nerdy": ["byte", "code", "ram", "nerd", "sys"],
        "feelings": ["sad", "luv", "mood", "rawr", "hurt"],
        "market": ["deal", "buy", "cart", "sell", "rack"]
    }
    seed = random.choice(base.get(theme, ["user", "test"]))
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4 - len(seed)))
    return (seed + suffix)[:4]

async def check_username(session: ClientSession, username: str, proxy: str):
    try:
        url = f"https://www.tiktok.com/@{username}"
        async with session.get(url, proxy=proxy, timeout=PROXY_TIMEOUT) as resp:
            if resp.status == 404:
                return username
    except:
        pass
    return None

async def batch_check():
    global available_usernames
    theme_cycle = itertools.cycle(themes)

    while running:
        theme = next(theme_cycle)
        await send_telegram_message(f"🔍 Checking themed batch: *{theme}*")
        async with aiohttp.ClientSession() as session:
            tasks = []
            proxy_cycle = itertools.cycle(proxies)
            for _ in range(BATCH_SIZE):
                username = generate_username(theme)
                proxy = next(proxy_cycle)
                tasks.append(check_username(session, username, proxy))
            results = await asyncio.gather(*tasks)
            found = [r for r in results if r]
            if found:
                available_usernames.extend(found)
                await send_telegram_message(
                    "*Available usernames:*\n" + "\n".join(found),
                    buttons=[[{"text": "Claim", "callback_data": "claim"}]]
                )
        await asyncio.sleep(2)

@app.post("/webhook")
async def telegram_webhook_handler(request: Request):
    global running
    data = await request.json()

    if "message" in data:
        text = data["message"]["text"]
        if text == "/start":
            buttons = [[
                {"text": "Start", "callback_data": "start"},
                {"text": "Stop", "callback_data": "stop"},
                {"text": "Refresh Proxies", "callback_data": "refresh"}
            ]]
            await send_telegram_message("🤖 Bot Ready", buttons)
    elif "callback_query" in data:
        query = data["callback_query"]
        cmd = query["data"]
        if cmd == "start":
            if not running:
                running = True
                await send_telegram_message("✅ Started")
                asyncio.create_task(batch_check())
        elif cmd == "stop":
            running = False
            await send_telegram_message("⏹️ Stopped")
        elif cmd == "refresh":
            await scrape_webshare()
            await send_telegram_message(f"🔁 Proxies refreshed. {len(proxies)} working.")
        elif cmd == "claim":
            await send_telegram_message("⚠️ Manual claiming required.")

    return JSONResponse({"ok": True})

@app.on_event("startup")
async def on_startup():
    await scrape_webshare()
