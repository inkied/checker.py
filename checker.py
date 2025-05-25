import os
import re
import asyncio
import aiohttp
import random
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")
TWO_CAPTCHA_KEY = os.getenv("TWO_CAPTCHA_KEY")

app = FastAPI()

# Globals
checking = False
raw_proxies = []
username_queue = asyncio.Queue()
checked_usernames = set()
failed_usernames = set()
in_progress_usernames = set()
proxy_queue = asyncio.Queue()  # queue of valid proxies ready to be assigned
proxy_refresh_interval = 600  # seconds (10 minutes)
CONCURRENCY = 12

user_agents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36",
]

# Load usernames from wordlist.txt file
def load_wordlist(file_path="wordlist.txt"):
    if not os.path.isfile(file_path):
        print(f"Wordlist file {file_path} not found!")
        return []
    with open(file_path, "r", encoding="utf-8") as f:
        words = [line.strip() for line in f if line.strip()]
    print(f"Loaded {len(words)} usernames from wordlist.")
    return words


async def send_telegram_message(text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()


async def scrape_proxies():
    print("Scraping proxies from Webshare...")
    url = "https://proxy.webshare.io/api/proxy/list/"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    scraped = []
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                for p in data.get("results", []):
                    ip = p.get("proxy_address")
                    port = p.get("proxy_port")
                    ptype = p.get("proxy_type").lower()
                    if ip and port and ptype:
                        scraped.append(f"{ptype}://{ip}:{port}")
                print(f"Scraped {len(scraped)} proxies.")
            else:
                print(f"Failed to scrape proxies: HTTP {resp.status}")
    return scraped


async def validate_proxy(proxy: str, session: aiohttp.ClientSession) -> bool:
    try:
        headers = {"User-Agent": random.choice(user_agents)}
        async with session.get("https://www.tiktok.com", proxy=proxy, headers=headers, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False


async def validate_proxies(raw_proxies):
    print("Validating proxies...")
    valid = []
    sem = asyncio.Semaphore(20)
    async with aiohttp.ClientSession() as session:
        async def sem_validate(p):
            async with sem:
                if await validate_proxy(p, session):
                    valid.append(p)
        tasks = [asyncio.create_task(sem_validate(p)) for p in raw_proxies if re.match(r"^(http|socks4|socks5)://\d+\.\d+\.\d+\.\d+:\d+$", p)]
        await asyncio.gather(*tasks)
    print(f"Validated {len(valid)} proxies.")
    return valid


async def is_captcha_page(text: str) -> bool:
    signs = ["captcha", "g-recaptcha", "hcaptcha", "verify you are human"]
    lower = text.lower()
    return any(sign in lower for sign in signs)


async def solve_captcha(site_key: str, url: str) -> str:
    # 2Captcha solving for recaptcha v2, returns token or empty string
    async with aiohttp.ClientSession() as session:
        data = {
            "key": TWO_CAPTCHA_KEY,
            "method": "userrecaptcha",
            "googlekey": site_key,
            "pageurl": url,
            "json": 1,
        }
        async with session.post("http://2captcha.com/in.php", data=data) as resp:
            res = await resp.json()
            if res.get("status") != 1:
                print("2Captcha submit error:", res)
                return ""
            captcha_id = res.get("request")

        for _ in range(24):
            await asyncio.sleep(5)
            params = {
                "key": TWO_CAPTCHA_KEY,
                "action": "get",
                "id": captcha_id,
                "json": 1,
            }
            async with session.get("http://2captcha.com/res.php", params=params) as resp:
                res = await resp.json()
                if res.get("status") == 1:
                    return res.get("request")
                elif res.get("request") == "CAPCHA_NOT_READY":
                    continue
                else:
                    print("2Captcha error:", res)
                    break
    return ""


async def check_username(session: aiohttp.ClientSession, username: str, proxy: str = None) -> bool:
    url = f"https://www.tiktok.com/@{username}"
    headers = {"User-Agent": random.choice(user_agents)}
    try:
        kwargs = {"headers": headers, "timeout": 15}
        if proxy:
            kwargs["proxy"] = proxy
        async with session.get(url, **kwargs) as resp:
            text = await resp.text()
            if resp.status == 404:
                return True
            elif await is_captcha_page(text):
                if TWO_CAPTCHA_KEY:
                    # Example site key - may need update for TikTok's actual captcha site key
                    site_key = "6Lc_aX0UAAAAABx7H3Dxz-wGZa8H7n50bXpt_E62"
                    captcha_token = await solve_captcha(site_key, url)
                    if captcha_token:
                        data = {"g-recaptcha-response": captcha_token}
                        async with session.get(url, headers=headers, proxy=proxy, timeout=15, params=data) as retry_resp:
                            return retry_resp.status == 404
                return False
            else:
                return False
    except Exception:
        return False


async def worker():
    async with aiohttp.ClientSession() as session:
        while checking:
            try:
                username = await asyncio.wait_for(username_queue.get(), timeout=10)
            except asyncio.TimeoutError:
                continue
            in_progress_usernames.add(username)

            try:
                proxy = await asyncio.wait_for(proxy_queue.get(), timeout=15)
            except asyncio.TimeoutError:
                # No proxy available, requeue username and wait
                await username_queue.put(username)
                in_progress_usernames.discard(username)
                await asyncio.sleep(5)
                continue

            available = False
            try:
                available = await check_username(session, username, proxy)
            except Exception:
                available = False

            # Return proxy back to proxy queue if it is still valid by quick validation
            if proxy:
                is_valid = await validate_proxy(proxy, session)
                if is_valid:
                    await proxy_queue.put(proxy)
                else:
                    print(f"Proxy failed and removed: {proxy}")

            in_progress_usernames.discard(username)

            if available:
                await send_telegram_message(f"✅ Username available: <b>{username}</b>")
                checked_usernames.add(username)
            else:
                # Retry username with a new proxy (max 2 retries)
                if username not in failed_usernames:
                    failed_usernames.add(username)
                    await username_queue.put(username)  # retry once more
                else:
                    checked_usernames.add(username)

            username_queue.task_done()
            await asyncio.sleep(random.uniform(0.5, 1.5))


async def fill_queue(usernames):
    for u in usernames:
        if u not in checked_usernames:
            await username_queue.put(u)


async def refresh_proxies_loop():
    global raw_proxies
    while True:
        if checking:
            print("Refreshing proxies...")
            raw_proxies = await scrape_proxies()
            valid_proxies = await validate_proxies(raw_proxies)

            # Clear proxy_queue and refill with valid proxies
            while not proxy_queue.empty():
                try:
                    proxy_queue.get_nowait()
                    proxy_queue.task_done()
                except asyncio.QueueEmpty:
                    break
            for p in valid_proxies:
                await proxy_queue.put(p)

            print(f"Proxy pool refreshed with {len(valid_proxies)} proxies.")
        await asyncio.sleep(proxy_refresh_interval)


@app.post("/webhook")
async def telegram_webhook(req: Request):
    global checking

    data = await req.json()
    message = data.get("message") or data.get("edited_message")
    if not message or "text" not in message:
        return JSONResponse({"ok": True})

    text = message["text"].strip().lower()
    chat_id = message["chat"]["id"]
    if chat_id != CHAT_ID:
        return JSONResponse({"ok": True})

    if text == "/start":
        if checking:
            await send_telegram_message("Checker is already running.")
        else:
            checking = True
            # Reload proxies first
            global raw_proxies
            raw_proxies = await scrape_proxies()
            valid_proxies = await validate_proxies(raw_proxies)
            # Fill proxy queue with valid proxies
            for p in valid_proxies:
                await proxy_queue.put(p)
            # Load usernames
            wordlist = load_wordlist()
            await fill_queue(wordlist)
            await send_telegram_message(f"Started checker with {proxy_queue.qsize()} valid proxies and {username_queue.qsize()} usernames queued.")
            # Start workers
            for _ in range(CONCURRENCY):
                asyncio.create_task(worker())
            # Start proxy refresher task
            asyncio.create_task(refresh_proxies_loop())

    elif text == "/stop":
        if checking:
            checking = False
            await send_telegram_message("Stopped the checker.")
        else:
            await send_telegram_message("Checker is not running.")

    elif text == "/proxies":
        msg = f"Total proxies scraped: {len(raw_proxies)}\nProxies in pool: {proxy_queue.qsize()}"
        await send_telegram_message(msg)

    elif text == "/usernames":
        queued = username_queue.qsize()
        in_prog = len(in_progress_usernames)
        failed = len(failed_usernames)
        msg = (f"Usernames queued: {queued}\n"
               f"Usernames in progress: {in_prog}\n"
               f"Failed usernames: {failed}")
        await send_telegram_message(msg)

    return JSONResponse({"ok": True})


if __name__ == "__main__":
    import uvicorn
    print("Starting server...")
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
