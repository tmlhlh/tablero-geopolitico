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

def is_relevant(item: dict):
    txt = f"{item['title']} {item['desc']}".lower()
    if any(ex in txt for ex in EXCLUSIONS): return False
    # Captura singular y plural (s/es)
    return any(re.search(rf"\b{re.escape(k)}(s|es)?\b", txt) for k in KEYWORDS)

# ── 3. LÓGICA DE INTELIGENCIA ────────────────────────────

def infer_ormuz_status(events: list, brent_chg: float, vix: float) -> dict:
    txt = " ".join((e["headline"] + " " + e["detail"]).lower() for e in events)
    
    # Pesos por tipo de noticia (Ponderación táctica)
    weights = {
        "closed": 60, "cerrado": 60, "blockade": 60, "bloqueo": 60,
        "mine": 55, "mina": 55, "sunk": 50, "hundido": 50, 
        "attack": 30, "ataque": 30, "missile": 25, "misil": 25
    }
    
    pressure = 0
    for k, w in weights.items():
        # Contamos cuántas veces aparece cada término (saturación informativa)
        matches = len(re.findall(rf"\b{re.escape(k)}(s|es)?\b", txt))
        if matches > 0:
            pressure += (w * min(matches, 3)) # Máximo 3 noticias por tipo para evitar sesgo
    
    # Sumamos pánico financiero (Brent y VIX)
    pressure += (brent_chg * 5 if brent_chg > 0 else 0)
    pressure += (max(0, vix - 20) * 3)

# CÁLCULO DE FLUJO (Mínimo residual 3%)
    flow = max(100 - pressure, 3)
    
    # CIERRE DE FACTO: Ajuste de sensibilidad extrema
    # Si hay noticias de minas, hundimientos o la presión supera el umbral de conflicto (50)
    crit_trigger = any(re.search(rf"\b{k}(s|es)?\b", txt) for k in ["closed", "cerrado", "blockade", "bloqueo", "mine", "mina", "sunk", "hundido"])
    
    if crit_trigger or pressure > 50:
        flow = min(flow, 3.0)

    # Determinación del Summary
    if flow <= 10:
        summary = f"CIERRE FACTICIO: Flujo al {flow:.1f}%."
    elif flow < 50:
        summary = f"DISRUPCIÓN SEVERA: Flujo al {flow:.1f}%."
    else:
        summary = "ESTRECHO OPERATIVO"

    return {"flow": round(flow, 1), "summary": summary, "pressure": pressure}

# ── 4. CONSTRUCCIÓN DEL JSON ─────────────────────────────

def build_intel():
    brent = fetch_yahoo(YAHOO_SYMBOLS["brent"])
    vix = fetch_yahoo(YAHOO_SYMBOLS["vix"])
    
    raw_items = []
    for url in RSS_FEEDS: raw_items.extend(parse_rss(url))
    
    relevant = [i for i in raw_items if is_relevant(i)]
    relevant.sort(key=lambda x: x['date'] or '', reverse=True)
    
    events = []
    for i in relevant[:6]:
        txt = f"{i['title']} {i['desc']}".lower()
        sev = "CRÍTICO" if any(re.search(rf"\b{k}(s|es)?\b", txt) for k in ["attack", "mine", "sunk", "war", "ataque", "mina", "hundido"]) else "INFO"
        events.append({
            "headline": i['title'].upper()[:80],
            "detail": i['desc'][:200] if i['desc'] else "Sin detalles.",
            "severity": sev,
            "timestamp": "INTEL RECIENTE"
        })

    ormuz = infer_ormuz_status(events, brent["change"], vix["price"])
    
    # Nivel de Riesgo (FIX para el NAN)
    risk_level = "CRÍTICO" if ormuz["flow"] < 15 else ("ALTO" if ormuz["pressure"] > 30 else "MEDIO")
    
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "market": {"brent_usd": brent["price"], "brent_chg": brent["change"]},
        "indicators": {
            "ormuz_flow_pct": ormuz["flow"],
            "vix": vix["price"],
            "risk_level": risk_level, # Esto arregla el NAN en el tablero
            "insurance_spread_pct": round(0.8 + max(0, (vix["price"]-15)*0.35), 1)
        },
        "ormuz_status": {"summary": ormuz["summary"]},
        "events": events,
        "ticker_items": [f"BRENT: ${brent['price']} ({brent['change']:+.2f}%)", f"VIX: {vix['price']}", f"ORMUZ: {ormuz['summary']}"]
    }

if __name__ == "__main__":
    data = build_intel()
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
