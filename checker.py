import os
import asyncio
import random
import string
from aiohttp import ClientSession, TCPConnector
from dotenv import load_dotenv
from telegram import Bot

load_dotenv()

WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
USERNAME_LEN = 4

BASE_URL = "https://www.tiktok.com/@{}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}


async def fetch_proxies():
    url = "https://proxy.webshare.io/api/v2/proxy/list/download/"
    params = {"mode": "direct", "quantity": "100", "format": "text"}
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    async with ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as resp:
            text = await resp.text()
            return list(filter(None, text.strip().splitlines()))


def generate_username():
    return ''.join(random.choices(string.ascii_lowercase, k=USERNAME_LEN))


async def send_telegram(bot, username):
    msg = f"✅ Available TikTok username: @{username}"
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)


async def check_username(session, bot, proxy, username):
    proxy_url = f"http://{proxy}"
    try:
        async with session.get(BASE_URL.format(username), proxy=proxy_url, headers=HEADERS, timeout=10) as resp:
            if resp.status == 404:
                print(f"[AVAILABLE] @{username}")
                await send_telegram(bot, username)
    except Exception:
        # You can log proxy failures here if you want
        pass


async def main():
    proxies = await fetch_proxies()
    bot = Bot(token=TELEGRAM_TOKEN)
    connector = TCPConnector(limit=50)
    async with ClientSession(connector=connector) as session:
        while True:
            tasks = []
            for _ in range(40):  # number of concurrent checks per batch
                username = generate_username()
                proxy = random.choice(proxies)
                tasks.append(check_username(session, bot, proxy, username))
            await asyncio.gather(*tasks)
            await asyncio.sleep(1)  # tiny delay between batches


if __name__ == "__main__":
    asyncio.run(main())
    )
