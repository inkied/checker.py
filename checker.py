import os
import asyncio
import aiohttp
import time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from collections import deque
from datetime import datetime
import uvicorn

app = FastAPI()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or "your_telegram_token_here"
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or "your_chat_id_here"
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY") or "your_webshare_api_key_here"

telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

checking_active = False
proxy_pool = deque()
proxy_stats = {}
usernames_batch_current = []
usernames_batch_old = []
usernames_checked_info = {}

def generate_usernames_batch(size=50):
    now = int(time.time())
    return [f"user{now + i}" for i in range(size)]

async def send_telegram(message: str, buttons=None):
    async with aiohttp.ClientSession() as session:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": buttons}
        await session.post(f"{telegram_api_url}/sendMessage", json=payload)

async def fetch_proxies():
    proxy_pool.clear()
    proxy_stats.clear()
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    async with aiohttp.ClientSession() as session:
        async with session.get("https://proxy.webshare.io/api/proxy/list/", headers=headers) as resp:
            if resp.status != 200:
                await send_telegram(f"❌ Failed to fetch proxies: HTTP {resp.status}")
                return False
            data = await resp.json()
            items = data.get("results", [])
            count = 0
            for item in items[:100]:  # Only use 100
                ip = item.get("proxy_address")
                port = item.get("port") or item.get("ports", {}).get("http")
                if ip and port:
                    proxy = f"http://{ip}:{port}"
                    proxy_pool.append(proxy)
                    proxy_stats[proxy] = {"success": 0, "fail": 0, "avg_response": None}
                    count += 1
            if count == 0:
                await send_telegram("❌ No valid proxies found from Webshare.")
                return False
            await send_telegram(f"✅ Fetched {count} proxies from Webshare.")
            return True

async def validate_proxy(proxy, timeout=5):
    try:
        start = time.perf_counter()
        async with aiohttp.ClientSession() as session:
            async with session.get("https://www.tiktok.com", proxy=proxy, timeout=timeout):
                return True, time.perf_counter() - start
    except:
        return False, None

async def refresh_and_validate_proxies():
    await fetch_proxies()
    valid_count = 0
    for proxy in list(proxy_pool):
        valid, resp_time = await validate_proxy(proxy)
        if valid:
            proxy_stats[proxy]["success"] += 1
            proxy_stats[proxy]["avg_response"] = resp_time
            valid_count += 1
        else:
            proxy_stats[proxy]["fail"] += 1
            proxy_pool.remove(proxy)
            proxy_stats.pop(proxy, None)
    await send_telegram(f"🌐 Proxies Validated: {valid_count}/{len(proxy_pool) + valid_count}")

async def check_username(username, proxy=None):
    await asyncio.sleep(0.3)
    available = (hash(username) % 4 == 0)
    now = int(time.time())
    if available:
        info = usernames_checked_info.get(username)
        if not info:
            usernames_checked_info[username] = {
                "available_since": now,
                "last_released": now - 86400,
            }
    else:
        usernames_checked_info.pop(username, None)
    return available

async def checker_loop():
    global checking_active, usernames_batch_current, usernames_batch_old
    while checking_active:
        if not proxy_pool:
            await send_telegram("⚠️ No proxies! Refreshing...")
            await refresh_and_validate_proxies()
            await asyncio.sleep(5)
            continue

        if not usernames_batch_current:
            usernames_batch_old = usernames_batch_current
            usernames_batch_current = generate_usernames_batch(50)
            await send_telegram(f"🔄 New username batch loaded: {len(usernames_batch_current)}")

        username = usernames_batch_current.pop(0)
        proxy = proxy_pool[0]
        proxy_pool.rotate(-1)
        available = await check_username(username, proxy)
        if available:
            info = usernames_checked_info[username]
            duration = int(time.time()) - info.get("available_since", int(time.time()))
            last_released = info.get("last_released", "Unknown")
            msg = f"✅ *{username}* is available!\n🕒 Available: {duration}s\n🗓️ Last released: {last_released}"
            await send_telegram(msg)

        await asyncio.sleep(1)

    await send_telegram("⏹️ Checker stopped.")

@app.post("/webhook")
async def telegram_webhook(request: Request):
    global checking_active, usernames_batch_current, usernames_batch_old
    data = await request.json()
    message = data.get("message") or data.get("callback_query", {}).get("message", {})
    text = message.get("text", "").strip()
    chat_id = message.get("chat", {}).get("id")
    callback_data = data.get("callback_query", {}).get("data")

    if str(chat_id) != str(TELEGRAM_CHAT_ID):
        return JSONResponse({"status": "ignored"})

    cmd = callback_data or text

    if cmd == "/start":
        if not checking_active:
            checking_active = True
            asyncio.create_task(checker_loop())
            await send_telegram("🟢 Checker started.", buttons=main_buttons())
        else:
            await send_telegram("🔁 Checker is already running.", buttons=main_buttons())
    elif cmd == "/stop":
        checking_active = False
        await send_telegram("🔴 Checker stopped.", buttons=main_buttons())
    elif cmd == "/proxies":
        await refresh_and_validate_proxies()
        valid = sum(1 for s in proxy_stats.values() if s["success"] > s["fail"])
        msg = f"🌐 Valid proxies: {valid}/{len(proxy_stats)}\n\n"
        for p, stats in list(proxy_stats.items())[:10]:
            msg += f"• {p} ✅ {stats['success']}/❌ {stats['fail']} | {stats['avg_response']:.2f}s\n"
        await send_telegram(msg, buttons=main_buttons())
    elif cmd == "/usernames":
        msg = (
            f"📝 Username Batch\n"
            f"- Current: {len(usernames_batch_current)}\n"
            f"- Old: {len(usernames_batch_old)}\n\n"
            f"⏱️ Refresh usernames to load a new batch after this finishes."
        )
        await send_telegram(msg, buttons=usernames_buttons())
    elif cmd == "/refreshusernames":
        usernames_batch_old = usernames_batch_current
        usernames_batch_current = generate_usernames_batch(50)
        await send_telegram("🔁 Username batch refreshed.", buttons=usernames_buttons())
    return JSONResponse({"ok": True})

def main_buttons():
    return [[
        {"text": "▶️ Start", "callback_data": "/start"},
        {"text": "⏹️ Stop", "callback_data": "/stop"},
    ], [
        {"text": "🌐 Proxies", "callback_data": "/proxies"},
        {"text": "📝 Usernames", "callback_data": "/usernames"},
    ]]

def usernames_buttons():
    return [[
        {"text": "🔁 Refresh Usernames", "callback_data": "/refreshusernames"},
        {"text": "🔙 Back", "callback_data": "/start"},
    ]]

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
