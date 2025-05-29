import aiohttp
import asyncio

# Simple list of usernames to check
usernames = ["testuser123", "abcd", "someuser", "notrealname"]

# If you want to use proxies, put a single proxy string here like "http://ip:port"
proxy = None  # e.g. "http://1.2.3.4:8080"

async def check_username(session, username):
    url = f"https://www.tiktok.com/@{username}"
    try:
        async with session.get(url, proxy=proxy, timeout=10) as resp:
            if resp.status == 404:
                print(f"[AVAILABLE] {username}")
            else:
                print(f"[TAKEN or ERROR] {username} (status: {resp.status})")
    except Exception as e:
        print(f"[ERROR] Checking {username}: {e}")

async def main():
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        tasks = [check_username(session, uname) for uname in usernames]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
