import aiohttp
import asyncio
import random
import string
import os
from aiohttp import ClientSession
from dotenv import load_dotenv

load_dotenv()

telegram_token = os.getenv("TELEGRAM_TOKEN")
telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
webshare_api_key = os.getenv("WEBSHARE_KEY")

vowels = "aeiou"
consonants = ''.join(set(string.ascii_lowercase) - set(vowels))


def generate_usernames(limit=5000):
    usernames = set()
    while len(usernames) < limit:
        pattern = random.choice(['CVCV', 'VCVC', 'repeat'])
        if pattern == 'repeat':
            ch = random.choice(consonants)
            usernames.add(ch * 4)
        else:
            uname = ''
            for p in pattern:
                uname += random.choice(consonants if p == 'C' else vowels)
            usernames.add(uname)
    return list(usernames)


def load_wordlist():
    try:
        with open("wordlist.txt", "r") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print("[WARN] wordlist.txt not found. Generating usernames.")
        return generate_usernames()


async def fetch_proxies():
    print("[DEBUG] Fetching proxies from Webshare...")
    headers = {"Authorization": f"Token {webshare_api_key}"}
    url = "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100"

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                print(f"[ERROR] Failed to fetch proxies. Status: {resp.status}")
                return []
            data = await resp.json()
            proxies = [
                f"http://{p['proxy_address']}:{p['ports']['http']}"
                for p in data['results']
            ]
            print(f"[INFO] Fetched {len(proxies)} proxies.")
            return proxies


async def check_username(session, proxy, username, found):
    try:
        url = f"https://www.tiktok.com/@{username}"
        async with session.get(url, proxy=proxy, timeout=15) as resp:
            if resp.status == 404:
                print(f"[AVAILABLE] {username}")
                found.append(username)
    except:
        pass  # Silently ignore proxy/connection errors


async def send_telegram_batch(usernames):
    if not usernames:
        print("[INFO] No available usernames found.")
        return
    text = "\n".join(usernames)
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    data = {
        "chat_id": telegram_chat_id,
        "text": f"🔥 Available TikTok usernames:\n{text}"
    }
    async with aiohttp.ClientSession() as session:
        await session.post(url, data=data)


async def main():
    usernames = load_wordlist()
    print(f"[INFO] Checking {len(usernames)} usernames...")

    proxies = await fetch_proxies()
    if not proxies:
        print("[FATAL] No proxies available. Exiting.")
        return

    found = []
    sem = asyncio.Semaphore(20)
    proxy_cycle = itertools.cycle(proxies)

    async def bound_check(username):
        async with sem:
            proxy = next(proxy_cycle)
            async with ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
                await check_username(session, proxy, username, found)
                await asyncio.sleep(random.uniform(0.4, 1.0))

    import itertools
    tasks = [bound_check(username) for username in usernames]
    await asyncio.gather(*tasks)

    await send_telegram_batch(found)
    print(f"[INFO] Finished. {len(found)} usernames found.")

if __name__ == "__main__":
    asyncio.run(main())
