"""
Firecrawl source — scrapes trader blogs / news pages to feed the Strategy Scout
normalization pipeline with richer content than raw RSS.

Endpoint: POST https://api.firecrawl.dev/v1/scrape  (Firecrawl v1)
Body    : {"url": "...", "formats": ["markdown"]}
Auth    : Authorization: Bearer $FIRECRAWL_API_KEY (read from .env)

Each URL is isolated — one failure never kills the cycle. Markdown is truncated
per URL so the combined blob fits Scout's _normalize token budget.
"""

import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("FirecrawlSource")

_API = "https://api.firecrawl.dev/v1/scrape"


def fetch(urls: list[str], per_url_chars: int = 2500, timeout: int = 60) -> list[str]:
    """Scrape each URL via Firecrawl, return a list of markdown snippets.

    - per_url_chars caps each snippet so the joint blob stays inside Scout's
      ~12000-char _normalize budget (3 URLs × 2500 = 7500 chars).
    - On per-URL failure: log + skip that URL (the cycle still proceeds).
    - If no API key is set: return [] silently (graceful disable).
    """
    key = os.getenv("FIRECRAWL_API_KEY", "").strip()
    if not key:
        log.info("FIRECRAWL_API_KEY not set — firecrawl source disabled")
        return []

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    out: list[str] = []
    for url in urls:
        try:
            resp = requests.post(
                _API, headers=headers,
                json={"url": url, "formats": ["markdown"]},
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                log.warning("Firecrawl returned success=false for %s", url)
                continue
            md = (data.get("data") or {}).get("markdown") or ""
            if not md.strip():
                continue
            title = ((data.get("data") or {}).get("metadata") or {}).get("title", "")
            snippet = f"[firecrawl:{url}] {title}\n{md[:per_url_chars]}"
            out.append(snippet)
        except Exception as e:
            log.warning("Firecrawl scrape failed (%s): %s — skipping", url, e)
    return out
