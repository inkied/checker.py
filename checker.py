import os
import asyncio
import aiohttp
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.executor import start_polling

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tiktok-checker")

TELEGRAM_API_TOKEN = os.getenv("TELEGRAM_API_TOKEN")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Your server HTTPS URL + /webhook if using webhook mode
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")

if not all([TELEGRAM_API_TOKEN, TELEGRAM_CHAT_ID, WEBSHARE_API_KEY]):
    logger.error("Missing one or more required environment variables.")
    exit(1)

# Themed words raw file URL
THEMED_WORDS_URL = "https://raw.githubusercontent.com/inkied/checker.py/main/themed_words.txt"

# Constants
MAX_CONCURRENT_CHECKS = 20
PROXY_RETRY_LIMIT = 3
USERNAME_BATCH_SIZE = 5
CHECK_COOLDOWN = 1.5  # seconds between username checks to avoid rate limits

bot = Bot(token=TELEGRAM_API_TOKEN)
dp = Dispatcher(bot)

usernames = []
proxies = []
checking = False
current_task = None

# Inline keyboard for start/stop buttons
keyboard = InlineKeyboardMarkup(row_width=2).add(
    InlineKeyboardButton("Start", callback_data="start"),
    InlineKeyboardButton("Stop", callback_data="stop"),
)


async def fetch_themed_words():
    logger.info("Loading themed words list...")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(THEMED_WORDS_URL) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    # Parse words by splitting lines and commas
                    lines = [line.strip() for line in text.splitlines() if line.strip()]
                    loaded_words = []
                    for line in lines:
                        if ":" in line:
                            _, words_str = line.split(":", 1)
                            words = [w.strip() for w in words_str.split(",") if w.strip()]
                            loaded_words.extend(words)
                    logger.info(f"Loaded {len(loaded_words)} themed words.")
                    return loaded_words
                else:
                    logger.error(f"Failed to load themed words file: HTTP {resp.status}")
                    return []
        except Exception as e:
            logger.error(f"Exception loading themed words: {e}")
            return []


async def fetch_proxies():
    logger.info("Fetching proxies from Webshare API...")
    url = f"https://proxy.webshare.io/api/proxy/list/?page=1&page_size=100"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    proxy_list = []
                    for proxy in data.get("results", []):
                        ip = proxy.get("proxy_address")
                        port = proxy.get("proxy_port")
                        username = proxy.get("proxy_username")
                        password = proxy.get("proxy_password")
                        if ip and port:
                            # Format proxy string for aiohttp (http or socks5)
                            proxy_str = f"http://{username}:{password}@{ip}:{port}" if username and password else f"http://{ip}:{port}"
                            proxy_list.append(proxy_str)
                    logger.info(f"Fetched {len(proxy_list)} proxies.")
                    return proxy_list
                else:
                    logger.error(f"Failed to fetch proxies: HTTP {resp.status}")
                    return []
        except Exception as e:
            logger.error(f"Exception fetching proxies: {e}")
            return []


async def check_proxy_health(proxy_url):
    test_url = "https://www.tiktok.com"
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(test_url, proxy=proxy_url) as resp:
                if resp.status == 200:
                    return True
    except Exception:
        pass
    return False


async def validate_proxies(proxy_list):
    logger.info("Validating proxies...")
    valid = []
    for proxy in proxy_list:
        healthy = await check_proxy_health(proxy)
        if healthy:
            valid.append(proxy)
    logger.info(f"{len(valid)} proxies are healthy and ready.")
    return valid


async def check_username_availability(username, proxy=None):
    url = f"https://www.tiktok.com/@{username}"
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, proxy=proxy, allow_redirects=False) as resp:
                # TikTok returns 404 if username available
                if resp.status == 404:
                    return True
                # 200 means username taken
                elif resp.status == 200:
                    return False
                else:
                    logger.debug(f"Unexpected status for {username}: {resp.status}")
                    return False
    except Exception as e:
        logger.debug(f"Error checking {username}: {e}")
        return False


async def send_available_usernames(available):
    if not available:
        return
    message = "**Available TikTok usernames found:**\n" + "\n".join(available)
    await bot.send_message(TELEGRAM_CHAT_ID, message)


async def username_check_loop():
    global checking
    proxy_index = 0
    available_usernames_batch = []

    while checking:
        for username in usernames:
            proxy = None
            if proxies:
                proxy = proxies[proxy_index % len(proxies)]
                proxy_index += 1

            is_available = await check_username_availability(username, proxy)
            if is_available:
                available_usernames_batch.append(username)
                logger.info(f"Available username found: {username}")

            if len(available_usernames_batch) >= USERNAME_BATCH_SIZE:
                await send_available_usernames(available_usernames_batch)
                available_usernames_batch = []

            await asyncio.sleep(CHECK_COOLDOWN)

        # After one full pass, loop again or stop if checking turned off
        if not checking:
            break

    # Send any leftover available usernames
    if available_usernames_batch:
        await send_available_usernames(available_usernames_batch)


@dp.callback_query_handler(lambda c: c.data in ["start", "stop"])
async def handle_start_stop(call: types.CallbackQuery):
    global checking, current_task

    if call.data == "start":
        if checking:
            await call.answer("Already running.")
            return
        checking = True
        current_task = asyncio.create_task(username_check_loop())
        await call.answer("Started TikTok username checking.")
        await bot.send_message(TELEGRAM_CHAT_ID, "✅ Checker started.", reply_markup=keyboard)

    elif call.data == "stop":
        if not checking:
            await call.answer("Not running.")
            return
        checking = False
        if current_task:
            current_task.cancel()
            current_task = None
        await call.answer("Stopped TikTok username checking.")
        await bot.send_message(TELEGRAM_CHAT_ID, "⏹️ Checker stopped.", reply_markup=keyboard)


@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    await message.answer("Welcome! Use the buttons below to start or stop checking usernames.", reply_markup=keyboard)


async def set_webhook():
    if WEBHOOK_URL:
        logger.info("Setting Telegram webhook...")
        async with aiohttp.ClientSession() as session:
            webhook_set_url = f"https://api.telegram.org/bot{TELEGRAM_API_TOKEN}/setWebhook?url={WEBHOOK_URL}"
            async with session.post(webhook_set_url) as resp:
                if resp.status == 200:
                    logger.info("Webhook set successfully.")
                else:
                    logger.error(f"Failed to set webhook: HTTP {resp.status}")


async def main():
    global usernames, proxies

    # Load themed usernames
    usernames = await fetch_themed_words()
    if not usernames:
        logger.error("No usernames loaded. Exiting.")
        return

    # Fetch and validate proxies
    proxy_list = await fetch_proxies()
    if not proxy_list:
        logger.error("No proxies fetched. Exiting.")
        return

    proxies = await validate_proxies(proxy_list)
    if not proxies:
        logger.error("No healthy proxies. Exiting.")
        return

    await set_webhook()

    logger.info("Starting bot polling...")
    await dp.start_polling()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
