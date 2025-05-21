import os
import asyncio
import aiohttp
import time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from collections import deque
from datetime import datetime, timedelta
import uvicorn

app = FastAPI()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or "your_telegram_token_here"
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or "your_chat_id_here"
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY") or "your_webshare_api_key_here"

telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

checking_active = False

proxy_pool = deque()
proxy_stats = {}  # {proxy: {'success': int, 'fail': int, 'avg_response': float}}

usernames_batch_current = []
usernames_batch_old = []
usernames_checked_info = {}  # {username: {'available_since': timestamp, 'last_released': timestamp}}

# Simulated username generator (replace with your real generator or wordlist)
def generate_usernames_batch(size=50):
    # Simple dummy usernames with timestamps
    now = int(time.time())
    return [f"user{now + i}" for i in range(size)]


async def send_telegram(message: str):
    async with aiohttp.ClientSession() as session:
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        async with session.post(f"{telegram_api_url}/sendMessage", json=payload) as resp:
            return await resp.json()


async def fetch_proxies():
    global proxy_pool, proxy_stats
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
            if not items:
                await send_telegram("❌ No proxies found from Webshare API.")
                return False
            count = 0
            for item in items:
                ip = item.get("proxy_address")
                port = item.get("port") or item.get("ports", {}).get("http")
                if ip and port:
                    proxy = f"http://{ip}:{port}"
                    proxy_pool.append(proxy)
                    proxy_stats[proxy] = {"success": 0, "fail": 0, "avg_response": None}
                    count += 1
            await send_telegram(f"✅ Fetched {count} proxies from Webshare.")
            return True


async def validate_proxy(proxy: str, timeout=5):
    test_url = "https://www.tiktok.com"
    start = time.perf_counter()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(test_url, proxy=proxy, timeout=timeout) as resp:
                if resp.status == 200:
                    duration = time.perf_counter() - start
                    return True, duration
    except Exception:
        pass
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
            try:
                proxy_pool.remove(proxy)
                proxy_stats.pop(proxy, None)
            except Exception:
                pass
    await send_telegram(f"🌐 Proxies Validated: {valid_count}/{len(proxy_pool)+valid_count}")


async def check_username(username: str, proxy: str = None):
    # Dummy username checker simulating availability check
    # Replace with your TikTok API or username check logic
    await asyncio.sleep(0.5)  # Simulate network delay
    # Simulate random availability
    available = (hash(username) % 3) == 0

    now = int(time.time())
    if available:
        info = usernames_checked_info.get(username)
        if not info:
            # First time found available
            usernames_checked_info[username] = {
                "available_since": now,
                "last_released": now - 86400,  # dummy last released 1 day ago
            }
        else:
            # Update last checked time
            usernames_checked_info[username]["last_checked"] = now
    else:
        # Remove if not available anymore
        if username in usernames_checked_info:
            usernames_checked_info.pop(username)

    return available


async def checker_loop():
    global checking_active, usernames_batch_current, usernames_batch_old
    while checking_active:
        if not proxy_pool:
            await send_telegram("⚠️ Proxy pool empty, refreshing proxies...")
            await refresh_and_validate_proxies()
            if not proxy_pool:
                await asyncio.sleep(10)
                continue

        if not usernames_batch_current:
            # Load new batch and keep old batch for re-check
            usernames_batch_old = usernames_batch_current
            usernames_batch_current = generate_usernames_batch(50)
            await send_telegram(f"🔄 Loaded new batch of {len(usernames_batch_current)} usernames")

        username = usernames_batch_current.pop(0)
        proxy = None
        try:
            proxy = proxy_pool[0]  # simple rotate
            proxy_pool.rotate(-1)
        except IndexError:
            proxy = None

        available = await check_username(username, proxy)
        if available:
            info = usernames_checked_info.get(username, {})
            duration = int(time.time()) - info.get("available_since", int(time.time()))
            last_released = info.get("last_released", "Unknown")
            msg = f"✅ Username *{username}* is available!\nAvailable for: {duration}s\nLast released: {last_released}"
            await send_telegram(msg)

        await asyncio.sleep(1)  # pacing delay

    await send_telegram("⏹️ Checker stopped.")


@app.post("/webhook")
async def telegram_webhook(request: Request):
    global checking_active, usernames_batch_current, usernames_batch_old
    data = await request.json()
    message = data.get("message") or data.get("edited_message") or {}
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip() if message else ""

    if chat_id != int(TELEGRAM_CHAT_ID):
        return JSONResponse({"status": "ignored"})

    if text == "/start" and not checking_active:
        checking_active = True
        asyncio.create_task(checker_loop())
        await send_telegram("🟢 Checker is starting...")
        return JSONResponse({"status": "started"})

    if text == "/stop" and checking_active:
        checking_active = False
        return await send_telegram("🔴 Checker is stopping...")

    if text == "/proxies":
        await refresh_and_validate_proxies()
        valid = sum(1 for s in proxy_stats.values() if s["success"] > s["fail"])
        total = len(proxy_stats)
        msg = f"🌐 Proxies valid: {valid}/{total}\n"
        msg += "Proxy health:\n"
        for p, stats in proxy_stats.items():
            success = stats["success"]
            fail = stats["fail"]
            avg_resp = stats["avg_response"]
            avg_resp_str = f"{avg_resp:.2f}s" if avg_resp else "N/A"
            msg += f"- {p}: Success {success}, Fail {fail}, Avg Resp {avg_resp_str}\n"
        await send_telegram(msg)
        return JSONResponse({"status": "proxies refreshed"})

    if text == "/usernames":
        # Show current batch info + option to refresh usernames
        batch_len = len(usernames_batch_current)
        old_len = len(usernames_batch_old)
        msg = f"📝 Current batch usernames: {batch_len}\nOld batch usernames (pending recheck): {old_len}\n\n"
        msg += "Send /refreshusernames to load a new batch."
        await send_telegram(msg)
        return JSONResponse({"status": "usernames info sent"})

    if text == "/refreshusernames":
        # Swap batches and refresh
        usernames_batch_old = usernames_batch_current
        usernames_batch_current = generate_usernames_batch(50)
        await send_telegram(f"🔄 Refreshed username batches. New batch size: {len(usernames_batch_current)}")
        return JSONResponse({"status": "usernames refreshed"})

    return JSONResponse({"status": "unknown command"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
