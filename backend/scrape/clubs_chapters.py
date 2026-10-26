from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
import json

# ---------------------------
# SET YOUR URLS HERE
# ---------------------------
URLS = [
    'https://vit.ac.in/campus/clubs/artscultural',
    'https://vit.ac.in/campus/clubs/technical',
    'https://vit.ac.in/campus/clubs/social%2520outreach',
    'https://vit.ac.in/campus/clubs/healthwellness',
    'https://vit.ac.in/campus/clubs/literature',
    'https://vit.ac.in/environmental-sustainability',
    'https://vit.ac.in/campus/chapters/indiansocieties',
    'https://vit.ac.in/campus/chapters/international-societies',
    'https://vit.ac.in/campus/chapters/ieeechapters'
]

# ---------------------------
# SETUP DRIVER
# ---------------------------
options = Options()
options.add_argument("--start-maximized")
options.add_argument("--disable-blink-features=AutomationControlled")

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=options
)

wait = WebDriverWait(driver, 15)

# ---------------------------
# CONVERT LIST → DICT
# ---------------------------
def convert_to_dict(data_list):
    result = {}

    for item in data_list:
        parts = item.split("\n", 1)

        if len(parts) == 2:
            name = parts[0].strip()
            description = " ".join(parts[1].split())  # clean spacing
        else:
            name = parts[0].strip()
            description = ""

        result[name] = description

    return result


# ---------------------------
# SCRAPER FUNCTION
# ---------------------------
def scrape_popup_page(url):
    print(f"\n🔗 Scraping: {url}")
    driver.get(url)

    time.sleep(5)

    try:
        cards = wait.until(EC.presence_of_all_elements_located(
            (By.CSS_SELECTOR, ".eae-popup-link")
        ))
    except:
        print("❌ No popup cards found")
        return {}

    print(f"Found {len(cards)} cards")

    section_data = []

    for i in range(len(cards)):
        try:
            cards = driver.find_elements(By.CSS_SELECTOR, ".eae-popup-link")
            card = cards[i]

            driver.execute_script("arguments[0].scrollIntoView(true);", card)
            time.sleep(1)

            driver.execute_script("arguments[0].click();", card)

            popup = wait.until(EC.visibility_of_element_located(
                (By.CSS_SELECTOR, ".mfp-content")
            ))

            text = popup.text.strip()
            section_data.append(text)

            print(f"✔ Item {i+1}")

            # Close popup safely
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
            print(f"Error at {i}: {e}")
            continue

    # Get section title
    try:
        title = driver.find_element(By.TAG_NAME, "h1").text.strip()
    except:
        title = url.split("/")[-1]

    # ✅ Convert to structured dict
    structured_data = convert_to_dict(section_data)

    return {title: structured_data}


# ---------------------------
# MAIN LOOP
# ---------------------------
final_output = {}

for url in URLS:
    result = scrape_popup_page(url)
    final_output[url] = result

driver.quit()

# ---------------------------
# SAVE FILE
# ---------------------------
with open("vit_all_data.json", "w", encoding="utf-8") as f:
    json.dump(final_output, f, indent=4, ensure_ascii=False)

print("\n✅ ALL DONE")


            