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
RSS_FEEDS = [
    "https://feeds.reuters.com/reuters/businessNews", # REUTERS (Internacional)
    "https://feeds.bbci.co.uk/news/world/rss.xml", # BBC (Británica)
    "https://www.eia.gov/rss/todayinenergy.xml", # EIA (Energía)
    "https://cnnespanol.cnn.com/feed/", # CNN (EEUU)
    "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/internacional/portada", # El País (España)
    "https://www.lanacion.com.ar/arc/outboundfeeds/rss/?outputType=xml", # La Nación (Argentina)
    "https://www.aljazeera.com/xml/rss/all.xml",              # Al-Jazeera (Qatar/Mundo Árabe)
    "https://www.xinhuanet.com/english/rss/worldrss.xml",     # Xinhua (China - Visión oficial)
    "https://www.rt.com/rss/news/",                           # RT News (Rusia - Perspectiva táctica/militar)
    "https://rss.dw.com/rdf/rss-sp-top"                       # Deutsche Welle (Alemania - Eje UE en español)
]
]

# Keywords para filtrar noticias relevantes al Golfo/energía
KEYWORDS = [
    # Inglés
    "oil", "crude", "energy", "hormuz", "strait", "tanker", "iran", "strike", "mine", 
    "missile", "drone", "blockade", "closure", "red sea", "navy", "sunk", "attack",
    # Español
    "petróleo", "crudo", "energía", "ormuz", "estrecho", "buque", "irán", "ataque", 
    "mina", "misil", "bloqueo", "cerrado", "mar rojo", "naval", "hundido", "explosión"
]

# Palabras que indican alta severidad (Color Rojo en el feed)
CRITICAL_KEYWORDS = [
    "attack", "strike", "war", "closure", "blockade", "explosion", "missile", 
    "mine", "minelaying", "sunk", "sink", "destroyed", "collision",
    "ataque", "guerra", "cierre", "bloqueo", "explosión", "misil", 
    "mina", "minado", "hundido", "destruido", "colisión"
]

# Palabras que indican alerta (Color Ámbar en el feed)
ALERT_KEYWORDS = [
    "disruption", "tension", "threat", "seized", "warning", "drill", "incident",
    "perturbación", "tensión", "amenaza", "incautado", "advertencia", "simulacro", "incidente"
]

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
    # Si la noticia menciona palabras críticas, es CRÍTICO
    if any(kw in text for kw in CRITICAL_KEYWORDS):
        return "CRÍTICO"
    # Si menciona alertas, es ALERTA
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


def infer_ormuz_status(events: list, brent_change: float, vix_price: float) -> dict:
    """
    Infiere el estado de flujo con sensibilidad táctica extrema y 
    correlación de pánico financiero (VIX).
    """
    # Consolidamos todo el texto de los eventos para el análisis de saturación
    text_all = " ".join((e["headline"] + " " + e["detail"]).lower() for e in events)
    
    # 1. CATEGORÍAS DE PESO (Ponderación por impacto operativo)
    # Subimos a 50/60 los puntos de 'mina' y 'hundido' porque paralizan el seguro marítimo
    weights = {
        # Impacto Crítico (Parálisis inmediata)
        "closed": 60, "cerrado": 60, "blockade": 60, "bloqueo": 60,
        "mine": 55, "mina": 55, "minelaying": 70, "minado": 70,
        "sunk": 50, "hundido": 50, "sink": 50, "destroyed": 50,
        
        # Impacto Alto (Riesgo cinético activo)
        "attack": 25, "ataque": 25, "missile": 30, "misil": 30, 
        "drone": 20, "strike": 25, "explosion": 25, "explosión": 25,
        
        # Impacto Medio (Tensión diplomática/logística)
        "seized": 15, "incautado": 15, "threat": 10, "amenaza": 10,
        "warning": 10, "tension": 10, "tensión": 10, "incident": 10
    }

    # 2. CÁLCULO DE PRESIÓN POR SATURACIÓN
    # No solo vemos si la palabra está, sino cuántas veces aparece en distintos medios
    pressure = 0
    for kw, weight in weights.items():
        count = text_all.count(kw)
        if count > 0:
            # Aplicamos un multiplicador por saturación (máximo 3 fuentes para no sesgar)
            saturation = min(count, 3)
            pressure += (weight * saturation)

    # 3. IMPACTO DE MERCADO (BRENT + VIX)
    # El Brent positivo suma presión lineal
    if brent_change > 0:
        pressure += (brent_change * 4)

    # El VIX (Pánico Global) actúa como multiplicador de presión
    # Un VIX > 25 indica que los mercados ya están huyendo del riesgo
    if vix_price > 25:
        pressure += (vix_price - 20) * 2.5

    # 4. DETERMINACIÓN DEL ESTADO
    # Definimos 'Cerrado' si hay palabras clave explícitas o la presión es extrema
    is_closed_news = any(kw in text_all for kw in ["closed", "cerrado", "blockade", "bloqueo", "mina", "mine"])
    
    # CÁLCULO FINAL DEL FLUJO (Piso técnico del 3%)
    # Si la presión es alta, el flujo cae exponencialmente hacia el flujo residual
    flow_pct = max(100 - pressure, 3)

    # Si hay confirmación de cierre o minas, el flujo no puede superar el 10%
    if is_closed_news:
        flow_pct = min(flow_pct, 10)

    # 5. REDACCIÓN DE RESUMEN ESTRATÉGICO
    if flow_pct <= 10:
        summary = f"CIERRE FACTICIO: Navegación paralizada por minado o hostilidades. Flujo residual: {flow_pct:.1f}%."
    elif flow_pct < 45:
        summary = f"DISRUPCIÓN CRÍTICA: Múltiples ataques detectados. Riesgo de seguro extremo. Flujo: {flow_pct:.1f}%."
    elif flow_pct < 85:
        summary = f"TENSIÓN LOGÍSTICA: Fricción operativa y desvíos preventivos. Flujo: {flow_pct:.1f}%."
    else:
        summary = "FLUJO NOMAL: Sin disrupciones sistémicas reportadas en los nodos principales."

    return {
        "open": flow_pct > 15,
        "disrupted": pressure > 20,
        "summary": summary,
        "flow_pct": round(flow_pct, 1)
    }

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
        if items:
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

    # CONEXIÓN CRÍTICA: Pasamos el VIX a la inferencia de Ormuz
    ormuz = infer_ormuz_status(events, brent["change_pct"], vix["price"])
    risk  = infer_risk_level(brent["change_pct"], events)

    # Spread de seguros: Ahora más realista usando el VIX como base de riesgo
    # Si el VIX sube de 20, el costo de asegurar un tanquero sube exponencialmente
    base_spread = 0.8
    vix_factor = max(0, (vix["price"] - 15) * 0.2)
    spread = round(base_spread + vix_factor + abs(brent["change_pct"]) * 0.3, 1)
    
    if not ormuz["open"]:    spread += 5.0 # Recargo por zona de guerra/cierre
    elif ormuz["disrupted"]: spread += 2.0

    # Ticker items: precio + top headlines
    ticker = [
        f"BRENT: ${brent['price']} ({brent['change_pct']:+.2f}%)",
        f"WTI: ${wti['price']} ({wti['change_pct']:+.2f}%)",
        f"VIX: {vix['price']} · RIESGO: {risk}",
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
