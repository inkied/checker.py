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

async def fetch_proxies():
    headers = {"Authorization": f"Token {webshare_api_key}"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100", headers=headers) as resp:
                data = await resp.json()
                proxies = [f"http://{p['proxy_address']}:{p['ports']['http']}" for p in data.get('results', [])]
                if not proxies:
                    print("No proxies fetched!")
                return proxies
    except Exception as e:
        print(f"Failed to fetch proxies: {e}")
        return []

async def check_username(session, proxy, username, found):
    url = f"https://www.tiktok.com/@{username}"
    try:
        async with session.get(url, proxy=proxy, timeout=15) as resp:
            if resp.status == 404:
                print(f"[AVAILABLE] {username}")
                found.append(username)
            elif resp.status != 200:
                print(f"Received status {resp.status} for {username} via {proxy}")
    except Exception as e:
        print(f"Error checking {username} via {proxy}: {e}")

async def send_telegram_batch(usernames):
    if not usernames:
        print("No usernames to send to Telegram.")
        return
    text = "\n".join(usernames)
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    data = {
        "chat_id": telegram_chat_id,
        "text": f"🔥 Available TikTok usernames:\n{text}"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as resp:
                if resp.status != 200:
                    print(f"Telegram API error: {resp.status}")
                else:
                    print(f"Sent {len(usernames)} usernames to Telegram.")
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

async def main():
    try:
        usernames = generate_usernames(5000)
        proxies = await fetch_proxies()
        if not proxies:
            print("No proxies available. Exiting.")
            return

        found = []
        sem = asyncio.Semaphore(25)  # Limit concurrency

        async with ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            async def bound_check(username):
                async with sem:
                    proxy = random.choice(proxies)
                    await check_username(session, proxy, username, found)
                    await asyncio.sleep(random.uniform(0.4, 0.9))

            tasks = [bound_check(username) for username in usernames]
            await asyncio.gather(*tasks)

        await send_telegram_batch(found)

    except Exception as e:
        print(f"Fatal error in main: {e}")

if __name__ == "__main__":
    asyncio.run(main())
