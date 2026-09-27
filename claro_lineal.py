#!/usr/bin/env python3
"""Actualiza el canal lineal Claro Sports México desde su guía diaria."""

import html
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree as XML
from zoneinfo import ZoneInfo


CHANNEL_ID = "claro.sports.mexico.latam"
NAME = "Claro Sports México"
GUIDE = "https://americatvguide.com/es/mx/channel/claro_sports"
MEXICO = ZoneInfo("America/Mexico_City")
ET = ZoneInfo("America/New_York")
ITEM = re.compile(r'href="/es/mx/c/claro-sports/(\d{6})/[^\"]+" title="([^\"]+)"')
HEADING = re.compile(r'<h5>Hoy - (\d{1,2})/(\d{1,2})/(\d{2})')


def schedule():
    request = Request(GUIDE, headers={"User-Agent": "Mozilla/5.0 (latam-sports-epg)"})
    with urlopen(request, timeout=30) as response:
        page = response.read().decode("utf-8")
    today = HEADING.search(page)
    if not today:
        raise ValueError("La guía de Claro Sports no publicó la fecha de hoy")
    day, month, year = map(int, today.groups())
    guide_date = datetime(2000 + year, month, day, tzinfo=MEXICO).date()
    if abs((guide_date - datetime.now(MEXICO).date()).days) > 1:
        raise ValueError(f"Guía de Claro Sports desactualizada: {guide_date}")
    shows = []
    for code, raw_title in ITEM.findall(page):
        date_day, hour, minute = int(code[:2]), int(code[2:4]), int(code[4:6])
        # La lista comienza con una emisión del día anterior y termina mañana.
        on_date = next((guide_date + timedelta(days=shift) for shift in (-1, 0, 1)
                        if (guide_date + timedelta(days=shift)).day == date_day), None)
        if on_date is None:
            continue
        title = html.unescape(raw_title).strip()
        title = re.sub(r"^\d{2}:\d{2}\s+", "", title)
        start = datetime(on_date.year, on_date.month, on_date.day, hour, minute, tzinfo=MEXICO)
        shows.append((start.astimezone(ET), title))
    shows = sorted(set(shows))
    programmes = []
    for (start, title), (stop, _next_title) in zip(shows, shows[1:]):
        if stop <= start or stop - start > timedelta(hours=8):
            continue
        # La agenda oficial identifica este bloque genérico como México–Colombia.
        # https://www.clarosports.com/futbol/agenda-deportiva-del-24-al-27-de-septiembre-debut-de-rafa-marquez-con-el-tri-nations-league-y-liga-mx/
        if start.strftime("%Y-%m-%d %H:%M") == "2026-09-26 21:00" and title == "Fútbol masculino amistosos internacionales":
            title = "México vs Colombia"
        programmes.append((start, stop, title))
    if len(programmes) < 15 or max(stop for _start, stop, _title in programmes) < datetime.now(ET) + timedelta(hours=12):
        raise SystemExit("Guía lineal de Claro Sports incompleta")
    return programmes


def main():
    shows = schedule()
    path = Path("epg.xml")
    document = XML.parse(path)
    root = document.getroot()
    channels = [c for c in root.findall("channel") if c.get("id") == CHANNEL_ID]
    if len(channels) > 1:
        raise SystemExit(f"ID duplicado: {CHANNEL_ID}")
    if not channels:
        channel = XML.Element("channel", {"id": CHANNEL_ID})
        XML.SubElement(channel, "display-name", {"lang": "es"}).text = NAME
        XML.SubElement(channel, "display-name", {"lang": "es"}).text = "Claro Sports (México)"
        root.insert(len(root.findall("channel")), channel)
    for p in list(root.findall("programme")):
        if p.get("channel") == CHANNEL_ID:
            root.remove(p)
    for start, stop, title in shows:
        p = XML.SubElement(root, "programme", {
            "start": start.strftime("%Y%m%d%H%M%S %z"),
            "stop": stop.strftime("%Y%m%d%H%M%S %z"),
            "channel": CHANNEL_ID,
        })
        XML.SubElement(p, "title", {"lang": "es"}).text = title
        XML.SubElement(p, "category", {"lang": "es"}).text = "Deportes"
    XML.indent(root, space="  ")
    temporary = path.with_suffix(".xml.tmp")
    document.write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace(path)
    print(f"{NAME}: {len(shows)} programas de la guía lineal; ET")


if __name__ == "__main__":
    main()
