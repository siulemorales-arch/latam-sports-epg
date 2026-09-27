#!/usr/bin/env python3
"""Actualiza GE TV y Premiere 1–9 desde la API pública de TVMap."""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree as XML
from zoneinfo import ZoneInfo


ET = ZoneInfo("America/New_York")
BASE = "https://tvmap.com.br/api"
CHANNELS = (
    ("ge.tv.brasil.latam", "GE TV", "GE"),
    ("premiere.1.brasil.latam", "Premiere 1", "Premiere-HD"),
    ("premiere.2.brasil.latam", "Premiere 2", "Premiere-HD-2"),
    ("premiere.3.brasil.latam", "Premiere 3", "Premiere-3"),
    ("premiere.4.brasil.latam", "Premiere 4", "Premiere-FC-4"),
    ("premiere.5.brasil.latam", "Premiere 5", "Premiere-FC-5"),
    ("premiere.6.brasil.latam", "Premiere 6", "Premiere-FC-6"),
    ("premiere.7.brasil.latam", "Premiere 7", "Premiere-7"),
    ("premiere.8.brasil.latam", "Premiere 8", "Premiere-8"),
    ("premiere.9.brasil.latam", "Premiere 9", "Premiere-9"),
)


def fetch(slug):
    unique = {}
    def fetch_day(suffix):
        url = f"{BASE}/{slug}" + (f"/{suffix}" if suffix else "")
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 (latam-sports-epg)"})
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    with ThreadPoolExecutor(max_workers=3) as executor:
        days = list(executor.map(fetch_day, ("Ontem", "", "Amanha")))
    for data in days:
        for item in data.get("exhibitions", []):
            start = datetime.fromisoformat(item["startDate"]).astimezone(ET)
            stop = datetime.fromisoformat(item["endDate"]).astimezone(ET)
            title = " ".join((item.get("title") or "Programação").split())
            category = " ".join((item.get("genre") or "").split())
            if stop > start:
                unique[(start, title)] = (start, stop, title, category)
    return sorted(unique.values())


def main():
    schedules = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        pending = {executor.submit(fetch, slug): (channel_id, name) for channel_id, name, slug in CHANNELS}
        for future in as_completed(pending):
            channel_id, name = pending[future]
            shows = future.result()
            if not shows:
                raise SystemExit(f"TVMap no devolvió programación para {name}")
            schedules[channel_id] = shows
    if len(schedules["ge.tv.brasil.latam"]) < 8:
        raise SystemExit("TVMap devolvió programación insuficiente para GE TV")
    path = Path("epg.xml")
    document = XML.parse(path)
    root = document.getroot()
    existing = {c.get("id") for c in root.findall("channel")}
    insert_at = len(root.findall("channel"))
    for channel_id, name, _slug in CHANNELS:
        if channel_id not in existing:
            channel = XML.Element("channel", {"id": channel_id})
            XML.SubElement(channel, "display-name", {"lang": "pt"}).text = name
            root.insert(insert_at, channel)
            insert_at += 1
    targets = set(schedules)
    for programme in list(root.findall("programme")):
        if programme.get("channel") in targets:
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
    print("TVMap Brasil: " + ", ".join(f"{name}: {len(schedules[channel_id])}" for channel_id, name, _slug in CHANNELS))


if __name__ == "__main__":
    main()
