import aiohttp
import asyncio
import os
import random
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")

BASE_URL = "https://www.tiktok.com/@{}"
HEADERS_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/113",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"
]
PROXY_API_URL = "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100"

proxy_pool = asyncio.Queue()
checking_active = False
username_wordlist = []
available_usernames = []

WORDLIST_SOURCES = [
    "https://raw.githubusercontent.com/dominictarr/random-name/master/first-names.json",
    "https://raw.githubusercontent.com/dariusk/corpora/master/data/humans/firstNames.json"
]

# ----------------- Username Gen -----------------
def generate_username():
    vowels = "aeiou"
    consonants = "bcdfghjklmnpqrstvwxyz"
    pattern = random.choice(["CVCV", "CVVC", "VCCV", "CCVV"])
    return ''.join(random.choice(vowels if c == "V" else consonants) for c in pattern)

async def load_usernames():
    global username_wordlist
    all_names = set()

    # Load from URLs
    for url in WORDLIST_SOURCES:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if isinstance(data, dict):
                            names = data.get("firstNames", [])
                        elif isinstance(data, list):
                            names = data
                        else:
                            names = []
                        all_names.update(name.lower() for name in names if 3 < len(name) <= 4)
        except Exception:
            continue

    # Local fallback
    if os.path.exists("wordlist.txt"):
        with open("wordlist.txt", "r") as f:
            local = [line.strip().lower() for line in f if 3 < len(line.strip()) <= 4]
            all_names.update(local)

    username_wordlist = list(all_names)
    random.shuffle(username_wordlist)

# ----------------- Telegram -----------------
async def send_telegram(username):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"✅ Available TikTok: @{username}",
        "disable_web_page_preview": True,
    }
    async with aiohttp.ClientSession() as session:
        await session.post(url, json=payload)

# ----------------- Proxies -----------------
async def fetch_proxies():
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(PROXY_API_URL, headers=headers) as response:
            data = await response.json()
            raw_proxies = [
                f"{item['proxy_address']}:{item['ports']['http']}"
                for item in data.get("results", [])
            ]
            valid = await validate_proxies(raw_proxies)
            for proxy in valid:
                await proxy_pool.put(proxy)
            print(f"[INFO] {len(valid)} healthy proxies loaded.")

async def validate_proxies(proxies):
    async def test(proxy):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("http://httpbin.org/ip", proxy=f"http://{proxy}", timeout=6):
                    return proxy
        except:
            return None
    tasks = [test(p) for p in proxies]
    results = await asyncio.gather(*tasks)
    return [p for p in results if p]

# ----------------- Checker -----------------
async def check_username(session, proxy, username):
    proxy_url = f"http://{proxy}"
    headers = {"User-Agent": random.choice(HEADERS_LIST)}

    try:
        async with session.get(BASE_URL.format(username), proxy=proxy_url, headers=headers, timeout=10) as resp:
            if resp.status == 404:
                print(f"[AVAILABLE] @{username}")
                available_usernames.append(username)
                await send_telegram(username)
    except:
        pass
    finally:
        await asyncio.sleep(random.uniform(2, 4))
        await proxy_pool.put(proxy)

async def checker_loop():
    global checking_active, username_wordlist
    await load_usernames()
    connector = aiohttp.TCPConnector(ssl=False)

    async with aiohttp.ClientSession(connector=connector) as session:
        while checking_active:
            if not username_wordlist:
                username = generate_username()
            else:
                username = username_wordlist.pop()

            if proxy_pool.empty():
                await asyncio.sleep(1)
                continue

            proxy = await proxy_pool.get()
            asyncio.create_task(check_username(session, proxy, username))
            await asyncio.sleep(random.uniform(0.3, 0.6))

# ----------------- Telegram Bot Webhook -----------------
async def handle_webhook(request):
    global checking_active

    data = await request.json()
    message = data.get("message", {})
    text = message.get("text", "")
    chat_id = str(message.get("chat", {}).get("id"))

    if chat_id != TELEGRAM_CHAT_ID:
        return web.Response(text="Unauthorized", status=403)

    if text == "/start" and not checking_active:
        checking_active = True
        asyncio.create_task(checker_loop())
        return web.Response(text="✅ Started username checking.")

    elif text == "/stop":
        checking_active = False
        return web.Response(text="⛔️ Stopped.")

    return web.Response(text="OK")

# ----------------- Webhook Server -----------------
async def start_webhook_server():
    app = web.Application()
    app.router.add_post('/webhook', handle_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, port=8080)
    await site.start()
    print("[INFO] Webhook listening at /webhook")

# ----------------- Entry -----------------
async def main():
    await fetch_proxies()
    await start_webhook_server()
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
