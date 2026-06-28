
import requests
from bs4 import BeautifulSoup
from collections import defaultdict
import json
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time


urls = [
    'https://vit.ac.in/school/course/vsign/ug',
     'https://vit.ac.in/all-courses/ug/bachelor-of-design-programme',  
]


REMOVE_HEADINGS = {
    "VIT @ Connect",
    "Other Links",
    "Quick Links",
    "VISITORS",
    "Committees @ VIT",
    "Don't Trust Fake Website/ Page / Channels",
    "BEWARE OF ILLEGAL/FAKE WEBSITES",
    "Last Updated",
    "Others",
    "Beware of VITEEE fake websites",
    "Announcements"
}

REMOVE_TEXT_CONTAINS = [
    "Campus Tour",
    "Student Login",
    "Parent Login",
    "VIT Intranet",
    "VITAA Website",
    "Last Updated:",
    "Copyrights ©",
    "Admissions Open",
    "Beware of fraudulent",
]


def is_bad_heading(text: str) -> bool:
    if not text:
        return False
    t = text.strip().lower()
    return any(h.lower() in t for h in REMOVE_HEADINGS)



def load_existing(filepath: str) -> dict:
    p = Path(filepath)
    if p.exists():
        try:
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}



def clean_data(data: dict) -> dict:
    cleaned = {}
    for url, sections in data.items():
        if not sections:
            continue

        clean_sections = {}
        for heading, content in sections.items():
            if not heading.strip():
                continue
            if not content:
                continue
            if isinstance(content, dict) and not any(content.values()):
                continue
            if isinstance(content, list) and not any(
                item.strip() if isinstance(item, str) else item
                for item in content
            ):
                continue
            clean_sections[heading] = content

        if clean_sections:
            cleaned[url] = clean_sections

    return cleaned



def save_json(filepath: str, new_data: dict):
    existing = load_existing(filepath)
    existing.update(new_data)
    cleaned = clean_data(existing)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(cleaned, f, indent=2, ensure_ascii=False)
    print(f"   Saved to {filepath} ({len(cleaned)} URLs total)")



def scrape_url(url):
    print(f"\nScraping: {url}")
    try:
        response = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Connection": "keep-alive",
            }
        )
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')

        # Remove layout noise
        for tag in soup.find_all(['header', 'footer', 'nav', 'aside']):
            tag.decompose()

        for div in soup.find_all(class_=lambda x: x and any(
            k in str(x).lower()
            for k in ['header', 'footer', 'menu', 'navigation', 'sidebar',
                      'announcement', 'breadcrumb', 'popup', 'newsletter']
        )):
            div.decompose()

        page_data = defaultdict(list)
        current_heading = f"{url.split('/')[-1]} - Introduction"

        for elem in soup.find_all(['h1', 'h2', 'h3', 'p', 'table', 'ul', 'ol']):
            if elem.name.startswith('h'):
                heading = elem.get_text(separator=' ', strip=True)
                if heading:
                    current_heading = heading
                continue

            if is_bad_heading(current_heading):
                continue

            texts = []
            links = []

            for t in elem.stripped_strings:
                cleaned = t.strip()
                if cleaned:
                    texts.append(cleaned)

            for a in elem.find_all('a', href=True):
                link_text = a.get_text(strip=True)
                link_url = urljoin(url, a['href'])
                if link_url and not link_url.startswith("javascript"):
                    links.append(f"{link_text} ({link_url})")

            combined = " ".join(texts)
            if links:
                combined += " | " + " | ".join(links)
            combined = combined.strip()

            if not combined:
                continue
            if any(bad.lower() in combined.lower() for bad in REMOVE_TEXT_CONTAINS):
                continue
            if len(combined) < 8:
                continue
            if combined not in page_data[current_heading]:
                page_data[current_heading].append(combined)

        # FAQ extraction
        faqs = soup.select('.elementor-tab-title, .elementor-tab-content')
        current_q = None

        for elem in faqs:
            classes = elem.get('class', [])
            if 'elementor-tab-title' in classes:
                current_q = elem.get_text(strip=True)
            elif 'elementor-tab-content' in classes:
                answer = elem.get_text(strip=True)
                if current_q and answer:
                    faq_text = f"Q: {current_q} | A: {answer}"
                    if not any(bad.lower() in faq_text.lower() for bad in REMOVE_TEXT_CONTAINS):
                        page_data["Frequently Asked Questions"].append(faq_text)

        cleaned_page_data = {
            heading: content
            for heading, content in page_data.items()
            if not is_bad_heading(heading) and content
        }

        return url, cleaned_page_data

    except Exception as e:
        print(f" Error scraping {url}: {e}")
        return url, {}



all_data = {}
with ThreadPoolExecutor(max_workers=5) as executor:
    futures = {executor.submit(scrape_url, url): url for url in urls}
    for future in as_completed(futures):
        url, data = future.result()
        if data:
            all_data[url] = data


save_json('filter1.json', all_data)
print("\n FILTER 1 DONE")


# ---------------------------
# SELENIUM SETUP (FILTER 2)
# ---------------------------
options = Options()
options.add_argument("--start-maximized")
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_argument("--disable-extensions")
options.add_argument("--disable-infobars")
options.add_argument("--no-first-run")
options.add_argument("--disable-default-apps")
options.add_argument("--blink-settings=imagesEnabled=false")
options.page_load_strategy = 'eager'

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=options
)

wait = WebDriverWait(driver, 8)


# ---------------------------
# CONVERT LIST → DICT
# ---------------------------
def convert_to_dict(data_list):
    result = {}
    for item in data_list:
        if is_bad_heading(item):
            continue
        parts = item.split("\n", 1)
        if len(parts) == 2:
            name = parts[0].strip()
            description = " ".join(parts[1].split())
        else:
            name = parts[0].strip()
            description = ""
        if not is_bad_heading(name):
            result[name] = description
    return result


# ---------------------------
# POPUP SCRAPER
# ---------------------------
def scrape_popup_page(url):
    print(f"\n🔗 Scraping popups: {url}")
    driver.get(url)

    try:
        cards = wait.until(EC.presence_of_all_elements_located(
            (By.CSS_SELECTOR, ".eae-popup-link")
        ))
        print(f"  → Found {len(cards)} items")
    except:
        print(" No popup cards found")
        return {}

    section_data = []

    for i in range(len(cards)):
        try:
            cards = driver.find_elements(By.CSS_SELECTOR, ".eae-popup-link")
            card = cards[i]

            driver.execute_script("arguments[0].scrollIntoView(true);", card)
            time.sleep(0.3)

            driver.execute_script("arguments[0].click();", card)

            popup = wait.until(EC.visibility_of_element_located(
                (By.CSS_SELECTOR, ".mfp-content")
            ))

            text = popup.text.strip()

            if is_bad_heading(text):
                print(f"  → Skipping item {i+1} — noise")
                continue

            section_data.append(text)
            print(f"  ✔ Item {i+1}")

            try:
                close_btn = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, ".mfp-close")
                ))
                driver.execute_script("arguments[0].click();", close_btn)
            except:
                driver.execute_script(
                    "document.dispatchEvent(new KeyboardEvent('keydown', {'key':'Escape'}));"
                )

            wait.until(EC.invisibility_of_element_located(
                (By.CSS_SELECTOR, ".mfp-content")
            ))

        except Exception as e:
            print(f"   Error at item {i+1}: {e}")
            continue

    try:
        title_raw = driver.find_element(By.TAG_NAME, "h1").text.strip()
        title = "Filtered Section" if is_bad_heading(title_raw) else title_raw
    except:
        title = url.split("/")[-1]

    structured_data = convert_to_dict(section_data)

    if is_bad_heading(title):
        return {}

    return {title: structured_data}


# ---------------------------
# MAIN LOOP
# ---------------------------
final_output = {}

for url in urls:
    result = scrape_popup_page(url)
    if result:
        final_output[url] = result

driver.quit()

# Save Filter 2
save_json('filter2.json', final_output)
print("\nFILTER 2 DONE")
