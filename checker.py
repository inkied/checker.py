import os
import asyncio
import aiohttp
import random
import time
from fastapi import FastAPI, Request
from pydantic import BaseModel

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")

app = FastAPI()

# Global state
checking = False
user_queue = asyncio.Queue()
proxies = []
working_proxies = []

# Load username wordlist or fallback to generator
async def load_wordlist(file_path="usernames.txt"):
    try:
        with open(file_path, "r") as f:
            names = [line.strip() for line in f if line.strip()]
            if names:
                return names
    except Exception:
        pass
    # fallback: generate some dummy usernames
    return [f"user{str(i).zfill(5)}" for i in range(100000)]

# Scrape 100k+ TikTok users asynchronously (fake example)
async def scrape_users():
    print("Starting user scraping...")
    scraped = 0
    async with aiohttp.ClientSession() as session:
        # Fake scraping loop: replace with real scraper API or logic
        while scraped < 100000:
            # For example, fake usernames user00000 to user99999
            await user_queue.put(f"user{str(scraped).zfill(5)}")
            scraped += 1
    print("User scraping complete.")

# Fetch proxies from Webshare, no country filter, limit 200
async def scrape_proxies():
    global proxies
    url = "https://proxy.webshare.io/api/proxy/list/"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers) as r:
                if r.status == 200:
                    data = await r.json()
                    proxies = []
                    for item in data.get("results", []):
                        proxy = f"http://{item['proxy_address']}:{item['port']}"
                        proxies.append(proxy)
                    print(f"Scraped {len(proxies)} proxies.")
                else:
                    print(f"Failed to fetch proxies: {r.status}")
        except Exception as e:
            print(f"Error scraping proxies: {e}")

# Check if a proxy works by measuring speed with a simple test request
async def test_proxy(proxy):
    test_url = "https://www.tiktok.com/"
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            start = time.perf_counter()
            async with session.get(test_url, proxy=proxy) as resp:
                if resp.status == 200:
                    elapsed = time.perf_counter() - start
                    return proxy, elapsed
    except:
        pass
    return proxy, None

# Validate proxies by speed, keep only working ones sorted by speed
async def validate_proxies():
    global working_proxies
    print("Validating proxies...")
    tasks = [test_proxy(p) for p in proxies]
    results = await asyncio.gather(*tasks)
    working = [(p, s) for p, s in results if s is not None]
    working.sort(key=lambda x: x[1])
    working_proxies = [p for p, s in working]
    print(f"{len(working_proxies)} proxies are working after validation.")

# Send message to Telegram chat
async def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    async with aiohttp.ClientSession() as session:
        try:
            await session.post(url, json=payload)
        except Exception as e:
            print(f"Telegram send error: {e}")

# Check username availability (dummy example, replace with real TikTok check)
async def check_username(username, proxy=None):
    # Simulate username check delay and random availability
    await asyncio.sleep(random.uniform(0.2, 0.7))
    # Fake: randomly 1% available
    available = random.random() < 0.01
    return username, available

# Worker task to consume usernames and check them
async def checker_worker():
    global checking
    while checking:
        try:
            username = await asyncio.wait_for(user_queue.get(), timeout=10)
        except asyncio.TimeoutError:
            continue
        # Rotate proxy round-robin
        proxy = None
        if working_proxies:
            proxy = random.choice(working_proxies)
        username, available = await check_username(username, proxy)
        if available:
            await send_telegram_message(f"✅ Username available: <b>{username}</b>")
        user_queue.task_done()

# Telegram update schema
class Update(BaseModel):
    message: dict = None

@app.post(f"/telegram_webhook/{BOT_TOKEN}")
async def telegram_webhook(update: Update):
    global checking
    msg = update.message
    if not msg or "text" not in msg:
        return {"ok": True}
    text = msg["text"].strip()
    chat_id = msg["chat"]["id"]
    if chat_id != int(CHAT_ID):
        return {"ok": True}

    if text == "/start":
        if checking:
            await send_telegram_message("Already running.")
        else:
            checking = True
            await send_telegram_message("Started username checking.")
            # Start tasks
            asyncio.create_task(scrape_proxies())
            asyncio.create_task(validate_proxies())
            asyncio.create_task(scrape_users())
            for _ in range(10):  # 10 workers for example
                asyncio.create_task(checker_worker())
    elif text == "/stop":
        checking = False
        await send_telegram_message("Stopped username checking.")
    elif text == "/scrape":
        if checking:
            await send_telegram_message("Already running. Wait for scraping to finish.")
        else:
            checking = True
            await send_telegram_message("Scraping 100k+ users now.")
            asyncio.create_task(scrape_users())
    else:
        await send_telegram_message("Unknown command. Use /start, /stop or /scrape.")
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("checker:app", host="0.0.0.0", port=8000)
