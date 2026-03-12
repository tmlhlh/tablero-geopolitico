"""
update_intel.py — ARQUITECTURA MATEMÁTICA AVANZADA
- Co-ocurrencia semántica y proximidad.
- Atenuación logarítmica (evita cámara de eco mediática).
- Decaimiento temporal (Exponential time-decay para autosanación).
"""

import json
import re
import math
import html # <-- AGREGAR ESTA LÍNEA
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

KEYWORDS = ["strike", "mine", "missile", "drone", "blockade", "sunk", "attack", "ataque", "mina", "misil", "bloqueo", "hundido", "explosion", "explosión"]
MARITIME = ["gulf", "hormuz", "ormuz", "strait", "shipping", "vessel", "tanker", "port", "naval", "fleet", "maritime", "golfo", "estrecho", "buque", "barco", "petrolero", "puerto", "naviera"]
TOP_PRIORITY = ["hormuz", "ormuz", "bab el-mandeb"]
EXCLUSIONS = ["metanfetamina", "narcotráfico", "droga", "laos", "fútbol"]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ── 2. HELPERS (Cronología y Feeds) ───────────────────────

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
        items = []
        for i in root.iter("item"):
            title = i.findtext("title") or ""
            desc = i.findtext("description") or ""
            
            # 1. DECODIFICACIÓN: Convierte las entidades trampa (&lt;img&gt;) en HTML real (<img>)
            desc_unescaped = html.unescape(desc)
            
            # 2. ESTERILIZACIÓN EXTREMA: Arranca cualquier etiqueta HTML de cuajo
            clean_desc = re.sub(r'<[^>]+>', ' ', desc_unescaped)
            
            # 3. PULIDO: Elimina caracteres especiales que puedan romper el JSON o el diseño
            clean_desc = re.sub(r'&\w+;', ' ', clean_desc) # Vuela restos como &nbsp;
            clean_desc = re.sub(r'\s+', ' ', clean_desc).strip() # Saca saltos de línea extra
            
            date = i.findtext("pubDate") or ""
            items.append({"title": title, "desc": clean_desc, "date": date})
        return items
    except: return []

def parse_date(rss_date: str) -> datetime:
    if not rss_date: return datetime.min.replace(tzinfo=timezone.utc)
    for fmt in ["%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT", "%Y-%m-%dT%H:%M:%S%z"]:
        try:
            dt = datetime.strptime(rss_date.strip(), fmt)
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except: continue
    return datetime.min.replace(tzinfo=timezone.utc)

def format_date(dt: datetime) -> str:
    if dt == datetime.min.replace(tzinfo=timezone.utc): return datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC").upper()
    return dt.strftime("%d %b %Y · %H:%M UTC").upper()

def is_relevant(item: dict):
    txt = f"{item['title']} {item['desc']}".lower()
    if any(ex in txt for ex in EXCLUSIONS): return False
    if any(re.search(rf"\b{re.escape(tp)}s?\b", txt) for tp in TOP_PRIORITY): return True
    has_keyword = any(re.search(rf"\b{re.escape(k)}(s|es)?\b", txt) for k in KEYWORDS)
    has_context = any(re.search(rf"\b{re.escape(m)}(s|es)?\b", txt) for m in MARITIME)
    return has_keyword and has_context

# ── 3. MOTOR MATEMÁTICO (Inferencia) ─────────────────────

def infer_ormuz_status(events: list, brent_chg: float, vix: float) -> dict:
    now = datetime.now(timezone.utc)
    event_pressure = 0
    is_structural_closure = False
    
    proximity_pattern = r"(attack|ataque|strike|missile|misil|mine|mina|drone|explosion|explosión).{0,80}(tanker|vessel|buque|petrolero|ship|barco|port|puerto)"
    
    for e in events:
        txt = (e["headline"] + " " + e["detail"]).lower()
        
        # CÁLCULO DE DECAIMIENTO TEMPORAL (Half-life de 18 horas)
        age_hours = (now - e["dt_obj"]).total_seconds() / 3600
        decay = math.exp(-age_hours / 18) if age_hours > 0 else 1.0
        
        # PROXIMIDAD Y ATENUACIÓN LOGARÍTMICA
        prox_matches = len(re.findall(proximity_pattern, txt))
        if prox_matches > 0:
            # log1p(x) = log(1+x). Evita que 5 noticias idénticas multipliquen la presión x5.
            event_pressure += (40 * math.log1p(prox_matches) * decay)
            
        # EVENTOS ESTRUCTURALES (Pesos absolutos)
        if any(re.search(rf"\b{k}(s|es)?\b", txt) for k in ["closed", "cerrado", "blockade", "bloqueo", "mine", "mina", "sunk", "hundido"]):
            is_structural_closure = True
            event_pressure += (50 * decay)

    # PRESIÓN DE MERCADO
    market_pressure = (brent_chg * 5 if brent_chg > 0 else 0) + (max(0, vix - 18) * 3)
    
    # PRESIÓN TOTAL PONDERADA
    total_pressure = (event_pressure * 0.7) + (market_pressure * 0.3)

    # FÓRMULA DE FLUJO EXPONENCIAL (Curva suave de atrición)
    # Sensibilidad K = 35. A mayor presión, el flujo decae exponencialmente hacia 3%.
    flow = 100 * math.exp(-total_pressure / 35)
    flow = max(flow, 3.0) 
    
    if is_structural_closure:
        flow = min(flow, 8.5) # Techo estricto si hay cierre de facto
        
    summary = f"CIERRE FACTICIO: Flujo al {flow:.1f}%" if flow < 15 else ("DISRUPCIÓN SEVERA" if flow < 50 else "ESTRECHO OPERATIVO")
    
    return {"flow": round(flow, 1), "summary": summary, "pressure": total_pressure}

# ── 4. CONSTRUCCIÓN ───────────────────────────────────────

def build_intel():
    brent = fetch_yahoo(YAHOO_SYMBOLS["brent"])
    vix = fetch_yahoo(YAHOO_SYMBOLS["vix"])
    
    raw_items = []
    for url in RSS_FEEDS: raw_items.extend(parse_rss(url))
    
    relevant = [i for i in raw_items if is_relevant(i)]
    relevant.sort(key=lambda x: parse_date(x.get('date', '')), reverse=True)
    
    pool_for_calculation = []
    seen_headlines = set()
    
    for i in relevant:
        if len(pool_for_calculation) >= 20: break
        
        headline = i['title'].upper()[:80]
        # Deduplicación estricta por titular para ayudar al logaritmo
        if headline in seen_headlines: continue
        seen_headlines.add(headline)
        
        txt = f"{i['title']} {i['desc']}".lower()
        sev = "CRÍTICO" if any(re.search(rf"{k}", txt) for k in ["attack", "mine", "sunk", "ataque", "mina", "hundido", "strike"]) else "INFO"
        
        dt_obj = parse_date(i.get('date', ''))
        pool_for_calculation.append({
            "timestamp": format_date(dt_obj),
            "headline": headline,
            "detail": i['desc'][:200] if i['desc'] else "",
            "severity": sev,
            "dt_obj": dt_obj # Pasamos el objeto fecha para el cálculo de decaimiento
        })

    ormuz = infer_ormuz_status(pool_for_calculation, brent["change"], vix["price"])
    
    # Limpiamos el dt_obj antes de exportar a JSON porque no es serializable
    export_events = []
    for e in pool_for_calculation[:6]:
        export_events.append({k:v for k,v in e.items() if k != "dt_obj"})
    
    risk_level = "CRÍTICO" if ormuz["flow"] < 15 else ("ALTO" if ormuz["pressure"] > 30 else "MEDIO")
    
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "market": {"brent_usd": brent["price"], "brent_chg": brent["change"]},
        "indicators": {
            "ormuz_flow_pct": ormuz["flow"],
            "vix": vix["price"],
            "risk_level": risk_level,
            "insurance_spread_pct": round(0.8 + max(0, (vix["price"]-15)*0.35), 1)
        },
        "ormuz_status": {"summary": ormuz["summary"]},
        "events": export_events,
        "ticker_items": [f"BRENT: ${brent['price']} ({brent['change']:+.2f}%)", f"VIX: {vix['price']}", f"ORMUZ: {ormuz['summary']}"]
    }

if __name__ == "__main__":
    data = build_intel()
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)