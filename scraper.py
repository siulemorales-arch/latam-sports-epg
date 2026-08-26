#!/usr/bin/env python3
import hashlib
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

GATO = "https://www.gatotv.com/guia_tv/completa"
GATO_CATALOG = "https://www.gatotv.com/canales"
DSPORTS = "https://dsports-widgets.tbxnet.com/widgets/epg/sports"
MOVISTAR_SPORTS = "https://www.movistarplus.es/programacion-tv/cpdep"
UA = "Mozilla/5.0 (compatible; latam-sports-epg/1.0; +https://github.com/siulemorales-arch/latam-sports-epg)"
SPORTS = re.compile(r"(?:^|\b)(?:ESPN(?:\s|$)|Fox Sports|TNT Sports|TyC Sports|TUDN|Win Sports|DSports|DirecTV Sports|Claro Sports|Sky Sports|TVC Deportes|Azteca Deportes|CDN Deportes|WAPA 2 Deportes|GolTV|Gol Peru|Gol Caracol|beIN Sports|AYM Sports|Adrenalina Sports|Teledeporte)(?:\b|$)", re.I)
# Además de los deportes, el mismo XML incluye las señales colombianas
# Caracol/RCN y todas las variantes que GatoTV identifique como Venezuela.
# Esto mantiene el descubrimiento dinámico cuando aparezcan señales nuevas.
GENERAL_LATAM = re.compile(r"\b(?:Caracol|RCN)\b|\bVenezuela\b", re.I)
MOVIE_CHANNELS = re.compile(r"\b(?:AMC|Cinemax|Cinecanal|Cine Latino|Cinema Dinamita|De Película|DHE|Europa Europa|Film ?& ?Arts|FX|Golden|HBO|Max|Mórbido|Multipremier|Paramount Network|Sony Movies|Space|Star Channel|Studio Universal|TCM|TNT|Universal TV)\b", re.I)
MOVIE_REGIONS = re.compile(r"\b(?:Latinoamérica|Latinoamerica|México|Mexico|Panregional)\b", re.I)
SPAIN_SPORTS = re.compile(r"(?:M\+ (?:Deportes|Golf|LALIGA|Liga de Campeones|Vamos|Baloncesto)|DAZN|Eurosport|Teledeporte|LALIGA TV|GOL$|Real Madrid TV|Canal Fútbol Replay|Caza y Pesca)", re.I)
EXCLUDE = re.compile(r"Espa(?:n|ñ)a|France|Italia|UK|Portugal", re.I)

TZ_RULES = [
    (re.compile(r"Mexico|México", re.I), "America/Mexico_City"),
    (re.compile(r"Chile|Sur|Argentina|TyC|TNT Sports", re.I), "America/Argentina/Buenos_Aires"),
    (re.compile(r"Colombia|Per[uú]|Ecuador|Win Sports", re.I), "America/Bogota"),
    (re.compile(r"Venezuela", re.I), "America/Caracas"),
    (re.compile(r"USA|Deportes", re.I), "America/New_York"),
]

# Nombres observados en la lista Xtream "1- WEIBTV LAT". XMLTV permite
# varios display-name por señal; así UHF puede asociar los nombres del
# proveedor sin cambiar los IDs estables.
DISPLAY_ALIASES = {
    "DSPORTS": [
        "DIRECTV SPORTS ARGENTINA", "DIRECTV SPORTS CHILE",
        "DIRECTV SPORTS URUGUAY", "DIRECTV SPORTS PERU",
    ],
    "DSPORTS 2": [
        "DSPORTS II COLOMBIA", "DSPORTS 2 | COLOMBIA",
        "DSPORTS II ARGENTINA", "DSPORTS 2 | ARGENTINA",
    ],
    "DSPORTS+": ["DSPORTS +"],
    "ESPN Chile": ["ESPN 1 CH HD", "ESPN 1 HD | CH"],
    "ESPN México": ["ESPN 1 MEX HD", "ESPN 1 MEX FHD", "ESPN 1 HD | MX"],
    "ESPN 4 México": ["ESPN 4 MX", "ESPN 4 HD | MX"],
    "Fox Sports Cono Norte": [
        "FOX SPORT 1 MX", "FOX SPORT 1 MX FHD",
        "FOX SPORTS 1 MX", "FOX SPORTS 1 FHD | MX",
    ],
    "Fox Sports 2 Cono Norte": [
        "FOX SPORTS 2 MX", "FOX SPORTS 2 FHD | MX",
    ],
    "Fox Sports 3 Cono Norte": [
        "FOX SPORTS 3 MX", "FOX SPORTS 3 HD | MX", "FOX SPORTS 3 FHD | MX",
    ],
    "TUDN México": ["TUDN HD | MX", "TUDN MX FHD", "TUDN FHD | MX"],
    "TUDN USA": ["TUDN HD | USA", "TUDN FHD | USA"],
}

# IDs alternativos para proveedores Xtream que usan el nombre visible como
# epg_channel_id. Se publican además del ID canónico, sin reemplazarlo.
PROVIDER_CHANNEL_IDS = {
    "DSPORTS": [
        "DSPORTS | AR", "DSPORTS | CO", "DIRECTV SPORTS ARGENTINA",
        "DIRECTV SPORTS CHILE", "DIRECTV SPORTS URUGUAY", "DIRECTV SPORTS PERU",
    ],
    "DSPORTS 2": [
        "DSPORTS II COLOMBIA", "DSPORTS 2 || COLOMBIA",
        "DSPORTS II ARGENTINA", "DSPORTS 2 | ARGENTINA",
    ],
    "DSPORTS+": ["DSPORTS +"],
}

def clean(s):
    return " ".join((s or "").split())

def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", ".", s).strip(".")
    return s + ".latam"

def timezone_for(name):
    for rx, tz in TZ_RULES:
        if rx.search(name): return ZoneInfo(tz)
    return ZoneInfo("America/Bogota")

def get(url, timeout=30):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    return r.text

def discover_gato_channels():
    soup = BeautifulSoup(get(GATO), "html.parser")
    found = {}
    for a in soup.select('a[href*="/canal/"]'):
        name, href = clean(a.get_text()), a.get("href", "")
        movie_feed = MOVIE_CHANNELS.search(name) and MOVIE_REGIONS.search(name)
        if name and (SPORTS.search(name) or GENERAL_LATAM.search(name) or movie_feed) and not EXCLUDE.search(name):
            found[href] = name
    # La guía completa no siempre muestra todas las señales venezolanas.
    # Complementamos desde el catálogo, que actualmente enumera decenas de
    # variantes y permite descubrir automáticamente las nuevas.
    catalog = BeautifulSoup(get(GATO_CATALOG), "html.parser")
    for a in catalog.select('a[href*="/canal/"]'):
        name, href = clean(a.get_text()), a.get("href", "")
        if name.lower().startswith("canal "):
            name = name[6:]
        movie_feed = MOVIE_CHANNELS.search(name) and MOVIE_REGIONS.search(name)
        if name and (GENERAL_LATAM.search(name) or movie_feed) and not EXCLUDE.search(name):
            found.setdefault(href, name)
    return sorted(found.items(), key=lambda x: x[1].casefold())

def parse_clock(text, day, tz):
    text = clean(text).upper().replace("A. M.", "AM").replace("P. M.", "PM")
    for fmt in ("%I:%M %p", "%H:%M"):
        try:
            t = datetime.strptime(text, fmt).time()
            return datetime.combine(day, t, tzinfo=tz)
        except ValueError:
            pass
    raise ValueError(text)

def scrape_gato_channel(url, name):
    html = get(url)
    soup = BeautifulSoup(html, "html.parser")
    target = None
    for table in soup.find_all("table"):
        heads = clean(table.get_text(" "))
        if "Hora Inicio" in heads and "Hora Fin" in heads and "Programa" in heads:
            target = table; break
    if target is None: return []
    # GatoTV ya convierte todos los relojes de la página a la zona elegida por
    # el sitio y publica el desfase como `utcOffset`. No debemos volver a
    # interpretar esos relojes como si fueran la zona del canal (AR/CO/MX),
    # porque eso desplaza la guía al verla en Miami.
    offset_match = re.search(r"utcOffset\s*:\s*(-?\d+(?:\.\d+)?)", html)
    if offset_match:
        tz = timezone(timedelta(hours=float(offset_match.group(1))))
    else:
        tz = timezone_for(name)
    day, out = datetime.now(tz).date(), []
    for tr in target.find_all("tr"):
        times = [clean(x.get_text()) for x in tr.find_all("time")]
        cells = tr.find_all(["td", "th"])
        if len(times) < 2 or len(cells) < 3: continue
        title = clean(cells[2].get_text(" "))
        if not title or title.lower() == "canal no disponible": continue
        try:
            start, stop = parse_clock(times[0], day, tz), parse_clock(times[1], day, tz)
        except ValueError: continue
        if stop <= start: stop += timedelta(days=1)
        out.append((start, stop, title, "GatoTV"))
    return out

def scrape_dsports():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(f"DSPORTS omitido: Playwright no disponible: {e}", file=sys.stderr); return {}
    rows = {0:"DSPORTS", 2:"DSPORTS 2", 3:"DSPORTS+"}
    result = {v: [] for v in rows.values()}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(DSPORTS, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector('[data-testid="content"] .programBox', timeout=30000)
            base_label = page.locator('.timelineTime').first.text_content().strip()
            data = page.eval_on_selector_all('[data-testid="content"] .programBox', """els => els.map(e => ({style:e.getAttribute('style')||'', title:(e.querySelector('.programTitle')?.textContent||'').trim()}))""")
            browser.close()
        # Chromium en GitHub Actions renderiza el widget en UTC. Conservamos
        # esa zona y dejamos que XMLTV/UHF convierta a la hora local.
        tz = ZoneInfo("UTC")
        day = datetime.now(tz).date()
        base_clock = datetime.strptime(base_label, "%H:%M").time()
        base = datetime.combine(day, base_clock, tzinfo=tz)
        for item in data:
            nums = {k:float(v) for k,v in re.findall(r"(width|top|left):\s*([0-9.]+)px", item["style"])}
            if not item["title"] or not all(k in nums for k in ("width","top","left")): continue
            row = round(nums["top"] / 78)
            if row not in rows: continue
            start = base + timedelta(minutes=nums["left"] / 7)
            stop = start + timedelta(minutes=nums["width"] / 7)
            if stop <= start: continue
            result[rows[row]].append((start, stop, item["title"], "DSPORTS oficial"))
    except Exception as e:
        print(f"DSPORTS omitido sin inventar datos: {e}", file=sys.stderr)
    return {k:v for k,v in result.items() if v}

def scrape_movistar_sports():
    """Descubre y obtiene todas las señales deportivas de Movistar Plus."""
    result = {}
    try:
        index = BeautifulSoup(get(MOVISTAR_SPORTS), "html.parser")
        feeds = {}
        for a in index.select('a[href*="/programacion-tv/"]'):
            img, href = a.find("img"), a.get("href", "")
            name = clean(img.get("title")) if img else ""
            if name and SPAIN_SPORTS.search(name):
                feeds[href.split("/2026-")[0]] = f"{name} (España)"
        tz, day = ZoneInfo("Europe/Madrid"), datetime.now(ZoneInfo("Europe/Madrid")).date()
        for url, name in sorted(feeds.items(), key=lambda x: x[1].casefold()):
            try:
                soup = BeautifulSoup(get(url), "html.parser")
                raw = []
                for box in soup.select("div.box"):
                    title_el, time_el = box.select_one("li.title"), box.select_one("li.time")
                    if not title_el or not time_el: continue
                    title, clock = clean(title_el.get_text(" ")), clean(time_el.get_text(" "))
                    try: moment = parse_clock(clock, day, tz)
                    except ValueError: continue
                    if raw and moment <= raw[-1][0]: moment += timedelta(days=1)
                    raw.append((moment, title))
                shows = []
                for i, (start, title) in enumerate(raw):
                    stop = raw[i + 1][0] if i + 1 < len(raw) else start + timedelta(hours=1)
                    if stop > start: shows.append((start, stop, title, "Movistar Plus oficial"))
                if shows: result[name] = shows
            except Exception as e:
                print(f"{name} omitido: {e}", file=sys.stderr)
            time.sleep(0.08)
    except Exception as e:
        print(f"Movistar Plus omitido sin inventar datos: {e}", file=sys.stderr)
    return result

def fmt(dt): return dt.strftime("%Y%m%d%H%M%S %z")

def main():
    channels = {}
    try:
        discovered = discover_gato_channels()
    except Exception as e:
        print(f"GatoTV falló: {e}", file=sys.stderr); discovered = []
    for i, (url, name) in enumerate(discovered, 1):
        try:
            shows = scrape_gato_channel(url, name)
            if shows: channels[name] = shows
        except Exception as e:
            print(f"{name} omitido: {e}", file=sys.stderr)
        time.sleep(0.12)
    for name, shows in scrape_dsports().items():
        channels[name] = shows
    for name, shows in scrape_movistar_sports().items():
        channels[name] = shows
    tv = ET.Element("tv", {"generator-info-name":"latam-sports-epg", "generator-info-url":"https://github.com/siulemorales-arch/latam-sports-epg"})
    ids = {}
    for name in sorted(channels, key=str.casefold):
        cid = slug(name); ids[name] = cid
        ch = ET.SubElement(tv, "channel", {"id":cid})
        ET.SubElement(ch, "display-name", {"lang":"es"}).text = name
        for alias in DISPLAY_ALIASES.get(name, []):
            ET.SubElement(ch, "display-name", {"lang":"es"}).text = alias
        for provider_id in PROVIDER_CHANNEL_IDS.get(name, []):
            provider_ch = ET.SubElement(tv, "channel", {"id":provider_id})
            ET.SubElement(provider_ch, "display-name", {"lang":"es"}).text = provider_id
    seen = set()
    for name in sorted(channels, key=str.casefold):
        for start, stop, title, source in sorted(channels[name], key=lambda x:x[0]):
            for target_id in [ids[name], *PROVIDER_CHANNEL_IDS.get(name, [])]:
                key = (target_id, fmt(start), fmt(stop), title.casefold())
                if key in seen: continue
                seen.add(key)
                pr = ET.SubElement(tv, "programme", {"start":fmt(start), "stop":fmt(stop), "channel":target_id})
                ET.SubElement(pr, "title", {"lang":"es"}).text = title
                ET.SubElement(pr, "category", {"lang":"es"}).text = "Deportes"
    ET.indent(tv, space="  ")
    Path("epg.xml").write_bytes(b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(tv, encoding="utf-8"))
    print(f"Generados {len(channels)} canales y {len(seen)} programas")
    if not channels or not seen: raise SystemExit("No se obtuvo programación real; no se publicará un XML vacío")

if __name__ == "__main__": main()
