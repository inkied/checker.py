import os
import sys
import asyncio
import aiohttp
import time
import random
from collections import deque
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

# === LOAD AND VALIDATE ENV ===
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://checker.up.railway.app/webhook")

def exit_with_error(msg):
    print(f"❌ ENV ERROR: {msg}")
    sys.exit(1)

if not TELEGRAM_TOKEN:
    exit_with_error("Missing TELEGRAM_TOKEN in .env")
if not TELEGRAM_CHAT_ID:
    exit_with_error("Missing TELEGRAM_CHAT_ID in .env")
if not WEBSHARE_API_KEY:
    exit_with_error("Missing WEBSHARE_API_KEY in .env")

try:
    TELEGRAM_CHAT_ID = int(TELEGRAM_CHAT_ID)
except ValueError:
    exit_with_error("TELEGRAM_CHAT_ID must be a valid integer")

telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
