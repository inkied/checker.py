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
            uname = ''.join(random.choice(consonants if p == 'C' else vowels) for p in pattern)
            usernames.add(uname)
    print(f"[INFO] Generated {len(usernames)} usernames.")
    return list(usernames)

async def fetch_proxies():
    url = "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100"
    headers = {
        "Authorization": f"Token {webshare_api_key}"
    }
    print("[DEBUG] Fetching proxies from Webshare...")
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                print(f"[ERROR] Failed to fetch proxies. Status: {resp.status}")
                return []
            data = await resp.json()
            proxies = [f"http://{p['proxy_address']}:{p['ports']['http']}" for p in data.get('results', [])]
            print(f"[DEBUG] {len(proxies)} proxies fetched.")
            return proxies

async def send_telegram_alert(username):
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    data = {
        "chat_id": telegram_chat_id,
        "text": f"✅ Available: `{username}`",
        "parse_mode": "Markdown"
    }
    async with aiohttp.ClientSession() as session:
        await session.post(url, data=data)

async def check_username(session, proxy, username):
    try:
        url = f"https://www.tiktok.com/@{username}"
        async with session.get(url, proxy=proxy, timeout=15) as resp:
            if resp.status == 404:
                print(f"[AVAILABLE] {username}")
                await send_telegram_alert(username)
    except:
        pass  # Silently ignore errors

async def main():
    usernames = generate_usernames(5000)
    proxies = await fetch_proxies()
    if not proxies:
        print("[FATAL] No proxies available. Exiting.")
        return

    sem = asyncio.Semaphore(25)

    async def bound_check(username):
        proxy = random.choice(proxies)
        async with sem:
            async with ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
                await check_username(session, proxy, username)
                await asyncio.sleep(random.uniform(0.4, 0.9))

    tasks = [bound_check(username) for username in usernames]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
