import json
import asyncio
from playwright.async_api import async_playwright
from collections import defaultdict
import os

async def scrape_riviera():
    urls = [
        'https://riviera.vit.ac.in/',
        'https://riviera.vit.ac.in/events',
        'https://riviera.vit.ac.in/external-events',
        'https://riviera.vit.ac.in/merch',
        'https://riviera.vit.ac.in/team',
        'https://riviera.vit.ac.in/faq',
        'https://riviera.vit.ac.in/announcements'
    ]

    all_data = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Use a realistic user agent to avoid basic bot detection if any
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        for url in urls:
            print(f"Scraping: {url}")
            try:
                # Increased timeout and wait_until to ensure dynamic content loads
                await page.goto(url, wait_until="networkidle", timeout=60000)
                await asyncio.sleep(2) # Extra buffer for animations/late loads
                
                page_data = defaultdict(list)
                
                # Get all relevant text elements
                # We target headings for structure and p/li/div for content
                elements = await page.query_selector_all("h1, h2, h3, h4, h5, p, li, table, .faq-question, .event-name, .event-description")
                
                current_heading = "General Information"
                
                for el in elements:
                    tag_name = await el.evaluate("el => el.tagName.toLowerCase()")
                    text = await el.inner_text()
                    text = text.strip()
                    
                    if not text:
                        continue
                        
                    # If it looks like a heading, update current_heading
                    if tag_name.startswith("h") or "question" in (await el.get_attribute("class") or "").lower():
                        current_heading = text
                    else:
                        # Append to current heading
                        if text not in page_data[current_heading]:
                            page_data[current_heading].append(text)
                
                # Deduplicate and clean
                all_data[url] = {k: v for k, v in page_data.items() if v}
                
            except Exception as e:
                print(f"Error scraping {url}: {e}")

        await browser.close()

    # Save in the same directory as vit_chunks.json for main.py to find
    output_path = os.path.join(os.path.dirname(__file__), '..', 'riviera_chunks.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Done: {output_path} saved.")

if __name__ == "__main__":
    asyncio.run(scrape_riviera())
