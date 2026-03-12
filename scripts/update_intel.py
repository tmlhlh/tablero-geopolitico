"""
update_intel.py — VERSIÓN FINAL BLINDADA
- Fix: Cierre de Facto por presión acumulada (aunque no diga 'cerrado').
- Fix: Indicador de Riesgo Geo (evita NAN).
- Sensibilidad: Captura plurales y saturación de noticias bilingües.
"""

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request

# ── 1. CONFIGURACIÓN ──────────────────────────────────────
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

# Keywords de monitoreo (Singulares para el Regex inteligente)
KEYWORDS = ["oil", "tanker", "iran", "strike", "mine", "missile", "drone", "blockade", "sunk", "attack", "petróleo", "buque", "irán", "ataque", "mina", "misil", "bloqueo", "hundido", "hormuz", "ormuz"]
EXCLUSIONS = ["metanfetamina", "narcotráfico", "droga", "laos", "fútbol"]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ── 2. HELPERS ───────────────────────────────────────────

def fetch_url(url: str):
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=15) as r: return r.read()
    except: return None

def fetch_yahoo(symbol: str):
    raw = fetch_url(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d")
    if not raw: return {"price": 0, "change": 0}
    try:
        data = json.loads(raw)
        meta = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice", 0)
        prev = meta.get("previousClose", price)
        return {"price": round(price, 2), "change": round(((price-prev)/prev*100), 2)}
    except: return {"price": 0, "change": 0}

def parse_rss(url: str):
    raw = fetch_url(url)
    if not raw: return []
    try:
        root = ET.fromstring(raw.decode("utf-8", errors="replace"))
        return [{"title": i.findtext("title"), "desc": i.findtext("description"), "date": i.findtext("pubDate")} for i in root.iter("item")]
    except: return []

def strip_html(text: str) -> str:
    """Elimina tags HTML, entidades y URLs de imágenes. Devuelve texto plano."""
    if not text: return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-zA-Z#0-9]+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def parse_date(rss_date: str) -> datetime:
    """Convierte el string de fecha a un objeto datetime real para ordenar."""
    if not rss_date:
        return datetime.min.replace(tzinfo=timezone.utc)
    for fmt in ["%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"]:
        try:
            dt = datetime.strptime(rss_date.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except: continue
    return datetime.min.replace(tzinfo=timezone.utc)

def format_date(dt: datetime) -> str:
    """Convierte el datetime al formato visual del tablero."""
    if dt == datetime.min.replace(tzinfo=timezone.utc):
        return datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC").upper()
    return dt.strftime("%d %b %Y · %H:%M UTC").upper()


def is_relevant(item: dict):
    txt = f"{item['title']} {item['desc']}".lower()
    if any(ex in txt for ex in EXCLUSIONS): return False
    # Captura singular y plural (s/es)
    return any(re.search(rf"\b{re.escape(k)}(s|es)?\b", txt) for k in KEYWORDS)

# ── 3. LÓGICA DE INTELIGENCIA ────────────────────────────

def infer_ormuz_status(events: list, brent_chg: float, vix: float) -> dict:
    """Análisis táctico con lookback extendido y sensibilidad de saturación."""
    # Consolidamos texto de un pool mayor de noticias para evitar 'olvidos'
    txt = " ".join((e["headline"] + " " + e["detail"]).lower() for e in events)
    
    weights = {
        "closed": 60, "cerrado": 60, "blockade": 60, "bloqueo": 60,
        "mine": 55, "mina": 55, "sunk": 50, "hundido": 50, 
        "attack": 35, "ataque": 35, "missile": 30, "misil": 30,
        "buque": 15, "tanker": 15, "explos": 25 # Captura explosión/explosion
    }
    
    pressure = 0
    for k, w in weights.items():
        # Buscamos variantes y plurales de forma más agresiva
        matches = len(re.findall(rf"{re.escape(k)}", txt))
        if matches > 0:
            pressure += (w * min(matches, 4)) # Permitimos más acumulación
    
    pressure += (brent_chg * 5 if brent_chg > 0 else 0)
    pressure += (max(0, vix - 18) * 3) # Bajamos el piso del VIX para detectar miedo antes

    # CÁLCULO DE FLUJO
    flow = max(100 - pressure, 3)
    
    # TRIGGER CRÍTICO: Si hay mención de minas o hundimientos, O la presión es > 40
    # el flujo colapsa al mínimo residual inmediatamente.
    crit_terms = ["mine", "mina", "sunk", "hundido", "blockade", "bloqueo", "cerrado"]
    is_crit = any(re.search(rf"\b{k}", txt) for k in crit_terms)
    
    if is_crit or pressure > 40:
        flow = 3.0 # El 'cero absoluto' operativo

    summary = f"CIERRE FACTICIO: Flujo al {flow}%" if flow < 10 else ("DISRUPCIÓN SEVERA" if flow < 50 else "OPERATIVO")
    return {"flow": flow, "summary": summary, "pressure": pressure}
    
# ── 4. CONSTRUCCIÓN DEL JSON ─────────────────────────────

def build_intel():
    brent = fetch_yahoo(YAHOO_SYMBOLS["brent"])
    vix = fetch_yahoo(YAHOO_SYMBOLS["vix"])
    
    raw_items = []
    for url in RSS_FEEDS: raw_items.extend(parse_rss(url))
    
    relevant = [i for i in raw_items if is_relevant(i)]
    relevant.sort(key=lambda x: x['date'] or '', reverse=True)
    
    # ANALIZAMOS LAS TOP 20 PARA EL CÁLCULO (aunque mostremos 6)
    pool_for_calculation = []
    for i in relevant[:20]:
        txt = f"{i['title']} {i['desc']}".lower()
        if any(re.search(rf"{k}", txt) for k in ["attack", "mine", "sunk", "ataque", "mina", "hundido", "strike", "explosion"]):
            sev = "CRÍTICO"
        elif any(re.search(rf"{k}", txt) for k in ["tension", "threat", "disruption", "tensión", "amenaza", "perturbación", "rise", "spike"]):
            sev = "ALERTA"
        else:
            sev = "INFO"
        pool_for_calculation.append({
            "timestamp": format_date(i.get('date')),
            "headline": i['title'].upper()[:80],
            "detail": strip_html(i['desc'])[:220] if i['desc'] else "",
            "severity": sev
        })

    # Calculamos el status con el pool de 20 noticias
    ormuz = infer_ormuz_status(pool_for_calculation, brent["change"], vix["price"])
    
    # Nivel de Riesgo
    risk_level = "CRÍTICO" if ormuz["flow"] < 10 else ("ALTO" if ormuz["pressure"] > 25 else "MEDIO")
    
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "market": {"brent_usd": brent["price"], "brent_chg": brent["change"]},
        "indicators": {
            "ormuz_flow_pct": ormuz["flow"],
            "vix": vix["price"],
            "risk_level": risk_level,
            "insurance_spread_pct": round(0.8 + max(0, (vix["price"]-15)*0.4), 1)
        },
        "ormuz_status": {"summary": ormuz["summary"]},
        "events": pool_for_calculation[:6], # Solo mostramos las 6 más frescas
        "ticker_items": [f"BRENT: ${brent['price']} ({brent['change']:+.2f}%)", f"VIX: {vix['price']}", f"ORMUZ: {ormuz['summary']}"]
    }

if __name__ == "__main__":
    data = build_intel()
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)