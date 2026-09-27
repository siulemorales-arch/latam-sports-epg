#!/usr/bin/env python3
"""Actualiza Globo São Paulo desde su guía regional."""

import html
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree as XML
from zoneinfo import ZoneInfo


CHANNEL_ID = "globo.sp.brasil.latam"
NAME = "Globo SP"
GUIDE = "https://americatvguide.com/pt/br/channel/tv_globo_sao_paulo"
BRAZIL = ZoneInfo("America/Sao_Paulo")
ET = ZoneInfo("America/New_York")
ITEM = re.compile(r'href="/pt/br/c/tv-globo-sao-paulo/(\d{6})/[^\"]+" title="([^\"]+)"')
HEADING = re.compile(r'<h5>Hoje - (\d{1,2})/(\d{1,2})/(\d{2})')


def fetch():
    request = Request(GUIDE, headers={"User-Agent": "Mozilla/5.0 (latam-sports-epg)"})
    with urlopen(request, timeout=30) as response:
        page = response.read().decode("utf-8")
    match = HEADING.search(page)
    if not match:
        raise SystemExit("La guía de Globo SP no publicó su fecha")
    day, month, year = map(int, match.groups())
    guide_date = datetime(2000 + year, month, day, tzinfo=BRAZIL).date()
    if abs((guide_date - datetime.now(BRAZIL).date()).days) > 1:
        raise SystemExit(f"Guía de Globo SP desactualizada: {guide_date}")
    starts = []
    for code, raw_title in ITEM.findall(page):
        date_day, hour, minute = int(code[:2]), int(code[2:4]), int(code[4:6])
        on_date = next((guide_date + timedelta(days=shift) for shift in (-1, 0, 1)
                        if (guide_date + timedelta(days=shift)).day == date_day), None)
        if on_date is None:
            continue
        title = re.sub(r"^\d{2}:\d{2}\s+", "", html.unescape(raw_title)).strip()
        start = datetime(on_date.year, on_date.month, on_date.day, hour, minute, tzinfo=BRAZIL)
        starts.append((start.astimezone(ET), title))
    starts = sorted(set(starts))
    return [(start, starts[index + 1][0], title) for index, (start, title) in enumerate(starts[:-1])]


def main():
    shows = fetch()
    if len(shows) < 20:
        raise SystemExit(f"Guía de Globo SP incompleta: {len(shows)}")
    path = Path("epg.xml")
    document = XML.parse(path)
    root = document.getroot()
    channels = [c for c in root.findall("channel") if c.get("id") == CHANNEL_ID]
    if len(channels) > 1:
        raise SystemExit(f"ID duplicado: {CHANNEL_ID}")
    if not channels:
        channel = XML.Element("channel", {"id": CHANNEL_ID})
        XML.SubElement(channel, "display-name", {"lang": "pt"}).text = NAME
        XML.SubElement(channel, "display-name", {"lang": "pt"}).text = "TV Globo São Paulo"
        root.insert(len(root.findall("channel")), channel)
    for programme in list(root.findall("programme")):
        if programme.get("channel") == CHANNEL_ID:
            root.remove(programme)
    for start, stop, title in shows:
        programme = XML.SubElement(root, "programme", {
            "start": start.strftime("%Y%m%d%H%M%S %z"),
            "stop": stop.strftime("%Y%m%d%H%M%S %z"),
            "channel": CHANNEL_ID,
        })
        XML.SubElement(programme, "title", {"lang": "pt"}).text = title
    XML.indent(root, space="  ")
    temporary = path.with_suffix(".xml.tmp")
    document.write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace(path)
    print(f"{NAME}: {len(shows)} programas; ET")


if __name__ == "__main__":
    main()
