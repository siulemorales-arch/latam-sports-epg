#!/usr/bin/env python3
import hashlib
import html as html_lib
import json
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
DSPORTS_API = "https://epg.tbxapis.com/v0/epg/external/entries"
MOVISTAR_SPORTS = "https://www.movistarplus.es/programacion-tv/cpdep"
TELEMUNDO_SPORTS = "https://www.telemundo.com/deportes/telemundo-deportes-ahora"
TELEVEN_EPG = "https://app.televen.com/modules/epg"
UA = "Mozilla/5.0 (compatible; latam-sports-epg/1.0; +https://github.com/siulemorales-arch/latam-sports-epg)"
# Imágenes oficiales por programa. Se mantiene fuera de las tuplas de la guía
# para conservar la compatibilidad con las validaciones y respaldos existentes.
PROGRAMME_ICONS = {}
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
    "Telemundo Deportes Ahora (USA)": ["Telemundo Deportes Ahora"],
    "Televen (Venezuela)": ["Televen", "Televen HD"],
    "Venevisión (Venezuela)": ["Venevisión", "Venevision"],
    "Meridiano TV (Venezuela)": ["Meridiano TV", "Meridiano"],
    "Globovisión (Venezuela)": ["Globovisión", "Globovision"],
    "TVES (Venezuela)": ["TVES", "TVes"],
    "IVC (Venezuela)": ["IVC", "IVC Network"],
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
    if s == "DSPORTS+":
        return "dsports.plus.latam"
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", ".", s).strip(".")
    return s + ".latam"

def timezone_for(name):
    for rx, tz in TZ_RULES:
        if rx.search(name): return ZoneInfo(tz)
    return ZoneInfo("America/Bogota")

def spanish_provider_aliases(name):
    """Nombres observados en la categoría FÚTBOL ESPAÑA de WEIBTV."""
    if not name.endswith(" (España)"):
        return []
    base = name[:-9]
    aliases = {base, base.upper()}
    for quality in ("SD", "HD", "FHD"):
        aliases.add(f"{base} {quality}")
        aliases.add(f"{base.upper()} {quality}")
    # El canal principal aparece como "M+ Deportes" en Movistar, pero
    # muchos proveedores IPTV lo numeran como Deportes 1. Incluimos ambas
    # formas y las variantes "por M+" para que UHF pueda asociarlas solo.
    m = re.fullmatch(r"M\+ Deportes(?: (\d+))?", base, re.I)
    if m:
        number = m.group(1) or "1"
        provider_names = {
            f"M+ DEPORTES {number}", f"MOVISTAR DEPORTES {number}",
            f"DEPORTES {number} POR M+", f"M DEPORTES {number}",
        }
        if number == "1":
            provider_names.update({"MOVISTAR DEPORTES", "DEPORTES POR M+"})
        for provider_name in provider_names:
            aliases.add(provider_name)
            for quality in ("SD", "HD", "FHD"):
                aliases.add(f"{provider_name} {quality}")
    m = re.fullmatch(r"M\+ Liga de Campeones(?: (\d+))?", base, re.I)
    if m:
        number = f" {m.group(1)}" if m.group(1) else ""
        for quality in ("SD", "HD", "FHD"):
            aliases.add(f"LIGA DE CAMPEONES{number} POR M+ {quality}")
    m = re.fullmatch(r"M\+ LALIGA(?: (\d+))?(?: HDR)?", base, re.I)
    if m:
        number = f" {m.group(1)}" if m.group(1) else ""
        for quality in ("SD", "HD", "FHD"):
            aliases.add(f"LALIGA TV{number} POR M+ {quality}")
            aliases.add(f"LALIGA{number} POR M+ {quality}")
    if base.upper().startswith("DAZN LALIGA"):
        number = base[len("DAZN LALIGA"):]
        for quality in ("SD", "HD", "FHD"):
            aliases.add(f"DAZN LALIGA{number} {quality}")
            aliases.add(f"DZN LALIGA{number} {quality}")
    if base.upper().startswith("LALIGA TV HYPERMOTION"):
        number = base[len("LALIGA TV HYPERMOTION"):]
        for quality in ("SD", "HD", "FHD"):
            aliases.add(f"LALIGA TV HYPERMOTION{number} {quality}")
    if base == "GOL": aliases.update({"GOL PLAY", "GOL PLAY HD", "GOL PLAY FHD"})
    if base == "Real Madrid TV": aliases.update({"REAL MADRID TV HD", "REAL MADRID TV FHD"})
    if base == "M+ Golf": aliases.update({"M+ GOL HD", "M+ GOL FHD"})
    return sorted(aliases, key=str.casefold)

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
    out = []
    fallback_tz = timezone_for(name)
    today = datetime.now(fallback_tz).date()
    guide_days = 5 if name.upper().startswith("ESPN") else 1
    for day_offset in range(guide_days):
        guide_day = today + timedelta(days=day_offset)
        page_url = f"{url.rstrip('/')}/{guide_day.isoformat()}" if guide_days > 1 else url
        html = get(page_url)
        soup = BeautifulSoup(html, "html.parser")
        target = None
        for table in soup.find_all("table"):
            heads = clean(table.get_text(" "))
            if "Hora Inicio" in heads and "Hora Fin" in heads and "Programa" in heads:
                target = table; break
        if target is None: continue
        # GatoTV ya convierte los relojes y publica el desfase usado.
        offset_match = re.search(r"utcOffset\s*:\s*(-?\d+(?:\.\d+)?)", html)
        tz = timezone(timedelta(hours=float(offset_match.group(1)))) if offset_match else fallback_tz
        for tr in target.find_all("tr"):
            times = [clean(x.get_text()) for x in tr.find_all("time")]
            cells = tr.find_all(["td", "th"])
            if len(times) < 2 or len(cells) < 3: continue
            # Cuando GatoTV incluye una miniatura, la tercera celda es solo
            # la imagen y el título real pasa a una cuarta celda. Esto ocurre
            # mucho con SportsCenter y antes producía huecos en ESPN Sur.
            programme_title = tr.select_one(".div_program_title_on_channel")
            title = clean(programme_title.get_text(" ")) if programme_title else clean(cells[-1].get_text(" "))
            if not title or title.lower() == "canal no disponible": continue
            try:
                start = parse_clock(times[0], guide_day, tz)
                stop = parse_clock(times[1], guide_day, tz)
            except ValueError: continue
            if stop <= start: stop += timedelta(days=1)
            out.append((start, stop, title, "GatoTV"))
    return out

def scrape_dsports():
    # El widget visual recorta la parrilla al ancho visible. Su API oficial
    # entrega la programación completa de varios días en UTC.
    names = {
        "1610": "DSPORTS", "1612": "DSPORTS 2", "1613": "DSPORTS+",
        "1614": "DSPORTS Eventos 1", "1615": "DSPORTS Eventos 2",
        "1616": "DSPORTS Eventos 3", "1618": "DSPORTS Eventos 4",
    }
    result = {name: [] for name in names.values()}
    try:
        payload = requests.get(DSPORTS_API, headers={"User-Agent": UA}, timeout=30)
        payload.raise_for_status()
        for item in payload.json().get("data", {}).get("programs", []):
            name = names.get(str(item.get("ChannelNum", "")))
            title = clean(item.get("Title"))
            if not name or not title: continue
            start = datetime.fromisoformat(item["StartDate"].replace("Z", "+00:00"))
            stop = datetime.fromisoformat(item["EndDate"].replace("Z", "+00:00"))
            if stop > start:
                result[name].append((start, stop, title, "DSPORTS API oficial"))
                image_url = clean(item.get("ImageURL"))
                if image_url.startswith("https://"):
                    PROGRAMME_ICONS[(name, start.isoformat(), stop.isoformat(), title.casefold())] = image_url
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
        tz = ZoneInfo("Europe/Madrid")
        today = datetime.now(tz).date()
        for url, name in sorted(feeds.items(), key=lambda x: x[1].casefold()):
            shows = []
            # Movistar asigna la madrugada (00:00-05:00 aprox.) a la
            # parrilla del día anterior. Consultarla evita que UHF muestre
            # huecos durante esas horas en DAZN y en las señales M+.
            for day_offset in range(-1, 5):
                guide_day = today + timedelta(days=day_offset)
                page_url = f"{url.rstrip('/')}/{guide_day.isoformat()}"
                try:
                    soup = BeautifulSoup(get(page_url), "html.parser")
                except Exception as e:
                    print(f"{name} {guide_day} omitido: {e}", file=sys.stderr)
                    continue
                raw = []
                for box in soup.select("div.box"):
                    title_el, time_el = box.select_one("li.title"), box.select_one("li.time")
                    if not title_el or not time_el: continue
                    title, clock = clean(title_el.get_text(" ")), clean(time_el.get_text(" "))
                    try: moment = parse_clock(clock, guide_day, tz)
                    except ValueError: continue
                    raw.append((moment, title))
                # Algunas parrillas empiezan mostrando el programa que
                # comenzó la noche anterior (p. ej. 23:30) y luego pasan a
                # las 08:00 del día elegido. Esa primera hora pertenece al
                # día anterior, no convierte las 08:00 en el día siguiente.
                if (len(raw) >= 2 and raw[0][0].hour >= 18
                        and raw[1][0].hour < 12 and raw[1][0] <= raw[0][0]):
                    raw[0] = (raw[0][0] - timedelta(days=1), raw[0][1])
                for i in range(1, len(raw)):
                    moment, title = raw[i]
                    while moment <= raw[i - 1][0]:
                        moment += timedelta(days=1)
                    raw[i] = (moment, title)
                for i, (start, title) in enumerate(raw):
                    stop = raw[i + 1][0] if i + 1 < len(raw) else start + timedelta(hours=1)
                    if stop > start: shows.append((start, stop, title, "Movistar Plus oficial"))
                time.sleep(0.06)
            if shows: result[name] = shows
        # En las señales HDR/eventos, UHF debe mostrar una guía continua.
        # Conservamos cada programa oficial y rellenamos únicamente huecos
        # reales con un aviso explícito, tal como pidió el usuario.
        for hdr_name in [name for name in result if " HDR (España)" in name]:
            original = sorted(result[hdr_name], key=lambda x: x[0])
            fillers = []
            for day_offset in range(5):
                day_start = datetime.combine(today + timedelta(days=day_offset), datetime.min.time(), tzinfo=tz)
                day_stop = day_start + timedelta(days=1)
                cursor = day_start
                for start, stop, _title, _source in original:
                    if stop <= day_start or start >= day_stop:
                        continue
                    clipped_start, clipped_stop = max(start, day_start), min(stop, day_stop)
                    if clipped_start > cursor:
                        fillers.append((cursor, clipped_start, f"{hdr_name[:-9]} — Sin emisión", "Relleno explícito"))
                    cursor = max(cursor, clipped_stop)
                if cursor < day_stop:
                    fillers.append((cursor, day_stop, f"{hdr_name[:-9]} — Sin emisión", "Relleno explícito"))
            result[hdr_name] = original + fillers
    except Exception as e:
        print(f"Movistar Plus omitido sin inventar datos: {e}", file=sys.stderr)
    return result

def scrape_telemundo_sports():
    """Usa toda la parrilla fechada que Telemundo publica en NEXT_DATA."""
    name = "Telemundo Deportes Ahora (USA)"
    try:
        page = get(TELEMUNDO_SPORTS)
        match = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
        if not match:
            raise ValueError("la página no publicó __NEXT_DATA__")
        data = json.loads(html_lib.unescape(match.group(1)))
        schedules = data["props"]["pageProps"]["ramenBentoAPISWRFallbackData"]["broadcastSchedules"]
        items = schedules["TELEMUNDO_DEPORTES_AHORA"]["scheduleItems"]
        shows = []
        for item in items:
            title = clean(item.get("title"))
            if not title: continue
            start = datetime.fromisoformat(item["startDateTime"].replace("Z", "+00:00"))
            stop = datetime.fromisoformat(item["endDateTime"].replace("Z", "+00:00"))
            if stop > start:
                shows.append((start, stop, title, "Telemundo oficial"))
        return {name: shows} if shows else {}
    except Exception as e:
        print(f"Telemundo Deportes Ahora omitido sin inventar datos: {e}", file=sys.stderr)
        return {}

def scrape_venezuela_epg():
    """Extrae la ventana máxima (hoy + 7 días) publicada por Televen Max.

    La aplicación es dinámica. Playwright inicia su sesión de invitado y
    reutilizamos exactamente la llamada EPG que realiza la propia página.
    """
    wanted = {
        "televen": "Televen (Venezuela)",
        "venevision": "Venevisión (Venezuela)",
        "meridiano": "Meridiano TV (Venezuela)",
        "globovision": "Globovisión (Venezuela)",
        "tves": "TVES (Venezuela)",
        "ivc": "IVC (Venezuela)",
    }

    def normalized(value):
        return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", value or "")
                      .encode("ascii", "ignore").decode().lower())

    result = {display: [] for display in wanted.values()}
    try:
        from playwright.sync_api import sync_playwright

        tz = ZoneInfo("America/Caracas")
        today = datetime.now(tz).date()
        page_url = f"{TELEVEN_EPG}?categoryName=All&date={today.isoformat()}"
        channel_payloads, epg_requests = [], []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(user_agent=UA, locale="es-VE")
            page = context.new_page()

            def remember_request(request):
                if "/media/tv/epg" in request.url and request.method == "POST":
                    epg_requests.append(request)

            def remember_response(response):
                if "/v3/channels?" in response.url and "type=TV" in response.url:
                    try:
                        channel_payloads.append(response.json())
                    except Exception:
                        pass

            page.on("request", remember_request)
            page.on("response", remember_response)
            page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(12000)
            if not epg_requests:
                raise ValueError("la aplicación no emitió la solicitud EPG")

            channels = []
            for payload in channel_payloads:
                body = payload.get("payload", payload) if isinstance(payload, dict) else {}
                content = body.get("content", []) if isinstance(body, dict) else []
                channels.extend(x for x in content if isinstance(x, dict))

            selected = {}
            for channel in channels:
                label = normalized(channel.get("name", ""))
                for key, display in wanted.items():
                    # Evita confundir Televen con canales de nombre parecido.
                    if (key == "televen" and label in {"televen", "televenhd"}) or (
                        key != "televen" and key in label
                    ):
                        epg_id = str(channel.get("epgId") or "")
                        if epg_id:
                            selected[display] = epg_id

            if not selected:
                raise ValueError("no se encontraron IDs de los seis canales solicitados")

            original = epg_requests[-1]
            epg_url = original.url
            headers = {
                k: v for k, v in original.headers.items()
                if k.lower() not in {"content-length", "host", "cookie"}
            }
            start = datetime.combine(today, datetime.min.time(), tzinfo=tz)
            stop = start + timedelta(days=8)
            body = {
                "channelEpgIds": sorted(set(selected.values())),
                "fromDate": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "toDate": stop.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            response = context.request.post(epg_url, headers=headers, data=body, timeout=60000)
            if not response.ok:
                raise ValueError(f"servicio EPG respondió HTTP {response.status}")
            epg = response.json()

            for display, epg_id in selected.items():
                for item in epg.get(epg_id, []) if isinstance(epg, dict) else []:
                    title = clean(item.get("title"))
                    if not title or not item.get("start") or not item.get("stop"):
                        continue
                    begin = datetime.fromisoformat(item["start"].replace("Z", "+00:00"))
                    end = datetime.fromisoformat(item["stop"].replace("Z", "+00:00"))
                    if end > begin:
                        result[display].append((begin, end, title, "Televen Max oficial"))
            browser.close()
    except Exception as e:
        print(f"Televen Max omitido sin inventar datos: {e}", file=sys.stderr)
    return {name: shows for name, shows in result.items() if shows}

def fmt(dt): return dt.strftime("%Y%m%d%H%M%S %z")

def parse_xmltv_datetime(value):
    return datetime.strptime(value, "%Y%m%d%H%M%S %z")

def load_previous_guide(path="epg.xml"):
    """Recupera programas aún vigentes del último XML publicado.

    Solo se usa para señales que desaparecieron de la extracción actual. Los
    cuatro grupos críticos se validan antes, de modo que una caída importante
    detiene la publicación y conserva íntegramente el XML anterior.
    """
    previous = {}
    xml_path = Path(path)
    if not xml_path.exists():
        return previous
    try:
        root = ET.parse(xml_path).getroot()
        names = {}
        for channel in root.findall("channel"):
            cid = channel.get("id", "")
            display = channel.findtext("display-name")
            if cid.endswith(".latam") and display:
                names[cid] = display
        now = datetime.now(timezone.utc)
        for programme in root.findall("programme"):
            name = names.get(programme.get("channel", ""))
            title = clean(programme.findtext("title"))
            if not name or not title:
                continue
            start = parse_xmltv_datetime(programme.get("start", ""))
            stop = parse_xmltv_datetime(programme.get("stop", ""))
            if stop > now and stop > start:
                previous.setdefault(name, []).append(
                    (start, stop, title, "Última guía válida")
                )
    except Exception as e:
        print(f"No se pudo recuperar la guía anterior: {e}", file=sys.stderr)
        return {}
    return previous

def validate_fresh_guide(channels):
    """Impide publicar una extracción incompleta o degradada."""
    programme_count = sum(len(shows) for shows in channels.values())
    errors = []
    if len(channels) < 80:
        errors.append(f"solo {len(channels)} canales frescos (mínimo 80)")
    if programme_count < 1500:
        errors.append(f"solo {programme_count} programas frescos (mínimo 1500)")

    critical = {
        "DSPORTS": lambda name: name == "DSPORTS",
        "ESPN Argentina/Sur": lambda name: name == "ESPN Sur",
        "DAZN": lambda name: name.startswith("DAZN ") or name == "DAZN (España)",
        "M+ LALIGA": lambda name: name == "M+ LALIGA (España)",
    }
    for label, predicate in critical.items():
        matches = [name for name, shows in channels.items() if predicate(name) and shows]
        if not matches:
            errors.append(f"faltó el grupo crítico {label}")

    # ESPN Sur y ESPN 2 Sur son señales continuas. Un hueco interno superior
    # a 30 minutos suele indicar que cambió el HTML de GatoTV.
    for name in ("ESPN Sur", "ESPN 2 Sur"):
        shows = sorted(channels.get(name, []), key=lambda item: item[0])
        coverage_end = None
        largest_gap = timedelta(0)
        for start, stop, _title, _source in shows:
            if coverage_end is not None and start > coverage_end:
                largest_gap = max(largest_gap, start - coverage_end)
            coverage_end = max(coverage_end, stop) if coverage_end else stop
        if shows and largest_gap > timedelta(minutes=30):
            errors.append(f"{name} tiene un hueco de {largest_gap}")

    if errors:
        raise SystemExit("Control de calidad rechazó la actualización: " + "; ".join(errors))
    print(f"Control de calidad aprobado: {len(channels)} canales y {programme_count} programas frescos")

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
    for name, shows in scrape_telemundo_sports().items():
        channels[name] = shows
    for name, shows in scrape_venezuela_epg().items():
        channels[name] = shows
    validate_fresh_guide(channels)

    previous = load_previous_guide()
    restored = 0
    for name, shows in previous.items():
        if name not in channels and shows:
            channels[name] = shows
            restored += 1
            print(f"Restaurado desde la última guía válida: {name}", file=sys.stderr)
    print(f"Canales restaurados desde el XML anterior: {restored}")

    tv = ET.Element("tv", {"generator-info-name":"latam-sports-epg", "generator-info-url":"https://github.com/siulemorales-arch/latam-sports-epg"})
    ids = {}
    for name in sorted(channels, key=str.casefold):
        cid = slug(name); ids[name] = cid
        ch = ET.SubElement(tv, "channel", {"id":cid})
        ET.SubElement(ch, "display-name", {"lang":"es"}).text = name
        for alias in DISPLAY_ALIASES.get(name, []):
            ET.SubElement(ch, "display-name", {"lang":"es"}).text = alias
        for alias in spanish_provider_aliases(name):
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
                icon_url = PROGRAMME_ICONS.get((name, start.isoformat(), stop.isoformat(), title.casefold()))
                if icon_url:
                    ET.SubElement(pr, "icon", {"src":icon_url})
    ET.indent(tv, space="  ")
    output = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(tv, encoding="utf-8")
    Path("epg.xml.tmp").write_bytes(output)
    Path("epg.xml.tmp").replace("epg.xml")
    print(f"Generados {len(channels)} canales y {len(seen)} programas")
    if not channels or not seen: raise SystemExit("No se obtuvo programación real; no se publicará un XML vacío")

if __name__ == "__main__": main()
