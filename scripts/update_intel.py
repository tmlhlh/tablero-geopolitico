"""
update_intel.py
Recopila datos de fuentes públicas gratuitas (Yahoo Finance + RSS) y escribe data/intel.json
Corre vía GitHub Actions cada hora. Sin API keys, 100% gratuito.

Fuentes:
  - Precios:  Yahoo Finance (JSON público)
  - VIX:      Yahoo Finance (^VIX)
  - Noticias: Reuters RSS, BBC RSS, EIA RSS
"""

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

# ── Config ───────────────────────────────────────────────
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "intel.json"

# Símbolos Yahoo Finance
YAHOO_SYMBOLS = {
    "brent": "BZ=F",    # Brent Crude Futures
    "wti":   "CL=F",    # WTI Crude Futures
    "vix":   "^VIX",    # CBOE Volatility Index
}

# Feeds RSS (sin API key)
RSS_FEEDS = [
    # Reuters - energía y commodities
    "https://feeds.reuters.com/reuters/businessNews",
    # BBC - noticias mundo
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    # EIA - energía US
    "https://www.eia.gov/rss/todayinenergy.xml",
]

# Keywords para filtrar noticias relevantes al Golfo/energía
KEYWORDS = [
    "oil", "petroleum", "crude", "energy", "opec", "gulf", "iran", "ormuz", "hormuz",
    "saudi", "aramco", "gas", "lng", "tanker", "shipping", "strait", "middle east",
    "petróleo", "golfo", "barril", "energía",
]

# Palabras que indican alta severidad
CRITICAL_KEYWORDS = ["attack", "strike", "war", "sanctions", "closure", "blockade",
                      "explosion", "missile", "ataque", "guerra", "cierre", "bloqueo"]
ALERT_KEYWORDS = ["disruption", "tension", "threat", "rise", "spike", "concern",
                  "perturbación", "tensión", "amenaza", "alza"]

HEADERS = {"User-Agent": "Mozilla/5.0 (tablero-intel-bot/1.0)"}


# ── Helpers ──────────────────────────────────────────────

def fetch_url(url: str, timeout: int = 10) -> bytes:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_yahoo_quote(symbol: str) -> dict:
    """Obtiene precio actual y cambio % de Yahoo Finance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
    try:
        data = json.loads(fetch_url(url))
        result = data["chart"]["result"][0]
        meta   = result["meta"]
        price  = meta.get("regularMarketPrice", 0)
        prev   = meta.get("chartPreviousClose") or meta.get("previousClose", price)
        change = ((price - prev) / prev * 100) if prev else 0
        return {"price": round(price, 2), "change_pct": round(change, 2)}
    except Exception as e:
        print(f"  ⚠ Yahoo {symbol}: {e}")
        return {"price": 0, "change_pct": 0}


def parse_rss(url: str) -> list[dict]:
    """Parsea un feed RSS y devuelve lista de items {title, description, pubDate, link}."""
    try:
        xml_data = fetch_url(url, timeout=15).decode("utf-8", errors="replace")
        root = ET.fromstring(xml_data)
        items = []
        # Soporta RSS 2.0 y Atom
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            desc  = item.findtext("description", "").strip()
            # Limpiar HTML de descripción
            desc  = re.sub(r"<[^>]+>", " ", desc).strip()
            desc  = re.sub(r"\s+", " ", desc)[:200]
            pub   = item.findtext("pubDate", "")
            link  = item.findtext("link", "")
            items.append({"title": title, "description": desc, "pubDate": pub, "link": link})
        return items
    except Exception as e:
        print(f"  ⚠ RSS {url}: {e}")
        return []


def is_relevant(item: dict) -> bool:
    text = (item["title"] + " " + item["description"]).lower()
    return any(kw in text for kw in KEYWORDS)


def classify_severity(item: dict) -> str:
    text = (item["title"] + " " + item["description"]).lower()
    if any(kw in text for kw in CRITICAL_KEYWORDS):
        return "CRÍTICO"
    if any(kw in text for kw in ALERT_KEYWORDS):
        return "ALERTA"
    return "INFO"


def parse_date(pub_date: str) -> datetime:
    """Intenta parsear fecha RSS, fallback a now."""
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(pub_date.strip(), fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return datetime.now(timezone.utc)


def format_event_date(dt: datetime) -> str:
    return dt.strftime("%d %b %Y · %H:%M UTC").upper()


def infer_risk_level(brent_change: float, events: list) -> str:
    """Infiere nivel de riesgo según movimiento de precio y severidad de noticias."""
    critical_count = sum(1 for e in events if e["severity"] == "CRÍTICO")
    alert_count    = sum(1 for e in events if e["severity"] == "ALERTA")

    if critical_count >= 2 or abs(brent_change) > 8:
        return "CRÍTICO"
    if critical_count >= 1 or alert_count >= 3 or abs(brent_change) > 4:
        return "ALTO"
    if alert_count >= 1 or abs(brent_change) > 2:
        return "MEDIO"
    return "BAJO"


def infer_ormuz_status(events: list, brent_change: float) -> dict:
    """Infiere estado de Ormuz a partir de noticias y movimiento de precio."""
    text_all = " ".join(
        (e["headline"] + " " + e["detail"]).lower() for e in events
    )
    closure_keywords   = ["closed", "closure", "blocked", "blockade", "cerrado", "bloqueo"]
    disruption_keywords= ["disrupted", "perturbado", "tension", "attack", "ataque", "perturbation"]

    closed    = any(kw in text_all for kw in closure_keywords)
    disrupted = closed or any(kw in text_all for kw in disruption_keywords) or brent_change > 5

    if closed:
        summary = "Estrecho de Ormuz cerrado — tráfico marítimo interrumpido."
    elif disrupted:
        summary = "Tráfico en Ormuz perturbado — tensiones elevan costos logísticos."
    else:
        summary = "Estrecho de Ormuz operativo. Flujo normal de tráfico marítimo."

    # Flujo estimado
    flow_pct = 40 if closed else (80 if disrupted else 100)

    return {"open": not closed, "disrupted": disrupted, "summary": summary,
            "flow_pct": flow_pct}


# ── Main ─────────────────────────────────────────────────

def build_intel() -> dict:
    now = datetime.now(timezone.utc)
    print("  Fetching precios (Yahoo Finance)...")

    brent = fetch_yahoo_quote(YAHOO_SYMBOLS["brent"])
    wti   = fetch_yahoo_quote(YAHOO_SYMBOLS["wti"])
    vix   = fetch_yahoo_quote(YAHOO_SYMBOLS["vix"])

    print(f"  Brent: ${brent['price']} ({brent['change_pct']:+.2f}%) | "
          f"WTI: ${wti['price']} ({wti['change_pct']:+.2f}%) | VIX: {vix['price']}")

    print("  Fetching RSS feeds...")
    all_items = []
    for url in RSS_FEEDS:
        items = parse_rss(url)
        print(f"    {url.split('/')[2]}: {len(items)} items")
        all_items.extend(items)

    # Filtrar relevantes y ordenar por fecha
    relevant = [i for i in all_items if is_relevant(i)]
    relevant.sort(key=lambda i: parse_date(i["pubDate"]), reverse=True)
    # Desduplicar por título similar
    seen, deduped = set(), []
    for item in relevant:
        key = item["title"][:50].lower()
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    print(f"  {len(relevant)} noticias relevantes → {len(deduped)} tras deduplicar")

    # Construir lista de eventos (máx 6)
    events = []
    for item in deduped[:6]:
        dt  = parse_date(item["pubDate"])
        sev = classify_severity(item)
        events.append({
            "timestamp": format_event_date(dt),
            "headline":  item["title"].upper()[:80],
            "detail":    item["description"][:200],
            "severity":  sev,
        })

    ormuz  = infer_ormuz_status(events, brent["change_pct"])
    risk   = infer_risk_level(brent["change_pct"], events)

    # Spread de seguros: proxy basado en cambio de precio
    # En escenarios reales el spread sube con la volatilidad
    base_spread = 0.8
    spread = round(base_spread + abs(brent["change_pct"]) * 0.3, 1)
    if not ormuz["open"]:   spread += 4.0
    elif ormuz["disrupted"]: spread += 1.5

    # Ticker items: precio + top headlines
    ticker = [
        f"BRENT: ${brent['price']} ({brent['change_pct']:+.2f}%)",
        f"WTI: ${wti['price']} ({wti['change_pct']:+.2f}%)",
        f"VIX: {vix['price']} · RIESGO GEOPOLÍTICO: {risk}",
        f"ORMUZ: {ormuz['summary'].upper()[:70]}",
    ] + [e["headline"][:80] for e in events[:4]]

    return {
        "updated_at": now.isoformat(),
        "market": {
            "brent_usd":        brent["price"],
            "wti_usd":          wti["price"],
            "brent_change_pct": brent["change_pct"],
            "wti_change_pct":   wti["change_pct"],
        },
        "indicators": {
            "ormuz_flow_pct":      ormuz["flow_pct"],
            "risk_level":          risk,
            "insurance_spread_pct": spread,
            "vix":                 vix["price"],
        },
        "ormuz_status": {
            "open":      ormuz["open"],
            "disrupted": ormuz["disrupted"],
            "summary":   ormuz["summary"],
        },
        "events":      events,
        "ticker_items": ticker,
        "dependency_bars": {
            # Estáticos — refleja estructura estructural de largo plazo
            # (no cambia hora a hora, solo se actualiza manualmente)
            "china_pct": 34,
            "india_pct": 22,
            "japan_pct": 14,
            "korea_pct": 10,
            "other_pct": 20,
        },
    }


def write_output(data: dict) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✓ intel.json escrito → {OUTPUT_PATH}")


if __name__ == "__main__":
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}] Iniciando update (RSS mode)...")
    try:
        data = build_intel()
        write_output(data)
        print(f"✓ Completado. Eventos: {len(data['events'])} | Ticker: {len(data['ticker_items'])} items")
    except Exception as e:
        print(f"✗ Error: {e}")
        raise
