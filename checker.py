import os
import re
import asyncio
import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")
TWO_CAPTCHA_KEY = os.getenv("TWO_CAPTCHA_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL") or "https://your-railway-app.up.railway.app/webhook"

app = FastAPI()

checking = False
proxies = []
username_queue = asyncio.Queue()
proxy_lock = asyncio.Lock()

def load_wordlist(file_path="wordlist.txt"):
    if not os.path.isfile(file_path):
        print(f"Wordlist file {file_path} not found!")
        return []
    with open(file_path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

async def send_telegram_message(text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()

async def answer_callback_query(callback_id, text=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()

async def set_telegram_webhook():
    print(f"Setting Telegram webhook to {WEBHOOK_URL}...")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
    params = {"url": WEBHOOK_URL}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            result = await resp.json()
            if result.get("ok"):
                print("Telegram webhook set successfully.")
            else:
                print(f"Failed to set webhook: {result}")

async def scrape_proxies():
    print("Scraping proxies from Webshare...")
    url = "https://proxy.webshare.io/api/proxy/list/"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                results = data.get("results", [])
                scraped = [f"{p['proxy_type'].lower()}://{p['proxy_address']}:{p['proxy_port']}" for p in results if p.get("proxy_address") and p.get("proxy_port")]
                print(f"Scraped {len(scraped)} proxies.")
                return scraped
            else:
                print(f"Failed to scrape proxies, status {resp.status}")
                return []

async def validate_proxy(proxy):
    test_url = "https://www.tiktok.com"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(test_url, proxy=proxy, timeout=5) as resp:
                return resp.status == 200
    except Exception:
        return False

async def validate_proxies(raw_proxies):
    print("Validating proxies...")
    valid = []
    tasks = []
    sem = asyncio.Semaphore(20)

    async def sem_validate(p):
        async with sem:
            if re.match(r"^(http|socks4|socks5)://\d+\.\d+\.\d+\.\d+:\d+$", p):
                if await validate_proxy(p):
                    valid.append(p)

    for p in raw_proxies:
        tasks.append(asyncio.create_task(sem_validate(p)))
    await asyncio.gather(*tasks)
    print(f"Validated {len(valid)} proxies.")
    return valid

async def solve_captcha(site_key, url, max_retries=20, sleep_interval=5):
    async with aiohttp.ClientSession() as session:
        submit_url = f"http://2captcha.com/in.php?key={TWO_CAPTCHA_KEY}&method=userrecaptcha&googlekey={site_key}&pageurl={url}&json=1"
        async with session.get(submit_url) as resp:
            res = await resp.json()
            if res.get("status") != 1:
                print(f"2Captcha submit failed: {res}")
                return None
            captcha_id = res.get("request")
        get_url = f"http://2captcha.com/res.php?key={TWO_CAPTCHA_KEY}&action=get&id={captcha_id}&json=1"

        for attempt in range(max_retries):
            await asyncio.sleep(sleep_interval)
            async with session.get(get_url) as resp:
                res = await resp.json()
                if res.get("status") == 1:
                    return res.get("request")
                elif res.get("request") == "CAPCHA_NOT_READY":
                    print(f"Captcha not ready, retry {attempt+1}/{max_retries}...")
                    continue
                else:
                    print(f"2Captcha error: {res}")
                    break
    return None

def extract_captcha_site_key(html_text):
    m = re.search(r'data-sitekey="([0-9a-zA-Z_-]+)"', html_text)
    if m:
        return m.group(1)
    m = re.search(r"sitekey\s*[:=]\s*['\"]([0-9a-zA-Z_-]+)['\"]", html_text)
    if m:
        return m.group(1)
    return None

async def check_username(session, username, proxy=None):
    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }

    try:
        async with session.get(url, headers=headers, proxy=proxy, timeout=15) as resp:
            text = await resp.text()
            if resp.status == 404:
                return True

            if "captcha" in text.lower() or resp.status in [403, 429]:
                site_key = extract_captcha_site_key(text)
                if site_key and TWO_CAPTCHA_KEY:
                    print(f"Captcha detected for {username}, solving...")
                    token = await solve_captcha(site_key, url)
                    if token:
                        headers["x-recaptcha-token"] = token
                        async with session.get(url, headers=headers, proxy=proxy, timeout=15) as resp2:
                            if resp2.status == 404:
                                return True
                            else:
                                return False
                else:
                    print(f"Captcha detected but missing site key or 2Captcha API key for {username}")
                    return False

            return False
    except Exception as e:
        print(f"Error checking {username}: {e}")
        return False

async def get_proxy():
    global proxies
    async with proxy_lock:
        if not proxies:
            return None
        proxy = proxies.pop(0)
        proxies.append(proxy)
        return proxy

async def worker():
    global checking
    async with aiohttp.ClientSession() as session:
        while checking:
            try:
                username = await asyncio.wait_for(username_queue.get(), timeout=10)
            except asyncio.TimeoutError:
                continue

            proxy = await get_proxy()
            available = await check_username(session, username, proxy)

            if not available and proxy:
                async with proxy_lock:
                    if proxy in proxies:
                        proxies.remove(proxy)
                await username_queue.put(username)
            else:
                username_queue.task_done()
                if available:
                    buttons = {
                        "inline_keyboard": [
                            [
                                {"text": "Claim", "callback_data": f"claim:{username}"},
                                {"text": "Skip", "callback_data": f"skip:{username}"},
                            ]
                        ]
                    }
                    await send_telegram_message(f"✅ Username available: <b>{username}</b>", reply_markup=buttons)

async def fill_queue(usernames):
    for u in usernames:
        await username_queue.put(u)

@app.post("/webhook")
async def telegram_webhook(req: Request):
    data = await req.json()
    if "callback_query" in data:
        cq = data["callback_query"]
        cid = cq["id"]
        data_text = cq["data"]
        if data_text.startswith("claim:"):
            username = data_text.split("claim:")[1]
            await answer_callback_query(cid, text=f"Trying to claim {username}...")
            await send_telegram_message(f"🟢 Trying to claim username: {username}")
        elif data_text.startswith("skip:"):
            username = data_text.split("skip:")[1]
            await answer_callback_query(cid, text=f"Skipped {username}")
        return JSONResponse({"ok": True})

    message = data.get("message") or data.get("edited_message")
    if message and "text" in message:
        text = message["text"].lower()
        chat_id = message["chat"]["id"]
        if chat_id != CHAT_ID:
            return JSONResponse({"ok": True})

        global checking
        if text == "/start":
            if checking:
                await send_telegram_message("Already running.")
            else:
                checking = True
                await send_telegram_message("Starting TikTok username checking...")
                asyncio.create_task(main_check_loop())
        elif text == "/stop":
            checking = False
            await send_telegram_message("Stopped TikTok username checking.")
        elif text == "/proxies":
            await send_telegram_message(f"Proxies available: {len(proxies)}")
        elif text == "/usernames":
            in_queue = username_queue.qsize()
            await send_telegram_message(f"Usernames in queue: {in_queue}")
    return JSONResponse({"ok": True})

async def main_check_loop():
    global proxies
    raw = await scrape_proxies()
    proxies = await validate_proxies(raw)

    if not proxies:
        await send_telegram_message("⚠️ No valid proxies found. Stopping.")
        return

    usernames = load_wordlist()
    if not usernames:
        await send_telegram_message("⚠️ No usernames to check. Stopping.")
        return

    await fill_queue(usernames)
    workers = [asyncio.create_task(worker()) for _ in range(20)]
    await username_queue.join()
    global checking
    checking = False
    await send_telegram_message("Finished checking all usernames.")

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    loop.create_task(set_telegram_webhook())
    uvicorn.run checker:app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
