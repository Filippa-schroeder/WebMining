#!/usr/bin/env python3
"""
Simple scraper that downloads https://books.toscrape.com, extracts
book titles, prices and star ratings from the homepage and saves the
results to `books.csv` using pandas.

Requires: requests, beautifulsoup4, pandas
Usage: python books_scraper.py
"""

import re
import sys

import requests
import pandas as pd
from bs4 import BeautifulSoup

BASE_URL = "https://books.toscrape.com"
TIMEOUT = 10
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BooksScraper/1.0)"}

# Map textual star rating to numeric value
RATING_MAP = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}


def parse_price(price_text: str) -> float:
    """Convert price string like 'Â£51.77' or '£51.77' to float 51.77."""
    # Remove any non-digit / non-dot characters and convert to float
    cleaned = re.sub(r"[^0-9.]", "", price_text)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_rating(classes) -> int:
    """Find the textual rating in a list of classes and map to integer."""
    for cls in classes:
        if cls and cls != "star-rating":
            # Normalize capitalization just in case
            text = cls.capitalize()
            if text in RATING_MAP:
                return RATING_MAP[text]
    return 0


def scrape_homepage(url: str = BASE_URL):
    """Download the homepage and extract title, price and rating for each book."""
    try:
        # Download the page
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching {url}: {e}")
        sys.exit(1)

    # Parse the HTML content with BeautifulSoup
    soup = BeautifulSoup(resp.content, "html.parser")

    # Find all books on the page (each book is an <article class="product_pod">)
    articles = soup.find_all("article", class_="product_pod")

    rows = []

    for art in articles:
        # Extract the title from the <a> tag's title attribute
        a = art.find("h3").find("a")
        title = a.get("title") or a.get_text(strip=True)

        # Extract the price from the <p class="price_color"> tag
        price_tag = art.find("p", class_="price_color")
        price_text = price_tag.get_text(strip=True) if price_tag else ""
        price = parse_price(price_text)

        # Extract the rating from the <p class="star-rating ..."> classes
        rating_tag = art.find("p", class_="star-rating")
        rating = parse_rating(rating_tag.get("class", [])) if rating_tag else 0

        rows.append({"title": title, "price": price, "rating": rating})

    # Build a pandas DataFrame and save to CSV
    df = pd.DataFrame(rows, columns=["title", "price", "rating"])
    output_file = "books.csv"
    df.to_csv(output_file, index=False, encoding="utf-8")

    print(f"Saved {len(df)} books to {output_file}")


if __name__ == "__main__":
    scrape_homepage()
