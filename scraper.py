#!/usr/bin/env python3
"""
Simple scraper for http://books.toscrape.com

Collects: title, price (float GBP), rating (1-5), number_of_reviews (int or -1),
product_page_url, scraped_at (ISO UTC). Implements polite scraping (User-Agent,
1s delay), retries (3 attempts), checkpointing to `checkpoint.json`, and
appends page results to `products.csv` as it runs. After finishing the run the
script deduplicates by product `title` and saves a cleaned `products.csv`.

Usage: python scraper.py

Note: Requires `requests` and `beautifulsoup4`.
"""

import csv
import json
import logging
import os
import time
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "http://books.toscrape.com/"
CHECKPOINT = "checkpoint.json"
OUT_CSV = "products.csv"
USER_AGENT = (
    "Mozilla/5.0 (compatible; WebMiningScraper/1.0; +https://example.com/bot)"
)
REQUEST_TIMEOUT = 10
RETRY_ATTEMPTS = 3
POLITE_DELAY = 1.0  # seconds between requests

RATING_MAP = {
    "One": 1,
    "Two": 2,
    "Three": 3,
    "Four": 4,
    "Five": 5,
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def retry_get(session: requests.Session, url: str) -> Optional[requests.Response]:
    """GET with simple retry logic.

    Returns Response on success or None on failure after retries.
    """
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                time.sleep(POLITE_DELAY)
                return resp
            logging.warning("Non-200 status %s for %s (attempt %d)", resp.status_code, url, attempt)
        except requests.RequestException as e:
            logging.warning("Request error for %s: %s (attempt %d)", url, e, attempt)
        if attempt < RETRY_ATTEMPTS:
            time.sleep(POLITE_DELAY)
    logging.error("Failed to GET %s after %d attempts", url, RETRY_ATTEMPTS)
    return None


def load_checkpoint():
    if os.path.exists(CHECKPOINT):
        try:
            with open(CHECKPOINT, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            logging.exception("Failed to load checkpoint, starting fresh")
    return {}


def save_checkpoint(data: dict):
    try:
        with open(CHECKPOINT, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception:
        logging.exception("Failed to write checkpoint")


def ensure_csv_header(path: str, fieldnames):
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()


def parse_price(price_str: str) -> float:
    # prices look like '£51.77' — strip currency symbol and convert
    try:
        cleaned = re.sub(r"[^0-9.]", "", price_str)
        return float(cleaned) if cleaned else 0.0
    except Exception:
        logging.exception("Failed to parse price: %s", price_str)
        return 0.0


def parse_rating(classes) -> int:
    # rating is encoded as class on a tag, e.g. 'star-rating Three'
    try:
        for cls in classes:
            if not cls:
                continue
            key = cls.strip()
            # normalize e.g. 'Three' or 'three'
            if key in RATING_MAP:
                return RATING_MAP[key]
            k2 = key.capitalize()
            if k2 in RATING_MAP:
                return RATING_MAP[k2]
    except Exception:
        logging.exception("Error parsing rating classes: %s", classes)
    return 0


def extract_number_of_reviews(soup: BeautifulSoup) -> int:
    # Try to find in product information table
    try:
        table = soup.find("table", class_="table table-striped")
        if table:
            for row in table.find_all("tr"):
                th = row.find("th")
                td = row.find("td")
                if not th or not td:
                    continue
                key = th.get_text(strip=True).lower()
                if "review" in key:
                    text = td.get_text(strip=True)
                    try:
                        return int(text)
                    except ValueError:
                        # sometimes it's not an int; return -1 then
                        return -1
    except Exception:
        logging.exception("Error extracting number of reviews")
    return -1


def scrape():
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    fieldnames = [
        "title",
        "price",
        "rating",
        "number_of_reviews",
        "product_page_url",
        "scraped_at",
    ]
    ensure_csv_header(OUT_CSV, fieldnames)

    checkpoint = load_checkpoint()
    next_url = checkpoint.get("next_url") or BASE_URL

    page_count = 0
    while next_url:
        page_count += 1
        logging.info("Processing page: %s", next_url)
        resp = retry_get(session, next_url)
        if resp is None:
            logging.error("Skipping page due to repeated failures: %s", next_url)
            break

        soup = BeautifulSoup(resp.text, "html.parser")

        product_articles = soup.select("article.product_pod")
        if not product_articles:
            logging.info("No products found on page: %s", next_url)

        rows_to_write = []
        for art in product_articles:
            try:
                h3 = art.find("h3")
                a = h3.find("a")
                title = a.get("title") or a.get_text(strip=True)
                rel_link = a.get("href")
                product_url = urljoin(next_url, rel_link)

                price_tag = art.find("p", class_="price_color")
                price = parse_price(price_tag.get_text()) if price_tag else 0.0

                rating_tag = art.find("p", class_="star-rating")
                rating = parse_rating(rating_tag.get("class", [])) if rating_tag else 0

                # Try to get number_of_reviews from product page
                num_reviews = -1
                prod_resp = retry_get(session, product_url)
                if prod_resp:
                    try:
                        prod_soup = BeautifulSoup(prod_resp.text, "html.parser")
                        num_reviews = extract_number_of_reviews(prod_soup)
                    except Exception:
                        logging.exception("Failed to parse product page: %s", product_url)
                        num_reviews = -1
                else:
                    logging.warning("Could not retrieve product page: %s", product_url)

                # be polite between product requests
                time.sleep(POLITE_DELAY)

                scraped_at = datetime.utcnow().isoformat() + "Z"

                row = {
                    "title": title,
                    "price": price,
                    "rating": rating,
                    "number_of_reviews": num_reviews,
                    "product_page_url": product_url,
                    "scraped_at": scraped_at,
                }
                rows_to_write.append(row)
                logging.info("Queued product: %s", title)
            except Exception:
                logging.exception("Failed to parse a product on %s", next_url)
                continue

        # Append page results to CSV as we go
        try:
            with open(OUT_CSV, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                for r in rows_to_write:
                    writer.writerow(r)
        except Exception:
            logging.exception("Failed to write page results to %s", OUT_CSV)
        else:
            # user-visible feedback on progress
            saved = len(rows_to_write)
            print(f"Saved {saved} rows from page {page_count}")

        # Save checkpoint (next page)
        next_link = soup.select_one("li.next > a")
        if next_link:
            href = next_link.get("href")
            # next pages on this site are relative to the catalog path
            next_url = urljoin(next_url, href)
            save_checkpoint({"next_url": next_url})
            logging.info("Saved checkpoint for next page: %s", next_url)
        else:
            # finished
            save_checkpoint({"next_url": None})
            logging.info("No next page; finished crawling pages")
            next_url = None

    logging.info("Crawling finished. Deduplicating output CSV by title...")
    deduplicate_csv(OUT_CSV, key_field="title", fieldnames=fieldnames)
    logging.info("Done. Cleaned CSV saved to %s", OUT_CSV)


def deduplicate_csv(path: str, key_field: str, fieldnames):
    """Read CSV and deduplicate by `key_field`, keeping first occurrence."""
    try:
        seen = {}
        with open(path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = row.get(key_field)
                if key and key not in seen:
                    seen[key] = row

        # Overwrite CSV with deduped rows
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in seen.values():
                writer.writerow(row)
    except Exception:
        logging.exception("Failed to deduplicate CSV %s", path)


if __name__ == "__main__":
    try:
        scrape()
    except KeyboardInterrupt:
        logging.warning("Interrupted by user")
    except Exception:
        logging.exception("Unhandled exception in scraper")
import requests
from bs4 import BeautifulSoup
import csv
from urllib.parse import urljoin

def scrape_books(base_url="http://books.toscrape.com", output_file="books.csv"):
    """
    Scrape book titles and prices from books.toscrape.com
    
    Args:
        base_url: The base URL of the website to scrape
        output_file: The name of the CSV file to save the data to
    """
    books = []
    page_num = 1
    
    while True:
        # Construct the URL for the current page
        if page_num == 1:
            url = base_url
        else:
            url = f"{base_url}/page-{page_num}/"
        
        try:
            print(f"Scraping page {page_num}: {url}")
            
            # Fetch the page
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # Parse the HTML
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find all book containers
            book_containers = soup.find_all('article', class_='product_pod')
            
            if not book_containers:
                print(f"No books found on page {page_num}. Stopping.")
                break
            
            # Extract title and price from each book
            for container in book_containers:
                # Extract title
                title_element = container.find('h3').find('a')
                title = title_element['title']
                
                # Extract price
                price_element = container.find('p', class_='price_color')
                price = price_element.text.strip()
                
                books.append({
                    'title': title,
                    'price': price
                })
                print(f"  - {title}: {price}")
            
            page_num += 1
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching page {page_num}: {e}")
            break
    
    # Save to CSV file
    if books:
        try:
            with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['title', 'price']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                writer.writeheader()
                writer.writerows(books)
            
            print(f"\n✓ Successfully scraped {len(books)} books")
            print(f"✓ Data saved to {output_file}")
            
        except IOError as e:
            print(f"Error saving to CSV file: {e}")
    else:
        print("No books were scraped.")

if __name__ == "__main__":
    scrape_books()
