import asyncio
from pipeline.fetcher import fetch_page

async def run():
    target = {"url": "https://vit.ac.in/counselling-division", "fetch_mode": "static"}
    try:
        result = await fetch_page(target)
        print(f"Success: {result.success}")
        print(f"Error: {result.error}")
        print(f"Length: {result.content_length}")
    except Exception as e:
        print(f"Exception: {e}")

asyncio.run(run())
