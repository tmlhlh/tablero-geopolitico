"""
update_intel.py — VERSIÓN FINAL CORREGIDA
- Fix: VIX en indicators (evita NaN).
- Fix: Detección inteligente de plurales (evita Ormuz abierto por error).
- Seguridad: Filtro anti-metanfetamina mediante Word Boundaries.
"""

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

# ── 1. CONFIGURACIÓN ──────────────────────────────────────
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "intel.json"

YAHOO_SYMBOLS = {
    "brent": "BZ=F",
    "wti":   "CL=F",
    "vix":   "^VIX",
}

RSS_FEEDS = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://www.eia.gov/rss/todayinenergy.xml",
    "https://cnnespanol.cnn.com/category/mundo/feed/",
    "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/internacional/portada",
    "https://www.lanacion.com.ar/arc/outboundfeeds/rss/?outputType=xml",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://www.xinhuanet.com/english/rss/worldrss.xml",
    "https://www.rt.com/rss/news/",
    "https://rss.dw.com/rdf/rss-sp-top"
]

# ── 2. FILTROS TÁCTICOS ───────────────────────────────────

TOP_PRIORITY = ["hormuz", "ormuz", "strait", "estrecho", "brent", "wti", "vix", "suez", "bab el-mandeb"]

EXCLUSIONS = [
    "metanfetamina", "narcotráfico", "droga", "narcóticos", "detenido", "arrestado", 
    "fútbol", "farándula", "celebrity", "robó", "laos", "meth", "narcotraficante"
]

KEYWORDS = [
    "oil", "crude", "energy", "tanker", "iran", "strike", "mine", "missile", "drone", 
    "blockade", "closure", "red sea", "navy", "sunk", "attack", "petróleo", "crudo", 
    "energía", "buque", "irán", "ataque", "mina", "misil", "bloqueo", "mar rojo", "naval"
]

CRITICAL_KEYWORDS = [
    "attack", "strike", "war", "closure", "blockade", "explosion", "missile", 
    "mine", "minelaying", "sunk", "sink", "destroyed", "ataque", "guerra", "cierre", 
    "bloqueo", "explosión", "misil", "mina", "minado", "hundido"
]

ALERT_KEYWORDS = [
    "disruption", "tension", "threat", "seized", "warning", "incident",
    "perturbación", "tensión", "amenaza", "incautado", "incidente"
]

HEADERS = {"User-Agent": "Mozilla/5.0 (tablero-intel-bot/1.0)"}

# ── 3. HELPERS ───────────────────────────────────────────

def fetch_url(url: str, timeout: int = 15) -> bytes:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=timeout) as r:
        return r.read()

def fetch_yahoo_quote(symbol: str) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
    try:
        data = json.loads(fetch_url(url))
        result = data["chart"]["result"][0]
        meta = result["meta"]
        price = meta.get("regularMarketPrice", 0)
        prev = meta.get("chartPreviousClose") or meta.get("previousClose", price)
        change = ((price - prev) / prev * 100) if prev else 0
        return {"price": round(price, 2), "change_pct": round(change, 2)}
    except Exception as e:
        print(f"  ⚠ Yahoo {symbol}: {e}")
        return {"price": 0, "change_pct": 0}

def parse_rss(url: str) -> list[dict]:
    try:
        xml_data = fetch_url(url).decode("utf-8", errors="replace")
        root = ET.fromstring(xml_data)
        items = []
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            desc = item.findtext("description", "").strip()
            desc = re.sub(r"<[^>]+>", " ", desc).strip()
            desc = re.sub(r"\s+", " ", desc)[:250]
            pub = item.findtext("pubDate", "")
            link = item.findtext("link", "")
            items.append({"title": title, "description": desc, "pubDate": pub, "link": link})
        return items
    except Exception as e:
        print(f"  ⚠ RSS {url}: {e}")
        return []

def parse_date(pub_date: str) -> datetime:
    formats = ["%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT", "%Y-%m-%dT%H:%M:%S%z"]
    for fmt in formats:
        try:
            return datetime.strptime(pub_date.strip(), fmt).replace(tzinfo=timezone.utc)
        except:
            continue
    return datetime.now(timezone.utc)

def format_event_date(dt: datetime) -> str:
    return dt.strftime("%d %b %Y · %H:%M UTC").upper()

def is_relevant(item: dict) -> bool:
    text = (item["title"] + " " + item["description"]).lower()
    if any(ex in text for ex in EXCLUSIONS): return False
    # Regex inteligente: busca la palabra o su plural (s?) con límites de palabra
    for tp in TOP_PRIORITY:
        if re.search(rf"\b{re.escape(tp)}s?\b", text): return True
    for kw in KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}s?\b", text): return True
    return False

def classify_severity(item: dict) -> str:
    text = (item["title"] + " " + item["description"]).lower()
    if any(re.search(rf"\b{re.escape(kw)}s?\b", text) for kw in CRITICAL_KEYWORDS): return "CRÍTICO"
    if any(re.search(rf"\b{re.escape(kw)}s?\b", text) for kw in ALERT_KEYWORDS): return "ALERTA"
    return "INFO"

# ── 4. INFERENCIA GEOPOLÍTICA ────────────────────────────

def infer_ormuz_status(events: list, brent_change: float, vix_price: float) -> dict:
    text_all = " ".join((e["headline"] + " " + e["detail"]).lower() for e in events)
    
    weights = {
        "closed": 60, "cerrado": 60, "blockade": 60, "bloqueo": 60,
        "mine": 55, "mina": 55, "minelaying": 70, "minado": 70,
        "sunk": 50, "hundido": 50, "attack": 25, "ataque": 25, "missile": 30, "misil": 30
    }

    pressure = 0
    for kw, weight in weights.items():
        # Buscamos singular o plural (\bs?) para capturar 'mina' y 'minas'
        count = len(re.findall(rf"\b{re.escape(kw)}s?\b", text_all))
        if count > 0:
            pressure += (weight * min(count, 3))

    if brent_change > 0: pressure += (brent_change * 4)
    if vix_price > 25: pressure += (vix_price - 20) * 2.5

    is_closed_news = any(re.search(rf"\b{kw}s?\b", text_all) for kw in ["closed", "cerrado", "blockade", "bloqueo", "mina", "mine"])
    flow_pct = max(100 - pressure, 3)
    if is_closed_news: flow_pct = min(flow_pct, 10)

    if flow_pct <= 10:
        summary = f"CIERRE FACTICIO: Tráfico paralizado por minado u hostilidades. Flujo: {flow_pct:.1f}%."
    elif flow_pct < 45:
        summary = f"DISRUPCIÓN SEVERA: Múltiples ataques detectados. Flujo: {flow_pct:.1f}%."
    elif flow_pct < 85:
        summary = f"TENSIÓN OPERATIVA: Fricción logística y riesgos de seguro. Flujo: {flow_pct:.1f}%."
    else:
        summary = "FLUJO NORMAL: Sin disrupciones sistémicas significativas."

    return {"open": flow_pct > 15, "disrupted": pressure > 20, "summary": summary, "flow_pct": round(flow_pct, 1)}

# ── 5. MOTOR PRINCIPAL ───────────────────────────────────

def build_intel() -> dict:
    now = datetime.now(timezone.utc)
    brent = fetch_yahoo_quote(YAHOO_SYMBOLS["brent"])
    wti = fetch_yahoo_quote(YAHOO_SYMBOLS["wti"])
    vix = fetch_yahoo_quote(YAHOO_SYMBOLS["vix"])

    all_items = []
    for url in RSS_FEEDS:
        items = parse_rss(url)
        all_items.extend(items)

    relevant = [i for i in all_items if is_relevant(i)]
    relevant.sort(key=lambda i: parse_date(i["pubDate"]), reverse=True)
    
    seen, deduped = set(), []
    for item in relevant:
        key = item["title"][:50].lower()
        if key not in seen:
            seen.add(key); deduped.append(item)

    events = []
    for item in deduped[:6]:
        dt = parse_date(item["pubDate"])
        sev = classify_severity(item)
        events.append({
            "timestamp": format_event_date(dt),
            "headline": item["title"].upper()[:80],
            "detail": item["description"][:200],
            "severity": sev,
        })

    ormuz = infer_ormuz_status(events, brent["change_pct"], vix["price"])
    vix_factor = max(0, (vix["price"] - 15) * 0.2)
    spread = round(0.8 + vix_factor + abs(brent["change_pct"]) * 0.3, 1)

    return {
        "updated_at": now.isoformat(),
        "market": {"brent_usd": brent["price"], "brent_change_pct": brent["change_pct"], "vix": vix["price"]},
        "indicators": {
            "ormuz_flow_pct": ormuz["flow_pct"], 
            "insurance_spread_pct": spread, 
            "vix": vix["price"], # FIX: Esto arregla el NaN en el tablero
            "risk_level": "ALTO" if ormuz["disrupted"] else "MEDIO"
        },
        "ormuz_status": ormuz,
        "events": events,
        "ticker_items": [f"BRENT: ${brent['price']} ({brent['change_pct']:+.2f}%)", f"VIX: {vix['price']}", f"ORMUZ: {ormuz['summary'].upper()[:70]}"] + [e["headline"][:80] for e in events[:4]],
        "dependency_bars": {"china_pct": 34, "india_pct": 22, "japan_pct": 14, "korea_pct": 10, "other_pct": 20},
    }

if __name__ == "__main__":
    try:
        data = build_intel()
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✓ Completado. Eventos: {len(data['events'])}")
    except Exception as e:
        print(f"✗ Error: {e}")
        raise
