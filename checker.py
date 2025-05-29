import aiohttp
import asyncio
import random
import string
import os
from aiohttp import ClientSession, ClientConnectorError
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

async def fetch_proxies():
    headers = {"Authorization": f"Token {webshare_api_key}"}
    url = "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=15) as resp:
                if resp.status != 200:
                    print(f"[ERROR] Failed to fetch proxies. Status: {resp.status}")
                    return []
                data = await resp.json()
                proxies = []
                for p in data.get('results', []):
                    ip = p.get('proxy_address')
                    port = p.get('ports', {}).get('http')
                    if ip and port:
                        proxies.append(f"http://{ip}:{port}")
                print(f"[INFO] Fetched {len(proxies)} proxies.")
                return proxies
    except Exception as e:
        print(f"[ERROR] Exception fetching proxies: {e}")
        return []

async def check_username(session, proxy, username):
    url = f"https://www.tiktok.com/@{username}"
    try:
        async with session.get(url, proxy=proxy, timeout=15, headers={"User-Agent": "Mozilla/5.0"}) as resp:
            if resp.status == 404:
                print(f"[AVAILABLE] {username}")
                return username
            else:
                return None
    except (asyncio.TimeoutError, ClientConnectorError) as e:
        # Network/connection issues, ignore and move on
        #print(f"[WARN] Network error on {username} with proxy {proxy}: {e}")
        return None
    except Exception as e:
        print(f"[ERROR] Unexpected error on {username}: {e}")
        return None

async def send_telegram(usernames):
    if not usernames:
        print("[INFO] No available usernames found to send.")
        return
    text = "\n".join(usernames)
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    data = {
        "chat_id": telegram_chat_id,
        "text": f"🔥 Available TikTok usernames:\n{text}"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, timeout=15) as resp:
                if resp.status == 200:
                    print("[INFO] Telegram alert sent successfully.")
                else:
                    print(f"[ERROR] Telegram send failed with status {resp.status}")
    except Exception as e:
        print(f"[ERROR] Exception sending Telegram message: {e}")

async def bound_check(sem, session, proxy, username):
    async with sem:
        return await check_username(session, proxy, username)

async def main():
    print("[INFO] Generating usernames...")
    usernames = generate_usernames(5000)
    print(f"[INFO] Generated {len(usernames)} usernames.")

    print("[INFO] Fetching proxies...")
    proxies = await fetch_proxies()
    if not proxies:
        print("[FATAL] No proxies available. Exiting.")
        return

    sem = asyncio.Semaphore(30)  # concurrency limit
    found = []

    async with ClientSession() as session:
        tasks = []
        for username in usernames:
            proxy = random.choice(proxies)
            tasks.append(bound_check(sem, session, proxy, username))

        print("[INFO] Starting username checks...")
        results = await asyncio.gather(*tasks)

    for r in results:
        if r:
            found.append(r)

    print(f"[INFO] Found {len(found)} available usernames.")
    await send_telegram(found)

if __name__ == "__main__":
    asyncio.run(main())
