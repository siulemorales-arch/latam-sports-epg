#!/usr/bin/env python3
"""Actualiza Mega Chile desde las páginas diarias de GatoTV."""

import html
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree as XML
from zoneinfo import ZoneInfo


CHANNEL_ID = "mega.chile.latam"
CHANNEL_NAME = "Mega Chile"
BASE_URL = "https://www.gatotv.com/canal/mega_chile"
ET = ZoneInfo("America/New_York")
ROW = re.compile(r'<tr class="tbl_EPG_row[^"]*"[^>]*>(.*?)</tr>', re.S)
TIME = re.compile(r'<time\s+datetime="(\d{2}:\d{2})"', re.S)
TITLE = re.compile(r'<div class="div_program_title_on_channel">(.*?)</div>', re.S)


def fetch_day(day):
    url = f"{BASE_URL}/{day.isoformat()}"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (latam-sports-epg)"})
    with urlopen(request, timeout=30) as response:
        page = response.read().decode("utf-8")
    if f'datetime="{day.isoformat()}"' not in page:
        return []  # GatoTV limita la cantidad de días futuros publicados.
    offset = re.search(r"utcOffset\s*:\s*(-?\d+(?:\.\d+)?)", page)
    if not offset:
        raise ValueError(f"GatoTV no indicó el desfase horario de {url}")
    source_zone = timezone(timedelta(hours=float(offset.group(1))))
    shows = []
    for index, row in enumerate(ROW.findall(page)):
        clocks = TIME.findall(row)
        match = TITLE.search(row)
        if len(clocks) != 2 or not match:
            continue
        title = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", match.group(1))).split())
        if not title or title.casefold() == "canal no disponible":
            continue
        start_day = day - timedelta(days=1) if index == 0 and "tbl_EPG_TimesColumnOutOfSchedule" in row else day
        start = datetime.combine(start_day, datetime.strptime(clocks[0], "%H:%M").time(), source_zone)
        stop = datetime.combine(day, datetime.strptime(clocks[1], "%H:%M").time(), source_zone)
        if stop <= start:
            stop += timedelta(days=1)
        shows.append((start.astimezone(ET), stop.astimezone(ET), title))
    return shows


def main():
    today = datetime.now(ET).date()
    unique = {}
    for shift in range(-1, 5):
        for start, stop, title in fetch_day(today + timedelta(days=shift)):
            unique[(start, title.casefold())] = (start, stop, title)
    shows = sorted(unique.values())
    if not shows or max(stop for _start, stop, _title in shows) < datetime.now(ET) + timedelta(hours=12):
        raise SystemExit("Mega Chile no tiene programación vigente suficiente en GatoTV")

    path = Path("epg.xml")
    document = XML.parse(path)
    root = document.getroot()
    channels = [node for node in root.findall("channel") if node.get("id") == CHANNEL_ID]
    if len(channels) > 1:
        raise SystemExit(f"ID duplicado: {CHANNEL_ID}")
    if not channels:
        channel = XML.Element("channel", {"id": CHANNEL_ID})
        XML.SubElement(channel, "display-name", {"lang": "es"}).text = CHANNEL_NAME
        XML.SubElement(channel, "display-name", {"lang": "es"}).text = "Mega (Chile)"
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
        XML.SubElement(programme, "title", {"lang": "es"}).text = title
    XML.indent(root, space="  ")
    temporary = path.with_suffix(".xml.tmp")
    document.write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace(path)
    print(f"Mega Chile: {len(shows)} programas desde GatoTV; horario ET")


if __name__ == "__main__":
    main()
