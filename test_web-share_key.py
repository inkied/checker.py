import asyncio
import aiohttp

WEBSHARE_API_KEY = "n4v8l3c6i2u7xn0w89nc6f5f9fbst0375oqj7gfi"
PROXY_API_URL = "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=10"

async def test_webshare_api():
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(PROXY_API_URL, headers=headers) as resp:
            if resp.status != 200:
                print(f"Error: Received status code {resp.status}")
                text = await resp.text()
                print(f"Response: {text}")
                return
            data = await resp.json()
            print("API call succeeded. Proxies fetched:")
            for item in data.get("results", []):
                proxy_address = item.get("proxy_address")
                ports = item.get("ports")
                if proxy_address and ports:
                    print(f"{proxy_address}:{ports.get('http', 'no-port')}")
                else:
                    print(f"Incomplete proxy info: {item}")

asyncio.run(test_webshare_api())
