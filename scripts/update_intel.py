import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request

# ── CONFIGURACIÓN ──────────────────────────────────────────
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "intel.json"
YAHOO_SYMBOLS = {"brent": "BZ=F", "wti": "CL=F", "vix": "^VIX"}
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

# ── FILTROS TÁCTICOS ───────────────────────────────────────
TOP_PRIORITY = ["hormuz", "ormuz", "strait", "estrecho", "brent", "wti", "vix"]
EXCLUSIONS = ["metanfetamina", "narcotráfico", "droga", "detenido", "fútbol", "laos"]
KEYWORDS = ["oil", "tanker", "iran", "strike", "mine", "missile", "drone", "blockade", "sunk", "attack", "petróleo", "ormuz", "buque", "irán", "ataque", "mina", "misil", "bloqueo", "hundido"]
CRITICAL_KEYWORDS = ["attack", "war", "closure", "blockade", "missile", "mine", "sunk", "ataque", "guerra", "cierre", "bloqueo", "misil", "mina", "hundido"]
ALERT_KEYWORDS = ["disruption", "tension", "threat", "incident", "tensión", "amenaza", "incidente"]

HEADERS = {"User-Agent": "Mozilla/5.0"}

# ── FUNCIONES ──────────────────────────────────────────────
def fetch_url(url: str):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=15) as r: return r.read()

def fetch_yahoo(symbol: str):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
    try:
        data = json.loads(fetch_url(url))
        meta = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice", 0)
        prev = meta.get("previousClose", price)
        return {"price": round(price, 2), "change": round(((price-prev)/prev*100), 2)}
    except: return {"price": 0, "change": 0}

def parse_rss(url: str):
    try:
        root = ET.fromstring(fetch_url(url).decode("utf-8", errors="replace"))
        return [{"title": i.findtext("title"), "desc": i.findtext("description"), "date": i.findtext("pubDate")} for i in root.iter("item")]
    except: return []

def is_relevant(item: dict):
    txt = f"{item['title']} {item['desc']}".lower()
    if any(ex in txt for ex in EXCLUSIONS): return False
    # El s? permite detectar 'mina' y 'minas'
    return any(re.search(rf"\b{re.escape(k)}s?\b", txt) for k in KEYWORDS + TOP_PRIORITY)

def infer_ormuz_status(events: list, brent_chg: float, vix: float) -> dict:
    txt = " ".join((e["headline"] + " " + e["detail"]).lower() for e in events)
    weights = {"closed":60, "cerrado":60, "blockade":60, "bloqueo":60, "mine":55, "mina":55, "sunk":50, "hundido":50, "attack":25, "ataque":25}
    pressure = sum(weights[k] * min(len(re.findall(rf"\b{k}s?\b", txt)), 3) for k in weights if re.search(rf"\b{k}s?\b", txt))
    pressure += (brent_chg * 4 if brent_chg > 0 else 0) + (max(0, vix-20) * 2.5)
    
    flow = max(100 - pressure, 3)
    is_closed = any(re.search(rf"\b{k}s?\b", txt) for k in ["closed", "cerrado", "blockade", "bloqueo", "mina", "mine"])
    if is_closed: flow = min(flow, 10)

    return {"flow": round(flow, 1), "summary": f"CIERRE FACTICIO: Flujo al {flow}%" if flow < 15 else "OPERATIVO"}

def build_intel():
    brent = fetch_yahoo(YAHOO_SYMBOLS["brent"])
    vix = fetch_yahoo(YAHOO_SYMBOLS["vix"])
    
    items = []
    for url in RSS_FEEDS: items.extend(parse_rss(url))
    
    relevant = [i for i in items if is_relevant(i)]
    relevant.sort(key=lambda x: x['date'] or '', reverse=True)
    
    events = []
    for i in relevant[:6]:
        txt = f"{i['title']} {i['desc']}".lower()
        sev = "CRÍTICO" if any(re.search(rf"\b{k}s?\b", txt) for k in CRITICAL_KEYWORDS) else "INFO"
        events.append({"headline": i['title'].upper()[:80], "detail": i['desc'][:200], "severity": sev, "timestamp": "RECUPERADO"})

    ormuz = infer_ormuz_status(events, brent["change"], vix["price"])
    
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "market": {"brent_usd": brent["price"], "brent_chg": brent["change"]},
        "indicators": {
            "ormuz_flow_pct": ormuz["flow"],
            "vix": vix["price"], # ESTO ARREGLA EL NaN
            "insurance_spread_pct": round(0.8 + max(0, (vix["price"]-15)*0.2), 1)
        },
        "ormuz_status": {"summary": ormuz["summary"]},
        "events": events,
        "ticker_items": [f"BRENT: ${brent['price']}", f"VIX: {vix['price']}", f"ORMUZ: {ormuz['summary']}"]
    }

if __name__ == "__main__":
    data = build_intel()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
