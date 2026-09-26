"""
TV-prisbevakare för TCL 55-65" på Prisjakt och PriceRunner.

Körs automatiskt av GitHub Actions (.github/workflows/check-prices.yml).
Skriver prishistorik till price_history.db och exporterar senaste läget
till data.json, som dashboarden (index.html) läser.

HUR SKRAPNINGEN FUNGERAR:
Istället för att leta efter specifika CSS-klasser (som ändras ofta och
skiljer sig mellan sajter) letar skriptet igenom ALLA länkar på sidan
och plockar ut de vars text innehåller "TCL", en giltig skärmstorlek
och ett pris inom ditt spann. Det är mindre känsligt för att sajterna
ändrar sin design, men kan missa produkter om sajten laddar in resultat
via t.ex. oändlig scroll utan att de finns i den inledande HTML:en.

Om resultatet ändå blir tomt när sajterna har relevanta produkter:
öppna sökresultatsidan i en vanlig webbläsare och kontrollera att
länkarna till produkterna verkligen innehåller modellnamn + pris i sin
synliga text (inte t.ex. bara en bild).
"""

import asyncio
import json
import re
import sqlite3
from datetime import datetime, timezone

from playwright.async_api import async_playwright

import config

# ---- Sidspecifik konfiguration ----

SEARCH_URLS = {
    "prisjakt": "https://www.prisjakt.nu/search?search={brand}+tv",
    "pricerunner": "https://www.pricerunner.se/sp/{brand_lower}-55.html",
}

SIZE_RE = re.compile(r"(\d{2})\s*(?:\"|tum|inch|\u2033)", re.IGNORECASE)
PRICE_RE = re.compile(r"(\d[\d\s]{2,7})\s*kr", re.IGNORECASE)


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
    """Hittar det FÖRSTA priset i texten som ser ut som '9 725 kr'."""
    m = PRICE_RE.search(text)
    if not m:
        return None
    digits = re.sub(r"\s", "", m.group(1))
    return int(digits) if digits.isdigit() else None


def matches_filters(text: str, size, price) -> bool:
    if config.BRAND.lower() not in text.lower():
        return False
    if size is not None and not (config.SIZE_MIN <= size <= config.SIZE_MAX):
        return False
    if price is None or not (config.PRICE_MIN <= price <= config.PRICE_MAX):
        return False
    return True


# ---- Skrapning (selektor-fri: letar igenom alla länkar på sidan) ----

async def scrape_source(page, source: str):
    url = SEARCH_URLS[source].format(brand=config.BRAND, brand_lower=config.BRAND.lower())

    await page.goto(url, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(2000)  # låt ev. JS-rendering/bot-check bli klar

    anchors = await page.query_selector_all("a")
    results = []
    for a in anchors:
        try:
            text = (await a.inner_text()).strip()
        except Exception:
            continue
        if not text or config.BRAND.lower() not in text.lower():
            continue

        size = parse_size(text)
        price = parse_price(text)
        if not matches_filters(text, size, price):
            continue

        href = await a.get_attribute("href")
        if href and href.startswith("/"):
            base = "https://www.prisjakt.nu" if source == "prisjakt" else "https://www.pricerunner.se"
            href = base + href

        model_name = text.split("\n")[0].strip()[:100]

        results.append({
            "model": model_name,
            "size": size,
            "price": price,
            "url": href if (href and href.startswith("http")) else url,
        })

    # Ta bort dubbletter (samma modell + pris dyker ofta upp i flera länkar per kort)
    seen = set()
    deduped = []
    for r in results:
        key = (r["model"], r["price"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


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

            print(f"[scraper] {source}: hittade {len(results)} träffar")
            for item in results:
                save_price(conn, source, item["model"], item["size"], item["price"], item["url"])
                print(f"[scraper] Kollad: {item['model']} - {item['price']} kr")

        await browser.close()

    export_json(conn)
    conn.close()


if __name__ == "__main__":
    asyncio.run(run())
