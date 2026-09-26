"""
TV-prisbevakare för TCL 55-65" på Prisjakt och PriceRunner.

Körs automatiskt av GitHub Actions (.github/workflows/check-prices.yml).
Skriver prishistorik till price_history.db och exporterar senaste läget
till data.json, som dashboarden (index.html) läser. Ingen notis skickas
någonstans - all information visas på sidan.

VIKTIGT — selektorerna nedan är platshållare:
Prisjakt och PriceRunner ändrar sin sidstruktur då och då, och båda har
bot-skydd. CSS-selektorerna nedan är en utgångspunkt, inte garanterat
fungerande direkt. Innan din första riktiga körning:
  1. Öppna sökresultatsidan i en vanlig webbläsare.
  2. Högerklicka på ett produktkort -> Inspektera, och hitta de faktiska
     klassnamnen för titel, pris och länk.
  3. Uppdatera SELECTORS-dictionaryn nedan.
Tips: leta även efter <script type="application/ld+json"> i sidkällan —
om produktdata finns där är det ofta stabilare att parsa än den visuella DOM:en.
"""

import asyncio
import json
import re
import sqlite3
from datetime import datetime, timezone

from playwright.async_api import async_playwright

import config

# ---- Sidspecifik konfiguration (platshållare — verifiera mot live-DOM) ----

SEARCH_URLS = {
    "prisjakt": "https://www.prisjakt.nu/search?search={brand}+tv",
    "pricerunner": "https://www.pricerunner.se/se/search?q={brand}+tv",
}

SELECTORS = {
    "prisjakt": {
        "card": "div.product-card",        # platshållare
        "title": ".product-card__title",   # platshållare
        "price": ".product-card__price",   # platshållare
        "link": "a.product-card__link",    # platshållare
    },
    "pricerunner": {
        "card": "li[data-test='product-item']",   # platshållare
        "title": "[data-test='product-title']",   # platshållare
        "price": "[data-test='product-price']",   # platshållare
        "link": "a",                               # platshållare
    },
}

SIZE_RE = re.compile(r"(\d{2})\s*(?:\"|tum|inch)", re.IGNORECASE)
PRICE_RE = re.compile(r"[\d\s]{3,}")


# ---- Lagring ----

def init_db():
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            model TEXT NOT NULL,
            size INTEGER,
            price INTEGER NOT NULL,
            url TEXT,
            checked_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def get_all_time_low(conn, source, model):
    row = conn.execute(
        "SELECT MIN(price) FROM prices WHERE source=? AND model=?",
        (source, model),
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def get_previous_price(conn, source, model, before_checked_at):
    row = conn.execute(
        "SELECT price FROM prices WHERE source=? AND model=? AND checked_at<? ORDER BY checked_at DESC LIMIT 1",
        (source, model, before_checked_at),
    ).fetchone()
    return row[0] if row else None


def save_price(conn, source, model, size, price, url):
    conn.execute(
        "INSERT INTO prices (source, model, size, price, url, checked_at) VALUES (?,?,?,?,?,?)",
        (source, model, size, price, url, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def export_json(conn):
    """Skriver senaste kända pris per (källa, modell), med historik-jämförelse, till data.json."""
    rows = conn.execute("""
        SELECT p1.source, p1.model, p1.size, p1.price, p1.url, p1.checked_at
        FROM prices p1
        INNER JOIN (
            SELECT source, model, MAX(checked_at) AS latest
            FROM prices GROUP BY source, model
        ) p2 ON p1.source = p2.source AND p1.model = p2.model AND p1.checked_at = p2.latest
    """).fetchall()

    data = []
    for source, model, size, price, url, checked_at in rows:
        all_time_low = get_all_time_low(conn, source, model)
        previous_price = get_previous_price(conn, source, model, checked_at)
        drop_percent = (
            round((previous_price - price) / previous_price * 100, 1)
            if previous_price else None
        )
        data.append({
            "source": source,
            "model": model,
            "size": size,
            "price": price,
            "all_time_low": all_time_low,
            "previous_price": previous_price,
            "drop_percent": drop_percent,
            "url": url,
            "checked_at": checked_at,
        })

    with open(config.DATA_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---- Parsning ----

def parse_size(text: str):
    m = SIZE_RE.search(text)
    return int(m.group(1)) if m else None


def parse_price(text: str):
    m = PRICE_RE.search(text.replace("kr", "").replace(":-", ""))
    if not m:
        return None
    digits = re.sub(r"\s", "", m.group(0))
    return int(digits) if digits.isdigit() else None


def matches_filters(model_text: str, size, price) -> bool:
    if config.BRAND.lower() not in model_text.lower():
        return False
    if size is not None and not (config.SIZE_MIN <= size <= config.SIZE_MAX):
        return False
    if price is None or not (config.PRICE_MIN <= price <= config.PRICE_MAX):
        return False
    return True


# ---- Skrapning ----

async def scrape_source(page, source: str):
    url = SEARCH_URLS[source].format(brand=config.BRAND)
    sel = SELECTORS[source]

    await page.goto(url, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(2000)  # låt ev. JS-rendering/bot-check bli klar

    cards = await page.query_selector_all(sel["card"])
    results = []
    for card in cards:
        title_el = await card.query_selector(sel["title"])
        price_el = await card.query_selector(sel["price"])
        link_el = await card.query_selector(sel["link"])
        if not (title_el and price_el):
            continue

        title = (await title_el.inner_text()).strip()
        price_text = (await price_el.inner_text()).strip()
        href = await link_el.get_attribute("href") if link_el else None

        size = parse_size(title)
        price = parse_price(price_text)

        if matches_filters(title, size, price):
            results.append({
                "model": title,
                "size": size,
                "price": price,
                "url": href if (href and href.startswith("http")) else url,
            })
    return results


async def run():
    conn = init_db()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        )

        for source in config.SOURCES:
            try:
                results = await scrape_source(page, source)
            except Exception as e:
                print(f"[scraper] {source} misslyckades: {e}")
                continue

            for item in results:
                save_price(conn, source, item["model"], item["size"], item["price"], item["url"])
                print(f"[scraper] Kollad: {item['model']} - {item['price']} kr")

        await browser.close()

    export_json(conn)
    conn.close()


if __name__ == "__main__":
    asyncio.run(run())
