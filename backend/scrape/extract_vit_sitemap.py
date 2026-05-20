import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse
from collections import deque
import time

visited = set()
queue = deque()

MAX_PAGES = 2500
MAX_DEPTH = 3

session = requests.Session()  # 🔥 reuse connections (big speed boost)

def normalize(url):
    parsed = urlparse(url)

    # remove query + fragment
    clean = parsed._replace(query="", fragment="")

    # remove trailing slash
    return urlunparse(clean).rstrip("/")


def is_valid(url):
    parsed = urlparse(url)

    # only VIT domain
    if parsed.netloc != "vit.ac.in":
        return False

    # 🚫 skip junk
    if any(x in url for x in [
        "mailto:", "tel:", ".jpg", ".png", ".jpeg", ".zip", "login", "signup",".webp",".mp4"
    ]):
        return False

    return True


def crawl(start_url):
    queue.append((start_url, 0))

    while queue and len(visited) < MAX_PAGES:
        url, depth = queue.popleft()
        url = normalize(url)

        if url in visited or depth > MAX_DEPTH:
            continue

        visited.add(url)
        print(f"[{len(visited)}] {url}")

        try:
            res = session.get(url, timeout=5)
            soup = BeautifulSoup(res.text, "lxml")

            for a in soup.find_all("a", href=True):
                link = urljoin(url, a["href"])
                link = normalize(link)

                if is_valid(link) and link not in visited:
                    queue.append((link, depth + 1))

        except Exception:
            continue

        time.sleep(0.2)  # 🔥 polite crawling (avoid ban)


# 🚀 start
crawl("https://vit.ac.in/campus-category/clubs")

# 💾 save
with open("vit_fast_urls.txt", "w", encoding="utf-8") as f:
    for u in sorted(visited):
        f.write(u + "\n")

print("\n✅ Done:", len(visited))