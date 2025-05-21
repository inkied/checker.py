import asyncio
import aiohttp
from fastapi import FastAPI, Request
import logging
import random
import string

app = FastAPI()

# === CONFIG ===
TELEGRAM_TOKEN = "7698527405:AAE8z3q9epDTXZFZMNZRW9ilU-ayevMQKVA"
TELEGRAM_CHAT_ID = "7755395640"
TELEGRAM_API = f"https://api.telegram.org/bot7698527405:AAE8z3q9epDTXZFZMNZRW9ilU-ayevMQKVA"
WEB_SHARE_API_KEY = "cmaqd2pxyf6h1bl93ozf7z12mm2efjsvbd7w366z"  # Your Webshare API key
WEB_SHARE_API_URL = "https://proxy.webshare.io/api/proxy/list/?page=1&page_size=100&protocol=http,https,socks4,socks5"
CHECK_CONCURRENCY = 40
USERNAME_BATCH_SIZE = 5
PROXY_TIMEOUT = 10

proxies = []
proxies_lock = asyncio.Lock()

semi_og_words = [
    "tsla", "kurv", "curv", "stak", "lcky", "loky", "juno", "moxi", "vibe",
    "zora", "neon", "flux", "hype", "rave", "glow", "nova", "perk", "quip", "zeal"
]

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

@app.get("/")
async def root():
    return {"status": "✅ Server running"}

@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        logging.info(f"Incoming update: {data}")

        message = data.get("message") or data.get("edited_message")
        if not message:
            return {"ok": True}

        text = message.get("text", "").strip()
        chat_id = message["chat"]["id"]

        if text.lower() == "/start":
            await send_message(chat_id, "✅ Checker bot active! Starting TikTok username checking...")
            asyncio.create_task(run_checker(chat_id))

        return {"ok": True}
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return {"ok": False, "error": str(e)}

async def send_message(chat_id, text):
    async with aiohttp.ClientSession() as session:
        try:
            await session.post(f"{TELEGRAM_API}/sendMessage", json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown"
            })
        except Exception as e:
            logging.error(f"Failed to send message: {e}")

async def fetch_webshare_proxies():
    global proxies
    headers = {"Authorization": f"Token {WEB_SHARE_API_KEY}"}
    new_proxies = []
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(WEB_SHARE_API_URL, headers=headers, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for p in data.get("results", []):
                        ip = p.get("proxy_address")
                        port = p.get("proxy_port")
                        proto = p.get("protocol")
                        proto = proto.lower()
                        if proto not in ("http", "https", "socks4", "socks5"):
                            continue
                        proxy_url = f"{proto}://{ip}:{port}"
                        new_proxies.append(proxy_url)
                    logging.info(f"Fetched {len(new_proxies)} proxies from Webshare")
                else:
                    logging.error(f"Webshare API error: HTTP {resp.status}")
        except Exception as e:
            logging.error(f"Error fetching proxies from Webshare: {e}")

    async with proxies_lock:
        proxies = new_proxies

async def validate_proxy(session, proxy):
    test_url = "https://www.tiktok.com"
    try:
        async with session.get(test_url, proxy=proxy, timeout=PROXY_TIMEOUT) as resp:
            return resp.status == 200
    except:
        return False

async def validate_proxies():
    logging.info("Starting proxy validation...")
    valid_proxies = []
    async with aiohttp.ClientSession() as session:
        tasks = [validate_proxy(session, proxy) for proxy in proxies]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for proxy, valid in zip(proxies, results):
            if valid is True:
                valid_proxies.append(proxy)
    async with proxies_lock:
        proxies.clear()
        proxies.extend(valid_proxies)
    logging.info(f"Proxy validation complete. {len(proxies)} proxies are valid.")

def generate_username():
    if random.random() < 0.5:
        return random.choice(semi_og_words)
    else:
        vowels = "aeiou"
        consonants = "".join(set(string.ascii_lowercase) - set(vowels))
        return (
            random.choice(consonants) +
            random.choice(vowels) +
            random.choice(consonants) +
            random.choice(vowels)
        )

async def check_username_availability(session, username, proxy=None):
    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
                      " Chrome/112.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    }
    try:
        async with session.get(url, headers=headers, proxy=proxy, timeout=10, allow_redirects=False) as resp:
            if resp.status == 404:
                return True
            elif resp.status == 200:
                return False
            else:
                return False
    except Exception as e:
        logging.debug(f"Error checking username {username}: {e}")
        return False

async def run_checker(chat_id: int):
    await fetch_webshare_proxies()
    await validate_proxies()

    if not proxies:
        await send_message(chat_id, "❌ No valid proxies available. Stopping checker.")
        return

    semaphore = asyncio.Semaphore(CHECK_CONCURRENCY)
    available_usernames = []
    total_checked = 0

    async with aiohttp.ClientSession() as session:

        async def check_and_report(username):
            nonlocal total_checked
            async with semaphore:
                proxy = None
                async with proxies_lock:
                    if proxies:
                        proxy = random.choice(proxies)

                available = await check_username_availability(session, username, proxy)
                total_checked += 1

                if available:
                    logging.info(f"Username AVAILABLE: {username}")
                    available_usernames.append(username)

                    if len(available_usernames) >= USERNAME_BATCH_SIZE:
                        msg = "✅ *Available TikTok usernames:*\n" + "\n".join(f"`{u}`" for u in available_usernames)
                        await send_message(chat_id, msg)
                        available_usernames.clear()

        while True:
            username = generate_username()
            asyncio.create_task(check_and_report(username))
            await asyncio.sleep(0.1)
