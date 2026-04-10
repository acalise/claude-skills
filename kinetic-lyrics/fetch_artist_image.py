#!/usr/bin/env python3
"""
Fetch an artist's main Wikipedia image and save it locally.
Uses the Wikipedia API (no auth needed).

Usage:
    python3 fetch_artist_image.py "Michael Jackson" output/artist.jpg
"""

import json
import sys
import ssl
import urllib.request
import urllib.parse
import os

try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl.create_default_context()


def fetch_artist_image(artist, save_path):
    """
    Fetch the main image from an artist's Wikipedia page.
    Returns the save path on success, None on failure.
    """
    search_url = (
        "https://en.wikipedia.org/w/api.php?"
        + urllib.parse.urlencode({
            "action": "query",
            "list": "search",
            "srsearch": f"{artist} musician",
            "srlimit": "3",
            "format": "json",
        })
    )

    req = urllib.request.Request(search_url, headers={
        "User-Agent": "KineticLyrics/1.0"
    })
    with urllib.request.urlopen(req, timeout=15, context=SSL_CONTEXT) as resp:
        data = json.loads(resp.read())

    results = data.get("query", {}).get("search", [])
    if not results:
        print(f"  No Wikipedia page found for: {artist}")
        return None

    page_title = results[0]["title"]
    for r in results:
        if artist.lower() in r["title"].lower():
            page_title = r["title"]
            break

    print(f"  Wikipedia page: {page_title}")

    image_url_api = (
        "https://en.wikipedia.org/w/api.php?"
        + urllib.parse.urlencode({
            "action": "query",
            "titles": page_title,
            "prop": "pageimages",
            "pithumbsize": "1200",
            "format": "json",
        })
    )

    req = urllib.request.Request(image_url_api, headers={
        "User-Agent": "KineticLyrics/1.0"
    })
    with urllib.request.urlopen(req, timeout=15, context=SSL_CONTEXT) as resp:
        data = json.loads(resp.read())

    pages = data.get("query", {}).get("pages", {})
    image_url = None
    for page in pages.values():
        thumb = page.get("thumbnail", {})
        image_url = thumb.get("source")
        break

    if not image_url:
        print(f"  No image found on Wikipedia for: {page_title}")
        return None

    print(f"  Image URL: {image_url}")

    req = urllib.request.Request(image_url, headers={
        "User-Agent": "KineticLyrics/1.0"
    })
    with urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT) as resp:
        img_data = resp.read()

    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    with open(save_path, "wb") as f:
        f.write(img_data)

    size_kb = len(img_data) / 1024
    print(f"  Saved: {save_path} ({size_kb:.0f} KB)")
    return save_path


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 fetch_artist_image.py <artist> <output_path>")
        sys.exit(1)
    result = fetch_artist_image(sys.argv[1], sys.argv[2])
    sys.exit(0 if result else 1)
