#!/usr/bin/env python3
"""Actualiza TVC Deportes y Fox Sports México desde GatoTV por varios días."""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as XML

import requests
from bs4 import BeautifulSoup


CHANNELS = (
    ("tvc.deportes.latam", "TVC Deportes", "tvc_deportes"),
    ("fox.sports.cono.norte.latam", "Fox Sports México 1", "fox_sports_cono_norte"),
    ("fox.sports.2.cono.norte.latam", "Fox Sports México 2", "fox_sports_2_cono_norte"),
    ("fox.sports.3.cono.norte.latam", "Fox Sports México 3", "fox_sports_3_cono_norte"),
)
GUIDE_ROOT = "https://www.gatotv.com/canal"
ET_ZONE = timezone(timedelta(hours=-4))
USER_AGENT = (
    "Mozilla/5.0 (compatible; latam-sports-epg/1.0; "
    "+https://github.com/siulemorales-arch/latam-sports-epg)"
)


def clean(value):
    return " ".join((value or "").split())


def parse_clock(value, day, tz):
    text = clean(value).upper().replace("A. M.", "AM").replace("P. M.", "PM")
    for fmt in ("%I:%M %p", "%H:%M"):
        try:
            clock = datetime.strptime(text, fmt).time()
            return datetime.combine(day, clock, tzinfo=tz)
        except ValueError:
            pass
    raise ValueError(value)


def fetch_day(slug, day):
    url = f"{GUIDE_ROOT}/{slug}/{day.isoformat()}"
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    html = response.text
    soup = BeautifulSoup(html, "html.parser")
    offset = re.search(r"utcOffset\s*:\s*(-?\d+(?:\.\d+)?)", html)
    tz = timezone(timedelta(hours=float(offset.group(1)))) if offset else ET_ZONE

    target = None
    for table in soup.find_all("table"):
        heading = clean(table.get_text(" "))
        if "Hora Inicio" in heading and "Hora Fin" in heading and "Programa" in heading:
            target = table
            break
    if target is None:
        return []

    shows = []
    for row in target.find_all("tr"):
        times = [clean(node.get_text()) for node in row.find_all("time")]
        cells = row.find_all(["td", "th"])
        if len(times) < 2 or len(cells) < 3:
            continue
        title_node = row.select_one(".div_program_title_on_channel")
        title = clean(title_node.get_text(" ")) if title_node else clean(cells[-1].get_text(" "))
        if not title or title.casefold() == "canal no disponible":
            continue
        try:
            start = parse_clock(times[0], day, tz)
            stop = parse_clock(times[1], day, tz)
        except ValueError:
            continue
        if stop <= start:
            stop += timedelta(days=1)
        shows.append((start, stop, title))
    return shows


def fetch_channel(slug, today):
    shows = []
    for offset in range(-1, 5):
        shows.extend(fetch_day(slug, today + timedelta(days=offset)))
    unique = {}
    for start, stop, title in shows:
        unique[(start.isoformat(), title.casefold())] = (start, stop, title)
    return sorted(unique.values(), key=lambda item: item[0])


def main():
    today = datetime.now(ET_ZONE).date()
    schedules = {}
    for channel_id, name, slug in CHANNELS:
        shows = fetch_channel(slug, today)
        if not shows:
            raise SystemExit(f"GatoTV no devolvió programación para {name}")
        schedules[channel_id] = shows

    xml_path = Path("epg.xml")
    document = XML.parse(xml_path)
    root = document.getroot()
    existing_ids = {node.get("id") for node in root.findall("channel")}
    missing = {channel_id for channel_id, _name, _slug in CHANNELS} - existing_ids
    if missing:
        raise SystemExit(f"Faltan canales existentes en el XMLTV: {sorted(missing)}")

    target_ids = set(schedules)
    for node in list(root.findall("programme")):
        if node.get("channel") in target_ids:
            root.remove(node)

    for channel_id, name, _slug in CHANNELS:
        for start, stop, title in schedules[channel_id]:
            programme = XML.SubElement(root, "programme", {
                "start": start.strftime("%Y%m%d%H%M%S %z"),
                "stop": stop.strftime("%Y%m%d%H%M%S %z"),
                "channel": channel_id,
            })
            XML.SubElement(programme, "title", {"lang": "es"}).text = title
            XML.SubElement(programme, "category", {"lang": "es"}).text = "Deportes"

    XML.indent(root, space="  ")
    temp_path = xml_path.with_suffix(".xml.tmp")
    document.write(temp_path, encoding="utf-8", xml_declaration=True)
    temp_path.replace(xml_path)
    summary = ", ".join(
        f"{name}: {len(schedules[channel_id])}"
        for channel_id, name, _slug in CHANNELS
    )
    print(f"Canales mexicanos actualizados desde GatoTV: {summary}")


if __name__ == "__main__":
    main()
