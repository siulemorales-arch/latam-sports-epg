#!/usr/bin/env python3
"""Actualiza señales brasileñas desde MeuGuia.TV y las convierte a ET."""

import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree as XML
from zoneinfo import ZoneInfo


SOURCE = "https://meuguia.tv/programacao/canal"
BRAZIL = ZoneInfo("America/Sao_Paulo")
ET = ZoneInfo("America/New_York")
CHANNELS = (
    ("globo.rj.brasil.latam", "Globo RJ", "GRD"),
    ("sportv.1.brasil.latam", "SporTV", "SPO"),
    ("sportv.2.brasil.latam", "SporTV 2", "SP2"),
    ("sportv.3.brasil.latam", "SporTV 3", "SP3"),
    ("espn.1.brasil.latam", "ESPN Brasil", "ESP"),
    ("espn.2.brasil.latam", "ESPN 2 Brasil", "ES2"),
    ("espn.3.brasil.latam", "ESPN 3 Brasil", "ES3"),
    ("espn.4.brasil.latam", "ESPN 4 Brasil", "ES4"),
    ("espn.5.brasil.latam", "ESPN 5 Brasil", "ES5"),
    ("premiere.clubes.brasil.latam", "Premiere Clubes", "121"),
)
EXTRA_CHANNELS = (
    # SporTV 4 es una señal eventual de Globoplay: MeuGuia no publica una
    # parrilla lineal para ella. Se conserva el ID sin fabricar programas.
    ("sportv.4.brasil.latam", "SporTV 4"),
)
TOKEN = re.compile(
    r'<li class="subheader devicepadding">[^<]*?(\d{1,2})/(\d{1,2})</li>'
    r'|<li>\s*<a[^>]*>\s*<div class=[\'\"]lileft time[\'\"]>(\d{2}:\d{2})</div>'
    r'.*?<h2>(.*?)</h2>\s*<h3>(.*?)</h3>', re.S,
)


def clean(value):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value or "")).split())


def fetch(slug):
    request = Request(f"{SOURCE}/{slug}", headers={"User-Agent": "Mozilla/5.0 (latam-sports-epg)"})
    with urlopen(request, timeout=30) as response:
        page = response.read().decode("utf-8")
    page = re.sub(r"<!--.*?-->", "", page, flags=re.S)
    now = datetime.now(BRAZIL)
    current_date = None
    starts = []
    for match in TOKEN.finditer(page):
        day, month, clock, raw_title, raw_category = match.groups()
        if day:
            year = now.year
            candidate = datetime(year, int(month), int(day), tzinfo=BRAZIL).date()
            if candidate < now.date() - timedelta(days=180):
                candidate = candidate.replace(year=year + 1)
            elif candidate > now.date() + timedelta(days=180):
                candidate = candidate.replace(year=year - 1)
            current_date = candidate
            continue
        if current_date is None:
            continue
        hour, minute = map(int, clock.split(":"))
        start = datetime(current_date.year, current_date.month, current_date.day, hour, minute, tzinfo=BRAZIL)
        starts.append((start.astimezone(ET), clean(raw_title), clean(raw_category)))
    starts = sorted(set(starts))
    shows = []
    for index, (start, title, category) in enumerate(starts):
        stop = starts[index + 1][0] if index + 1 < len(starts) else start + timedelta(hours=1)
        if stop > start:
            shows.append((start, stop, title, category))
    return shows


def main():
    schedules = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        pending = {executor.submit(fetch, slug): (channel_id, name) for channel_id, name, slug in CHANNELS}
        for future in as_completed(pending):
            channel_id, name = pending[future]
            shows = future.result()
            if len(shows) < 10:
                raise SystemExit(f"MeuGuia devolvió programación insuficiente para {name}: {len(shows)}")
            schedules[channel_id] = shows
    path = Path("epg.xml")
    document = XML.parse(path)
    root = document.getroot()
    existing = {c.get("id"): c for c in root.findall("channel")}
    insert_at = len(root.findall("channel"))
    for channel_id, name, _slug in CHANNELS:
        if channel_id not in existing:
            channel = XML.Element("channel", {"id": channel_id})
            XML.SubElement(channel, "display-name", {"lang": "pt"}).text = name
            root.insert(insert_at, channel)
            insert_at += 1
    for channel_id, name in EXTRA_CHANNELS:
        if channel_id not in existing:
            channel = XML.Element("channel", {"id": channel_id})
            XML.SubElement(channel, "display-name", {"lang": "pt"}).text = name
            XML.SubElement(channel, "display-name", {"lang": "pt"}).text = "SporTV 4 (Globoplay)"
            root.insert(insert_at, channel)
            insert_at += 1
    target_ids = set(schedules)
    for programme in list(root.findall("programme")):
        if programme.get("channel") in target_ids:
            root.remove(programme)
    for channel_id, _name, _slug in CHANNELS:
        for start, stop, title, category in schedules[channel_id]:
            programme = XML.SubElement(root, "programme", {
                "start": start.strftime("%Y%m%d%H%M%S %z"),
                "stop": stop.strftime("%Y%m%d%H%M%S %z"),
                "channel": channel_id,
            })
            XML.SubElement(programme, "title", {"lang": "pt"}).text = title
            if category:
                XML.SubElement(programme, "category", {"lang": "pt"}).text = category
    XML.indent(root, space="  ")
    temporary = path.with_suffix(".xml.tmp")
    document.write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace(path)
    print("MeuGuia Brasil: " + ", ".join(f"{name}: {len(schedules[channel_id])}" for channel_id, name, _slug in CHANNELS))


if __name__ == "__main__":
    main()
