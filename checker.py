import asyncio
import aiohttp
from fastapi import FastAPI, Request, HTTPException
import logging
import random
from time import time

app = FastAPI()

# === CONFIG ===
TELEGRAM_TOKEN = "7698527405:AAE8z3q9epDTXZFZMNZRW9ilU-ayevMQKVA"
TELEGRAM_CHAT_ID = "7755395640"
TELEGRAM_API = f"https://api.telegram.org/botAAE8z3q9epDTXZFZMNZRW9ilU-ayevMQKVA"
WEB_SHARE_API_KEY = "cmaqd2pxyf6h1bl93ozf7z12mm2efjsvbd7w366z"
WEB_SHARE_API_URL = "https://proxy.webshare.io/api/proxy/list/?page=1&page_size=100&protocol=http,https,socks4,socks5"

CHECK_CONCURRENCY = 30
USERNAME_BATCH_SIZE = 5
PROXY_TIMEOUT = 10
PROXY_COOLDOWN = 120  # seconds to wait before retrying failed proxy
PROXY_MAX_FAILS = 3   # max fails before cooldown

# Globals
proxies = []  # list of dicts: {proxy:str, fails:int, cooldown_until:float}
proxies_lock = asyncio.Lock()

available_usernames = []
available_lock = asyncio.Lock()

# 4-letter semi-OG wordlist (brandable)
semi_og_words = [
    "tsla", "kurv", "curv", "stak", "lcky", "loky", "juno", "moxi", "vibe",
    "zora", "neon", "flux", "hype", "rave", "glow", "nova", "perk", "quip", "zeal"
]

# 5-6 letter pronounceable English-like syllable combos
syllables = [
    "ba", "be", "bi", "bo", "bu",
    "ca", "ce", "ci", "co", "cu",
    "da", "de", "di", "do", "du",
    "fa", "fe", "fi", "fo", "fu",
    "la", "le", "li", "lo", "lu",
    "ma", "me", "mi", "mo", "mu",
    "na", "ne", "ni", "no", "nu",
    "pa", "pe", "pi", "po", "pu",
    "ra", "re", "ri", "ro", "ru",
    "sa", "se", "si", "so", "su",
    "ta", "te", "ti", "to", "tu",
    "va", "ve", "vi", "vo", "vu",
    "za", "ze", "zi", "zo", "zu",
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

        elif text.lower() == "/stop":
            # Implement stop logic if needed (not included here)
            await send_message(chat_id, "🛑 Checker stopping is not implemented yet.")

        return {"ok": True}
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return {"ok": False, "error": str(e)}

@app.get("/webhook")
async def webhook_get():
    raise HTTPException(status_code=405, detail="GET method not allowed on /webhook")

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
                        proto = p.get("protocol").lower()
                        if proto not in ("http", "https", "socks4", "socks5"):
                            continue
                        proxy_url = f"{proto}://{ip}:{port}"
                        new_proxies.append({"proxy": proxy_url, "fails": 0, "cooldown_until": 0})
                    logging.info(f"Fetched {len(new_proxies)} proxies from Webshare")
                else:
                    logging.error(f"Webshare API error: HTTP {resp.status}")
        except Exception as e:
            logging.error(f"Error fetching proxies from Webshare: {e}")

    async with proxies_lock:
        proxies = new_proxies

async def validate_proxy(session, proxy_dict):
    test_url = "https://www.tiktok.com"
    proxy = proxy_dict["proxy"]
    try:
        async with session.get(test_url, proxy=proxy, timeout=PROXY_TIMEOUT) as resp:
            return resp.status == 200
    except:
        return False

async def validate_proxies():
    logging.info("Starting proxy validation...")
    valid_proxies = []
    async with aiohttp.ClientSession() as session:
        tasks = [validate_proxy(session, p) for p in proxies]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for p, valid in zip(proxies, results):
            if valid is True:
                valid_proxies.append(p)
    async with proxies_lock:
        proxies.clear()
        proxies.extend(valid_proxies)
    logging.info(f"Proxy validation complete. {len(proxies)} proxies are valid.")

def generate_username():
    # 50% chance semi-OG 4-letter from wordlist
    # 50% chance 5-6 letter pronounceable combo
    if random.random() < 0.5:
        return random.choice(semi_og_words)
    else:
        length = random.choice([5,6])
        # build username by concatenating random syllables
        username = ""
        while len(username) < length:
            username += random.choice(syllables)
        return username[:length]

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
        logging.debug(f"Error checking username {username} via proxy {proxy}: {e}")
        return False

async def run_checker(chat_id: int):
    await fetch_webshare_proxies()
    await validate_proxies()

    if not proxies:
        await send_message(chat_id, "❌ No valid proxies available. Stopping checker.")
        return

    semaphore = asyncio.Semaphore(CHECK_CONCURRENCY)

    async with aiohttp.ClientSession() as session:
        while True:
            await asyncio.sleep(0)  # allow cancellation

            username = generate_username()

            async with semaphore:
                proxy = None
                async with proxies_lock:
                    # Pick a proxy that is not on cooldown
                    now = time()
                    available_proxies = [p for p in proxies if p["cooldown_until"] <= now]
                    if not available_proxies:
                        # all proxies cooling down - wait a bit
                        logging.info("All proxies cooling down, waiting 10s...")
                        await asyncio.sleep(10)
                        continue
                    proxy_dict = random.choice(available_proxies)
                    proxy = proxy_dict["proxy"]

                available = await check_username_availability(session, username, proxy)

                if available:
                    logging.info(f"✅ Username available: {username}")
                    async with available_lock:
                        available_usernames.append(username)
                        if len(available_usernames) >= USERNAME_BATCH_SIZE:
                            msg = "✅ *Available TikTok usernames:*\n" + "\n".join(f"`{u}`" for u in available_usernames)
                            await send_message(chat_id, msg)
                            available_usernames.clear()
                    # reset fails for proxy on success
                    async with proxies_lock:
                        proxy_dict["fails"] = 0
                        proxy_dict["cooldown_until"] = 0
                else:
                    logging.info(f"❌ Username taken or check failed: {username}")
                    # On fail increase proxy fails count and possibly cooldown
                    async with proxies_lock:
                        proxy_dict["fails"] += 1
                        if proxy_dict["fails"] >= PROXY_MAX_FAILS:
                            proxy_dict["cooldown_until"] = time() + PROXY_COOLDOWN
                            logging.info(f"Proxy {proxy_dict['proxy']} cooldown for {PROXY_COOLDOWN}s due to repeated fails.")
                            proxy_dict["fails"] = 0

            await asyncio.sleep(random.uniform(0.4, 1.2))  # small delay for stealth
