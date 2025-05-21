import aiohttp
import asyncio
import os
import random
import logging
from dotenv import load_dotenv
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

load_dotenv()

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
WEBHOOK_URL = f"https://checkerpy-production-a7e1.up.railway.app/webhook"
PROXY_API_URL = "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100"
BASE_URL = "https://www.tiktok.com/@{}"
HEADERS_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)",
]

proxy_pool = asyncio.Queue()
checking_active = False
available_usernames = set()
username_wordlists = []
MAX_USERNAME_SOURCES = 2

app = FastAPI()

def load_usernames_from_file(filename):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            lines = [line.strip().lower() for line in f if 3 < len(line.strip()) <= 4]
            random.shuffle(lines)
            return lines
    return []

USERNAME_SOURCES = [
    "https://raw.githubusercontent.com/dominictarr/random-name/master/first-names.txt",
    "https://raw.githubusercontent.com/dominictarr/random-name/master/names.txt",
]

async def fetch_username_list(session, url):
    try:
        async with session.get(url, timeout=15) as resp:
            if resp.status == 200:
                text = await resp.text()
                lines = [line.strip().lower() for line in text.splitlines() if 3 < len(line.strip()) <= 4]
                random.shuffle(lines)
                return lines
    except Exception as e:
        logging.warning(f"Failed to fetch username list from {url}: {e}")
    return []

async def gather_usernames():
    usernames = []
    async with aiohttp.ClientSession() as session:
        for url in USERNAME_SOURCES[:MAX_USERNAME_SOURCES]:
            lines = await fetch_username_list(session, url)
            usernames.extend(lines)
    usernames.extend(load_usernames_from_file("wordlist.txt"))
    random.shuffle(usernames)
    return usernames

def generate_username():
    vowels = "aeiou"
    consonants = "bcdfghjklmnpqrstvwxyz"
    pattern = random.choice(["CVCV", "CVVC", "VCCV", "CCVV"])
    return ''.join(random.choice(vowels if c == "V" else consonants) for c in pattern)

async def send_telegram(text):
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    async with aiohttp.ClientSession() as session:
        try:
            await session.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)
        except Exception as e:
            logging.warning(f"Failed to send telegram message: {e}")

async def fetch_proxies():
    logging.info("Grabbing proxies from WebShare...")
    await send_telegram("🌀 Grabbing proxies from WebShare...")
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(PROXY_API_URL, headers=headers, timeout=10) as response:
                data = await response.json()
                raw_proxies = [
                    f"{item['proxy_address']}:{item['ports']['http']}"
                    for item in data.get("results", [])
                ]
                valid = await validate_proxies(raw_proxies)
                for proxy in valid:
                    await proxy_pool.put(proxy)
                logging.info(f"{len(valid)} proxies are working.")
                await send_telegram(f"✅ {len(valid)} proxies are working.")
        except Exception as e:
            logging.error(f"[ERROR] Failed to fetch proxies: {e}")

async def validate_proxies(proxies):
    async def test(proxy):
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get("http://httpbin.org/ip", proxy=f"http://{proxy}"):
                    return proxy
        except:
            return None
    tasks = [test(p) for p in proxies]
    results = await asyncio.gather(*tasks)
    return [p for p in results if p]

async def check_username(session, proxy, username):
    proxy_url = f"http://{proxy}"
    headers = {"User-Agent": random.choice(HEADERS_LIST)}

    try:
        async with session.get(BASE_URL.format(username), proxy=proxy_url, headers=headers, timeout=10) as resp:
            if resp.status == 404:
                if username not in available_usernames:
                    logging.info(f"[AVAILABLE] @{username}")
                    available_usernames.add(username)
                    await send_telegram(f"✅ Available TikTok: @{username}")
            elif resp.status in (429, 403):
                await asyncio.sleep(5)
    except Exception:
        pass
    finally:
        await asyncio.sleep(random.uniform(1.5, 3.5))
        await proxy_pool.put(proxy)

async def checker_loop():
    global checking_active, username_wordlists
    username_wordlists = await gather_usernames()
    connector = aiohttp.TCPConnector(ssl=False)

    async with aiohttp.ClientSession(connector=connector) as session:
        while checking_active:
            if proxy_pool.empty():
                logging.info("[INFO] Proxy pool empty, refetching...")
                await fetch_proxies()
                await asyncio.sleep(3)
                continue
            username = username_wordlists.pop() if username_wordlists else generate_username()
            proxy = await proxy_pool.get()
            asyncio.create_task(check_username(session, proxy, username))
            await asyncio.sleep(random.uniform(0.4, 0.9))

@app.post("/webhook")
async def handle_webhook(request: Request):
    global checking_active
    data = await request.json()
    message = data.get("message", {})
    text = message.get("text", "")
    chat_id = str(message.get("chat", {}).get("id"))

    if chat_id != TELEGRAM_CHAT_ID:
        return JSONResponse({"error": "Unauthorized"}, status_code=status.HTTP_403_FORBIDDEN)

    if text == "/start" and not checking_active:
        checking_active = True
        asyncio.create_task(checker_loop())
        return JSONResponse({"status": "Started checking usernames."})

    elif text == "/stop":
        checking_active = False
        await send_telegram("🔴 Checker stopped.")
        return JSONResponse({"status": "Stopped checking."})

    return JSONResponse({"status": "OK"})

@app.on_event("startup")
async def startup_event():
    await set_webhook()
    await send_telegram("✅ Checker is online.")
    await fetch_proxies()

async def set_webhook():
    payload = {"url": WEBHOOK_URL}
    async with aiohttp.ClientSession() as session:
        await session.post(f"{TELEGRAM_API_URL}/setWebhook", json=payload)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
