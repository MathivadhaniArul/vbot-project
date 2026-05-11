import requests
from bs4 import BeautifulSoup
from collections import defaultdict
import json
from urllib.parse import urljoin

urls = [
    'https://vit.ac.in/admissions/international/btech-eligibilityandprocedure',
    'https://vit.ac.in/cdc-overview',
    'https://vit.ac.in/cdc-highlights',
    'https://vit.ac.in/stars-support-advancement-rural-students',
    'https://vit.ac.in/admissions/international/otherugprogrammes',
    'https://vit.ac.in/admissions/international/pg',
    'https://vit.ac.in/admissions/international/integrated',
    'https://vit.ac.in/admissions/international/research',
    'https://vit.ac.in/admissions/international/fee',
    'https://vit.ac.in/academics/library#',
    'https://vit.ac.in/coe-email-contacts',
    'https://vit.ac.in/academics/coe',
    'https://vit.ac.in/counselling-division',
    'https://vit.ac.in/internal-complaints-committee',
    'https://vit.ac.in/service-and-support-differently-abled-learners-sasdal',
    'https://vit.ac.in/academics/iqac',
    'https://vit.ac.in/mentoring-committee-for-higher-studies',
    'https://vit.ac.in/equal-opportunity-cell',
    'https://vit.ac.in/sc-st-cell',
    'https://vit.ac.in/vit-privacy-policy/',
    'https://vit.ac.in/scholarship',
    'https://vit.ac.in/instruction'
]

all_data = {}

for url in urls:
    print(f"Scraping: {url}")
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    page_data = defaultdict(list)
    current_heading = f"{url.split('/')[-1]} - Introduction"

    for elem in soup.find_all(['h1', 'h2', 'h3', 'p', 'table', 'ul', 'ol']):

        if elem.name and elem.name.startswith('h'):
            current_heading = elem.get_text(strip=True) or current_heading

        else:
            texts = []
            links = []

            # 🔹 Extract text
            for t in elem.stripped_strings:
                texts.append(t.strip())

            # 🔹 Extract links
            for a in elem.find_all('a', href=True):
                link_text = a.get_text(strip=True)
                link_url = urljoin(url, a['href'])

                if link_url and not link_url.startswith("javascript"):
                    # keep only useful links (optional filter)
                    if any(x in link_url.lower() for x in ['pdf', 'download', 'form', 'apply']):
                        links.append(f"{link_text} ({link_url})")
                    else:
                        links.append(f"{link_text} ({link_url})")

            # 🔹 Merge text + links into SAME LIST (your format)
            combined = " ".join(texts)

            # Append links into text
            if links:
                combined += " | " + " | ".join(links)

            if combined.strip():
                page_data[current_heading].append(combined)

    # 🔹 FAQ extraction
    faqs = soup.select('.elementor-tab-title, .elementor-tab-content')
    current_q = None

    for elem in faqs:
        classes = elem.get('class', [])

        if 'elementor-tab-title' in classes:
            current_q = elem.get_text(strip=True)

        elif 'elementor-tab-content' in classes:
            answer = elem.get_text(strip=True)

            if current_q and answer:
                page_data["Frequently Asked Questions"].append(
                    f"Q: {current_q} | A: {answer}"
                )

    all_data[url] = dict(page_data)

# 🔹 SAVE
with open('vit_final_with_links.json', 'w', encoding='utf-8') as f:
    json.dump(all_data, f, indent=2, ensure_ascii=False)

print("\n✅ Done: JSON with links saved.")