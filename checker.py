import os
import asyncio
import aiohttp
import random
import string
from fastapi import FastAPI, Request
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")
APP_URL = os.getenv("APP_URL")

PROXY_POOL = []
BAD_PROXIES = set()
PROXY_LOCK = asyncio.Lock()

CHECKING = False
BATCH_SIZE = 5000
CONCURRENCY = 20

AVAILABLE_USERNAMES = set()
USERNAME_QUEUE = asyncio.Queue()
USERNAMES_CHECKED = 0

app = FastAPI()


def generate_username():
    # 4 char username, no digit at start, letters + digits mix
    chars = string.ascii_lowercase + string.digits
    while True:
        username = ''.join(random.choice(chars) for _ in range(4))
        if not username[0].isdigit():
            return username


async def fetch_proxies():
    global PROXY_POOL, BAD_PROXIES
    url = "https://proxy.webshare.io/api/proxy/list/?page=1&page_size=100"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            data = await resp.json()
            proxies = []
            for proxy in data.get("results", []):
                ip = proxy["proxy_address"]
                port = proxy["port"]
                proxy_str = f"http://{ip}:{port}"
                proxies.append(proxy_str)
            async with PROXY_LOCK:
                PROXY_POOL = proxies
                BAD_PROXIES = set()
    print(f"✅ Loaded {len(PROXY_POOL)} proxies from Webshare.")


async def replenish_proxies_if_needed():
    async with PROXY_LOCK:
        if len(PROXY_POOL) - len(BAD_PROXIES) < 10:
            print("⚠️ Proxy count low, replenishing proxies...")
            await fetch_proxies()


async def send_telegram_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    async with aiohttp.ClientSession() as session:
        await session.post(url, json=payload)


async def check_username(session, username, proxy):
    global USERNAMES_CHECKED
    if username.isdigit():
        USERNAMES_CHECKED += 1
        return False

    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.45 Safari/537.36",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-US",
        "Content-Type": "application/json"
    }

    try:
        async with session.head(url, headers=headers, proxy=proxy, timeout=10) as resp:
            status = resp.status
            USERNAMES_CHECKED += 1
            if status == 404:
                # Available or banned
                if username not in AVAILABLE_USERNAMES:
                    AVAILABLE_USERNAMES.add(username)
                    with open("Available.txt", "a") as f:
                        f.write(username + "\n")
                    await send_telegram_message(f"✅ Available username found: <b>{username}</b>")
                return True
            elif status == 200:
                # Unavailable
                return False
            else:
                # Unknown status - treat as failure
                return False
    except Exception:
        # On proxy error or timeout, mark proxy bad
        async with PROXY_LOCK:
            BAD_PROXIES.add(proxy)
        return False


async def worker():
    global CHECKING
    async with aiohttp.ClientSession() as session:
        while CHECKING:
            try:
                username = await USERNAME_QUEUE.get()
            except asyncio.CancelledError:
                break
            if username is None:
                break
            async with PROXY_LOCK:
                valid_proxies = [p for p in PROXY_POOL if p not in BAD_PROXIES]
            if not valid_proxies:
                await replenish_proxies_if_needed()
                await asyncio.sleep(5)
                USERNAME_QUEUE.put_nowait(username)
                continue
            proxy = random.choice(valid_proxies)
            await check_username(session, username, proxy)
            USERNAME_QUEUE.task_done()


async def generate_batch():
    USERNAME_QUEUE._queue.clear()
    AVAILABLE_USERNAMES.clear()
    global USERNAMES_CHECKED
    USERNAMES_CHECKED = 0
    print(f"🧰 Generating batch of {BATCH_SIZE} usernames...")
    for _ in range(BATCH_SIZE):
        USERNAME_QUEUE.put_nowait(generate_username())
    print(f"✅ Batch loaded to queue.")


async def main_loop():
    global CHECKING
    await fetch_proxies()
    await generate_batch()
    CHECKING = True
    workers = [asyncio.create_task(worker()) for _ in range(CONCURRENCY)]

    while CHECKING:
        await asyncio.sleep(1)
        # Replenish proxies if needed
        await replenish_proxies_if_needed()

        # Auto refresh batch when done
        if USERNAME_QUEUE.empty():
            await send_telegram_message("⚡ Batch finished, generating new batch...")
            await generate_batch()

    for w in workers:
        w.cancel()
    await asyncio.gather(*workers, return_exceptions=True)


@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    if "message" in data:
        message = data["message"]
        text = message.get("text", "")
        chat_id = message["chat"]["id"]
        if chat_id != TELEGRAM_CHAT_ID:
            return {"ok": True}

        global CHECKING

        if text.startswith("/start"):
            if CHECKING:
                await send_telegram_message("⚠️ Already running!")
            else:
                asyncio.create_task(main_loop())
                await send_telegram_message("✅ Bot started! Checking usernames...")
        elif text.startswith("/stop"):
            CHECKING = False
            await send_telegram_message("🛑 Bot stopped.")
        elif text.startswith("/proxies"):
            async with PROXY_LOCK:
                total = len(PROXY_POOL)
                bad = len(BAD_PROXIES)
                good = total - bad
            await send_telegram_message(
                f"🛡 Proxy health:\nGood: {good}\nBad: {bad}\nTotal: {total}"
            )
            if good < 10:
                await send_telegram_message("⚠️ Proxy count low, replenishing...")
                await fetch_proxies()
    return {"ok": True}


@app.on_event("startup")
async def startup_event():
    # Set Telegram webhook on start
    webhook_url = f"{APP_URL}/webhook"
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
    payload = {"url": webhook_url}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            result = await resp.json()
            if result.get("ok"):
                print(f"✅ Webhook set to {webhook_url}")
            else:
                print(f"❌ Failed to set webhook: {result}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
