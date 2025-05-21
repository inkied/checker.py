import os
import aiohttp
import asyncio
import random
import time
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")

PROXY_API = "https://proxy.webshare.io/api/proxy/list/?page_size=100&page=1&country=US&is_active=true"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
    " Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko)"
    " Chrome/112.0.0.0 Mobile Safari/537.36",
    # Add more user agents here
]

# Globals
proxies = []
available_usernames = []
usernames_checked_info = {}  # track availability times, etc.

async def fetch_proxies():
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(PROXY_API, headers=headers) as resp:
            data = await resp.json()
            proxy_list = []
            for item in data.get("results", []):
                ip = item.get("proxy_address")
                port = item.get("proxy_port")
                protocol = item.get("proxy_type").lower()
                if protocol in ["http", "https"]:
                    proxy_list.append(f"http://{ip}:{port}")
                elif protocol in ["socks4", "socks5"]:
                    proxy_list.append(f"{protocol}://{ip}:{port}")
            return proxy_list

async def validate_proxy(proxy):
    test_url = "https://www.tiktok.com/"
    timeout = aiohttp.ClientTimeout(total=8)
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(test_url, proxy=proxy, headers=headers) as resp:
                return resp.status == 200
    except:
        return False

async def load_and_validate_proxies():
    global proxies
    print("[*] Fetching proxies...")
    raw_proxies = await fetch_proxies()
    print(f"[*] {len(raw_proxies)} proxies fetched, validating...")
    validated = []
    for p in raw_proxies:
        if await validate_proxy(p):
            validated.append(p)
    proxies = validated
    print(f"[*] {len(proxies)} proxies validated and ready")

async def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    async with aiohttp.ClientSession() as session:
        await session.post(url, data=data)

async def check_username(username: str, proxy: str = None):
    url = f"https://www.tiktok.com/api/user/detail/?uniqueId={username}"
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.tiktok.com/",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    }
    timeout = aiohttp.ClientTimeout(total=8)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, proxy=proxy, headers=headers) as resp:
                if resp.status == 404:
                    # Username available
                    return True
                elif resp.status == 200:
                    # Username taken
                    return False
                else:
                    return False
    except:
        return False

async def username_worker(queue: asyncio.Queue):
    while True:
        username = await queue.get()
        if not proxies:
            print("[!] No proxies available")
            queue.task_done()
            continue
        proxy = random.choice(proxies)
        available = await check_username(username, proxy=proxy)
        if available:
            msg = f"✅ Username available: *{username}*"
            print(msg)
            available_usernames.append(username)
            await send_telegram_message(msg)
            # Optional: save to file
            with open("available_usernames.txt", "a") as f:
                f.write(username + "\n")
        else:
            print(f"✖ Username taken: {username}")
        queue.task_done()
        await asyncio.sleep(random.uniform(0.5, 1.5))  # polite delay

async def main():
    await load_and_validate_proxies()

    # Your username source: list, wordlist, or generate live
    usernames_to_check = [
        "tsla", "kurv", "curv", "stak", "lcky", "loky",
        # Add more usernames or generate dynamically
    ]

    queue = asyncio.Queue()
    for uname in usernames_to_check:
        queue.put_nowait(uname)

    workers = []
    for _ in range(15):  # concurrency
        worker = asyncio.create_task(username_worker(queue))
        workers.append(worker)

    await queue.join()

    for w in workers:
        w.cancel()

    print("[*] All usernames processed.")

if __name__ == "__main__":
    asyncio.run(main())
