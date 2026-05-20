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
    'https://vit.ac.in/instruction',
    'https://vit.ac.in/counselling-division'
]

# 🔥 HEADERS / FOOTERS / COMMON SECTIONS TO REMOVE
REMOVE_HEADINGS = {
    "VIT @ Connect",
    "Other Links",
    "Quick Links",
    "VISITORS",
    "Committees @ VIT",
    "Don't Trust Fake Website/ Page / Channels",
    "BEWARE OF ILLEGAL/FAKE WEBSITES",
    "Last Updated : June 2025",
    "Undergraduate Admission",
    "Undergraduate NRI / Foreign Admission",
    "Postgraduate Admission",
    "Postgraduate NRI / Foreign Admission",
    "Research",
    "Research NRI / Foreign",
    "VIT Online Education",
    "Others",
    "Beware of VITEEE fake websites",
    "Announcements",
    "Career Development Centre",
    "Recruiting Companies",
    "International Admission",
    "Research Organisation",
    "Students Welfare"
}

# 🔥 COMMON TEXTS TO REMOVE
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

all_data = {}

for url in urls:
    print(f"Scraping: {url}")

    try:
        response = requests.get(url, timeout=20)
        soup = BeautifulSoup(response.text, 'html.parser')

        # 🔥 REMOVE HEADER / FOOTER / NAV / SIDEBAR
        for tag in soup.find_all([
            'header',
            'footer',
            'nav',
            'aside'
        ]):
            tag.decompose()

        # 🔥 REMOVE COMMON DIVS
        for div in soup.find_all(
            class_=lambda x: x and any(
                k in str(x).lower()
                for k in [
                    'header',
                    'footer',
                    'menu',
                    'navigation',
                    'sidebar',
                    'announcement',
                    'breadcrumb',
                    'popup',
                    'newsletter'
                ]
            )
        ):
            div.decompose()

        page_data = defaultdict(list)

        current_heading = (
            f"{url.split('/')[-1]} - Introduction"
        )

        for elem in soup.find_all([
            'h1', 'h2', 'h3',
            'p', 'table', 'ul', 'ol'
        ]):

            # 🔹 HEADINGS
            if elem.name.startswith('h'):

                heading = elem.get_text(
                    separator=' ',
                    strip=True
                )

                if heading:
                    current_heading = heading

                continue

            # 🔥 SKIP COMMON HEADINGS
            if current_heading in REMOVE_HEADINGS:
                continue

            texts = []
            links = []

            # 🔹 TEXT EXTRACTION
            for t in elem.stripped_strings:
                cleaned = t.strip()

                if cleaned:
                    texts.append(cleaned)

            # 🔹 LINK EXTRACTION
            for a in elem.find_all('a', href=True):

                link_text = a.get_text(strip=True)
                link_url = urljoin(url, a['href'])

                if (
                    link_url and
                    not link_url.startswith("javascript")
                ):
                    links.append(
                        f"{link_text} ({link_url})"
                    )

            # 🔹 MERGE
            combined = " ".join(texts)

            if links:
                combined += " | " + " | ".join(links)

            combined = combined.strip()

            # 🔥 SKIP EMPTY
            if not combined:
                continue

            # 🔥 REMOVE COMMON FOOTER TEXTS
            skip = False

            for bad_text in REMOVE_TEXT_CONTAINS:
                if bad_text.lower() in combined.lower():
                    skip = True
                    break

            if skip:
                continue

            # 🔥 REMOVE VERY SHORT GARBAGE
            if len(combined) < 8:
                continue

            # 🔥 REMOVE DUPLICATES
            if combined not in page_data[current_heading]:
                page_data[current_heading].append(combined)

        # 🔹 FAQ EXTRACTION
        faqs = soup.select(
            '.elementor-tab-title, .elementor-tab-content'
        )

        current_q = None

        for elem in faqs:

            classes = elem.get('class', [])

            if 'elementor-tab-title' in classes:

                current_q = elem.get_text(
                    strip=True
                )

            elif 'elementor-tab-content' in classes:

                answer = elem.get_text(
                    strip=True
                )

                if current_q and answer:

                    faq_text = (
                        f"Q: {current_q} | "
                        f"A: {answer}"
                    )

                    # 🔥 FILTER FAQ GARBAGE
                    if not any(
                        bad.lower() in faq_text.lower()
                        for bad in REMOVE_TEXT_CONTAINS
                    ):
                        page_data[
                            "Frequently Asked Questions"
                        ].append(faq_text)

        # 🔥 REMOVE EMPTY HEADINGS
        cleaned_page_data = {}

        for heading, content in page_data.items():

            if (
                heading not in REMOVE_HEADINGS
                and content
            ):
                cleaned_page_data[heading] = content

        all_data[url] = cleaned_page_data

    except Exception as e:
        print(f"❌ Error scraping {url}")
        print(e)

# 🔹 SAVE JSON
with open(
    'vit_final_with_links.json',
    'w',
    encoding='utf-8'
) as f:

    json.dump(
        all_data,
        f,
        indent=2,
        ensure_ascii=False
    )

print("\n✅ Done: Clean JSON saved.")

