"""
zara_scraper.py
Scrapes up to 30 products from a Zara search results page and saves to `zara_products.csv`.
Uses Playwright for reliable JS rendering and automatic browser management.

Usage:
  pip install -r requirements.txt
  pip install playwright
  playwright install chromium
  python zara_scraper.py

Notes:
 - Respect Zara's robots.txt and terms of service before running repeatedly.
 - Script is polite: it scrolls slowly and includes delays.
"""

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import csv
import time
import random

URL = "https://www.zara.com/es/en/search?searchTerm=zara%20top%20gate&section=WOMAN"
TARGET = 30
OUTPUT = "zara_products.csv"

SCROLL_PAUSE = 1.0
MAX_SCROLL_ATTEMPTS = 60

SELECTOR_CANDIDATES = [
    "article[data-qa-id='product']",
    "article.product-grid-product",
    ".product-grid-product",
    ".product-grid-product__container",
    "a.product-link",
    "div.product-card"
]

PRICE_SELECTORS = [
    ".price__amount",
    ".product-price",
    ".price"
]


def extract_from_element(el):
    # Try to get the product url
    href = None
    try:
        a = el.query_selector("a[href]")
        if a:
            href = a.get_attribute("href")
            if href and href.startswith("/"):
                href = "https://www.zara.com" + href
    except Exception:
        href = None

    # image
    img = None
    try:
        i = el.query_selector("img")
        if i:
            img = i.get_attribute("src") or i.get_attribute("data-src") or i.get_attribute("data-lazy")
    except Exception:
        img = None

    # title: try alt, aria-label, or visible text
    title = None
    try:
        if i:
            title = i.get_attribute("alt")
        if not title:
            title = el.get_attribute("aria-label")
        if not title:
            text = el.inner_text()
            if text:
                # first line is often the title
                title = text.splitlines()[0]
    except Exception:
        title = title or ""

    # price
    price = ""
    for sel in PRICE_SELECTORS:
        try:
            p = el.query_selector(sel)
            if p:
                price = p.inner_text().strip()
                if price:
                    break
        except Exception:
            continue

    return {
        "title": (title or "").strip(),
        "price": price,
        "url": href or "",
        "image": img or ""
    }


def find_elements(page):
    for sel in SELECTOR_CANDIDATES:
        try:
            elems = page.query_selector_all(sel)
            if elems and len(elems) > 0:
                return elems
        except Exception:
            continue
    return []


def run():
    products = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                                   "(KHTML, like Gecko) Chrome/117.0 Safari/537.36"))
        page = context.new_page()
        page.set_default_timeout(15000)
        print("Loading page...")
        page.goto(URL)

        scroll_attempts = 0
        last_count = 0
        while len(products) < TARGET and scroll_attempts < MAX_SCROLL_ATTEMPTS:
            # Wait for product cards to appear
            try:
                page.wait_for_timeout(500)
            except PlaywrightTimeout:
                pass

            elems = find_elements(page)
            for el in elems:
                try:
                    info = extract_from_element(el)
                    if info["url"] and info["url"] not in products:
                        products[info["url"]] = info
                        print(f"Found ({len(products)}) - {info['title']} - {info['price']}")
                        if len(products) >= TARGET:
                            break
                except Exception:
                    continue

            # If not enough products yet, scroll further
            if len(products) >= TARGET:
                break

            scroll_attempts += 1
            page.evaluate("() => window.scrollBy(0, window.innerHeight)")
            # small random delay to reduce load
            time.sleep(SCROLL_PAUSE + random.random() * 0.8)

            # if no new items after a few attempts, try clicking 'load more' style buttons
            if len(products) == last_count:
                # try click a 'show more' if exists
                try:
                    btn = page.query_selector("button[data-qa-id='load-more']") or page.query_selector("button.load-more")
                    if btn:
                        btn.click()
                        time.sleep(1)
                except Exception:
                    pass
            last_count = len(products)

        browser.close()

    # write CSV
    items = list(products.values())[:TARGET]
    if items:
        with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["title", "price", "image", "url"])
            writer.writeheader()
            for it in items:
                writer.writerow(it)
        print(f"Wrote {len(items)} products to {OUTPUT}")
    else:
        print("No products found. You may need to adjust selectors or run with a non-headless browser to inspect the page.")


if __name__ == "__main__":
    run()
