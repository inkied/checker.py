import asyncio
import aiohttp
import random
import string
from fastapi import FastAPI, BackgroundTasks, Request

# CONFIG
TELEGRAM_BOT_TOKEN = "7698527405:AAE8z3q9epDTXZFZMNZRW9ilU-ayevMQKVA"
TELEGRAM_CHAT_ID = "7755395640"
WEBSHARE_API_KEY = "cmaqd2pxyf6h1bl93ozf7z12mm2efjsvbd7w366z"

CHECK_CONCURRENCY = 30
BATCH_SIZE = 5
SAVE_FILE = "available_tiktok_usernames.txt"

vowels = "aeiouy"
consonants = "".join(c for c in string.ascii_lowercase if c not in vowels)
digits = "0123456789"

BANNED_PATTERNS = [
    "admin", "support", "staff", "mod", "test", "null", "undefined",
    "sys", "root", "system", "operator", "owner", "manager"
]

def contains_banned_pattern(name):
    name_lower = name.lower()
    return any(pattern in name_lower for pattern in BANNED_PATTERNS)

def semi_og_generator(n=500):
    names = set()
    while len(names) < n:
        name_chars = []
        for i in range(4):
            if i % 2 == 0:
                name_chars.append(random.choice(consonants))
            else:
                name_chars.append(random.choice(vowels))
        if random.random() < 0.3:
            idx = random.randint(0, 3)
            name_chars[idx] = random.choice(digits)
        username = "".join(name_chars)
        if max(username.count(ch) for ch in username) <= 2 and not contains_banned_pattern(username):
            names.add(username)
    return list(names)

async def fetch_proxies(session):
    url = f"https://proxy.webshare.io/api/proxy/list/?page_size=100"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    proxies = []
    try:
        async with session.get(url, headers=headers) as r:
            data = await r.json()
            for p in data.get("results", []):
                proxy = f"http://{p['proxy_address']}:{p['ports']['http']}"
                proxies.append(proxy)
    except Exception as e:
        print(f"Proxy fetch error: {e}")
    return proxies

async def validate_proxy(session, proxy):
    test_url = "https://www.tiktok.com"
    try:
        async with session.head(test_url, proxy=proxy, timeout=7) as r:
            return r.status == 200
    except:
        return False

async def check_username(session, username, proxy=None):
    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        async with session.head(url, headers=headers, proxy=proxy, timeout=7) as r:
            return r.status == 404
    except:
        return False

async def send_telegram_message(session, messages):
    if not messages:
        return
    text = "\n".join(messages)
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        async with session.post(url, data=payload) as r:
            return await r.json()
    except Exception as e:
        print(f"Telegram send error: {e}")
        return None

async def send_inline_buttons(chat_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "TikTok Username Checker\nChoose an action below:",
        "reply_markup": {
            "inline_keyboard": [
                [{"text": "▶ Start", "callback_data": "start"}],
                [{"text": "⛔ Stop", "callback_data": "stop"}]
            ]
        }
    }
    async with aiohttp.ClientSession() as session:
        await session.post(url, json=payload)

async def worker(queue, session, proxies):
    available = []
    while True:
        username = await queue.get()
        proxy = random.choice(proxies) if proxies else None
        if proxy and not proxy.startswith("http"):
            proxy = "http://" + proxy
        is_available = await check_username(session, username, proxy)
        if is_available:
            print(f"[AVAILABLE] {username}")
            available.append(username)
            with open(SAVE_FILE, "a") as f:
                f.write(username + "\n")
            if len(available) >= BATCH_SIZE:
                await send_telegram_message(session, available)
                available.clear()
        queue.task_done()
        await asyncio.sleep(random.uniform(0.1, 0.4))

async def run_checker():
    usernames = semi_og_generator(1000)
    queue = asyncio.Queue()
    for u in usernames:
        queue.put_nowait(u)

    async with aiohttp.ClientSession() as session:
        proxies = await fetch_proxies(session)
        valid_proxies = []
        results = await asyncio.gather(*[validate_proxy(session, proxy) for proxy in proxies])
        for proxy, valid in zip(proxies, results):
            if valid:
                valid_proxies.append(proxy)
        print(f"Valid proxies: {len(valid_proxies)}")

        tasks = [asyncio.create_task(worker(queue, session, valid_proxies)) for _ in range(CHECK_CONCURRENCY)]
        await queue.join()
        for task in tasks:
            task.cancel()

# ========== FastAPI APP ==========

app = FastAPI()

@app.get("/")
async def root():
    return {"status": "TikTok checker API running"}

@app.post("/start_checker")
async def start_checker(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_checker)
    return {"message": "Checker started in background"}

@app.post("/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    print("Webhook received:", data)

    if "message" in data:
        message = data["message"]
        chat_id = message["chat"]["id"]

        if message.get("text") == "/start":
            await send_inline_buttons(chat_id)

    elif "callback_query" in data:
        query = data["callback_query"]
        chat_id = query["message"]["chat"]["id"]
        command = query["data"]

        if command == "start":
            background_tasks.add_task(run_checker)
            async with aiohttp.ClientSession() as session:
                await send_telegram_message(session, ["✅ TikTok checker started."])
        elif command == "stop":
            async with aiohttp.ClientSession() as session:
                await send_telegram_message(session, ["⛔ Stop not implemented yet."])

    return {"ok": True}
