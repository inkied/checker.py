import aiohttp
import asyncio
import random

usernames = ["testuser123", "abcd", "someuser", "notrealname"]
proxy = None  # Or set your proxy URL here, e.g. "http://ip:port"

async def check_username(session, username, retries=3):
    url = f"https://www.tiktok.com/@{username}"
    for attempt in range(1, retries + 1):
        try:
            async with session.get(url, proxy=proxy, timeout=10) as resp:
                if resp.status == 404:
                    print(f"[AVAILABLE] {username}")
                    return True
                else:
                    print(f"[TAKEN] {username} (Status: {resp.status})")
                    return False
        except aiohttp.ClientConnectionError as e:
            print(f"[WARN] Connection error on {username} attempt {attempt}: {e}")
        except asyncio.TimeoutError:
            print(f"[WARN] Timeout on {username} attempt {attempt}")
        except Exception as e:
            print(f"[ERROR] Unexpected error on {username}: {e}")

        await asyncio.sleep(random.uniform(1, 3))  # wait a bit before retrying
    print(f"[FAIL] Giving up on {username} after {retries} attempts")
    return False

async def main():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [check_username(session, username) for username in usernames]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
