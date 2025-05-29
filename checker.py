import aiohttp
import asyncio

usernames = ["testuser123", "abcd", "someuser", "notrealname"]
proxy = None  # or "http://ip:port" if you want

async def check_username(session, username):
    url = f"https://www.tiktok.com/@{username}"
    try:
        async with session.get(url, proxy=proxy, timeout=10) as resp:
            if resp.status == 404:
                print(f"[AVAILABLE] {username}")
            else:
                print(f"[TAKEN] {username} (Status: {resp.status})")
    except Exception as e:
        print(f"[ERROR] {username}: {e}")

async def main():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [check_username(session, username) for username in usernames]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
