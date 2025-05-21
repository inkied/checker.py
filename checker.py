import asyncio
import aiohttp
import random
import string
import time

# CONFIG - fill these with your actual tokens/IDs/keys
TELEGRAM_BOT_TOKEN = "7698527405:AAE8z3q9epDTXZFZMNZRW9ilU-ayevMQKVA"
TELEGRAM_CHAT_ID = "7755395640"
WEBSHARE_API_KEY = "cmaqd2pxyf6h1bl93ozf7z12mm2efjsvbd7w366z"

CHECK_CONCURRENCY = 30
BATCH_SIZE = 5
SAVE_FILE = "available_tiktok_usernames.txt"

vowels = "aeiouy"
consonants = "".join(c for c in string.ascii_lowercase if c not in vowels)
digits = "0123456789"

# 1. Username generator (semi-OG + brandable)
def semi_og_generator(n=500):
    names = set()
    while len(names) < n:
        name_chars = []
        for i in range(4):
            if i % 2 == 0:
                name_chars.append(random.choice(consonants))
            else:
                name_chars.append(random.choice(vowels))
        # 30% chance replace a char with digit
        if random.random() < 0.3:
            idx = random.randint(0, 3)
            name_chars[idx] = random.choice(digits)
        username = "".join(name_chars)
        if max(username.count(ch) for ch in username) <= 2:
            names.add(username)
    return list(names)

# 2. Proxy scraper from Webshare
async def fetch_proxies(session):
    url = f"https://proxy.webshare.io/api/proxy/list/?page_size=100"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    proxies = []
    try:
        async with session.get(url, headers=headers) as r:
            data = await r.json()
            for p in data.get("results", []):
                proxies.append(f"http://{p['proxy_address']}:{p['ports']['http']}")
    except:
        pass
    return proxies

# 3. Proxy validator (simple HTTP check)
async def validate_proxy(session, proxy):
    test_url = "https://www.tiktok.com"
    try:
        async with session.get(test_url, proxy=proxy, timeout=10) as r:
            return r.status == 200
    except:
        return False

# 4. TikTok username availability check
async def check_username(session, username, proxy=None):
    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        async with session.get(url, headers=headers, proxy=proxy, timeout=10) as r:
            # 404 means username available
            if r.status == 404:
                return True
            return False
    except:
        return False

# 5. Telegram send message batch
async def send_telegram_message(session, messages):
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
    except:
        return None

# 6. Worker tasks
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

# 7. Telegram bot listener - /start command to trigger check
async def telegram_listener():
    offset = None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    while True:
        try:
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as r:
                    data = await r.json()
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        msg = update.get("message", {})
                        text = msg.get("text", "")
                        chat_id = msg.get("chat", {}).get("id", 0)
                        if text == "/start" and str(chat_id) == TELEGRAM_CHAT_ID:
                            print("Received /start command - starting checker")
                            asyncio.create_task(run_checker())
        except Exception as e:
            print(f"Telegram listener error: {e}")
        await asyncio.sleep(1)

# 8. Main checker logic called on /start command
async def run_checker():
    usernames = semi_og_generator(1000)
    queue = asyncio.Queue()
    for u in usernames:
        queue.put_nowait(u)

    async with aiohttp.ClientSession() as session:
        proxies = await fetch_proxies(session)
        proxies = [p for p in proxies if await validate_proxy(session, p)]
        print(f"Valid proxies: {len(proxies)}")

        tasks = []
        for _ in range(CHECK_CONCURRENCY):
            tasks.append(asyncio.create_task(worker(queue, session, proxies)))

        await queue.join()
        for task in tasks:
            task.cancel()

        # Send remaining available usernames if any
        if tasks:
            # just a safety - though available cleared in worker
            pass

async def main():
    listener_task = asyncio.create_task(telegram_listener())
    await listener_task

if __name__ == "__main__":
    asyncio.run(main())
