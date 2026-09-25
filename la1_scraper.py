#!/usr/bin/env python3
"""Actualiza canales seleccionados usando la guía oficial de Movistar Plus."""

import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup


CHANNELS = (
    {
        "name": "LA 1 (España)",
        "id": "la.1.espana.latam",
        "slug": "tve",
        "category": "Generalista",
        "aliases": ("LA 1", "LA 1 HD", "TVE LA 1", "TVE 1", "ES| LA 1"),
    },
    {
        "name": "Eurosport 1 (España)",
        "id": "eurosport.1.espana.latam",
        "slug": "esp",
        "category": "Deportes",
        "aliases": (
            "EUROSPORT 1", "Eurosport 1", "EUROSPORT 1 FHD",
            "Eurosport 1 FHD", "EUROSPORT 1 HD", "Eurosport 1 HD",
            "EUROSPORT 1 SD", "Eurosport 1 SD",
        ),
    },
    {
        "name": "Eurosport 2 (España)",
        "id": "eurosport.2.espana.latam",
        "slug": "esp2",
        "category": "Deportes",
        "aliases": (
            "EUROSPORT 2", "Eurosport 2", "EUROSPORT 2 FHD",
            "Eurosport 2 FHD", "EUROSPORT 2 HD", "Eurosport 2 HD",
            "EUROSPORT 2 SD", "Eurosport 2 SD",
        ),
    },
)
GUIDE_ROOT = "https://www.movistarplus.es/programacion-tv"
USER_AGENT = (
    "Mozilla/5.0 (compatible; latam-sports-epg/1.0; "
    "+https://github.com/siulemorales-arch/latam-sports-epg)"
)


def clean(value):
    return " ".join((value or "").split())


def parse_clock(value, day, tz):
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", clean(value))
    if not match:
        raise ValueError(value)
    hour, minute = map(int, match.groups())
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


def fetch_day(slug, day, tz):
    url = f"{GUIDE_ROOT}/{slug}/{day.isoformat()}"
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    raw = []
    for box in soup.select("div.box"):
        title_node = box.select_one("li.title")
        time_node = box.select_one("li.time")
        if not title_node or not time_node:
            continue
        title = clean(title_node.get_text(" "))
        if not title:
            continue
        try:
            start = parse_clock(time_node.get_text(" "), day, tz)
        except ValueError:
            continue
        if raw:
            while start <= raw[-1][0]:
                start += timedelta(days=1)
        raw.append((start, title))

    shows = []
    for index, (start, title) in enumerate(raw):
        stop = raw[index + 1][0] if index + 1 < len(raw) else start + timedelta(hours=1)
        if stop > start:
            shows.append((start, stop, title))
    return shows


def fetch_channel(channel, today, tz):
    shows = []
    for offset in range(-1, 6):
        shows.extend(fetch_day(channel["slug"], today + timedelta(days=offset), tz))
    unique = {}
    for start, stop, title in shows:
        unique[(start.isoformat(), title.casefold())] = (start, stop, title)
    shows = sorted(unique.values(), key=lambda item: item[0])
    if not shows:
        raise SystemExit(f"Movistar Plus no devolvió programación para {channel['name']}")
    return shows


def replace_channel(root, channel, shows):
    channel_id = channel["id"]
    for node in list(root.findall("channel")):
        if node.get("id") == channel_id:
            root.remove(node)
    for node in list(root.findall("programme")):
        if node.get("channel") == channel_id:
            root.remove(node)

    channel_node = ET.Element("channel", {"id": channel_id})
    for display_name in (channel["name"], *channel["aliases"]):
        ET.SubElement(channel_node, "display-name", {"lang": "es"}).text = display_name
    first_programme = root.find("programme")
    insert_at = list(root).index(first_programme) if first_programme is not None else len(root)
    root.insert(insert_at, channel_node)

    for start, stop, title in shows:
        programme = ET.SubElement(root, "programme", {
            "start": start.strftime("%Y%m%d%H%M%S %z"),
            "stop": stop.strftime("%Y%m%d%H%M%S %z"),
            "channel": channel_id,
        })
        ET.SubElement(programme, "title", {"lang": "es"}).text = title
        ET.SubElement(programme, "category", {"lang": "es"}).text = channel["category"]


def main():
    tz = ZoneInfo("Europe/Madrid")
    today = datetime.now(tz).date()
    schedules = {channel["id"]: fetch_channel(channel, today, tz) for channel in CHANNELS}

    xml_path = Path("epg.xml")
    tree = ET.parse(xml_path)
    root = tree.getroot()
    for channel in CHANNELS:
        replace_channel(root, channel, schedules[channel["id"]])

    ET.indent(root, space="  ")
    temp_path = xml_path.with_suffix(".xml.tmp")
    tree.write(temp_path, encoding="utf-8", xml_declaration=True)
    temp_path.replace(xml_path)
    summary = ", ".join(
        f"{channel['name']}: {len(schedules[channel['id']])}"
        for channel in CHANNELS
    )
    print(f"Canales oficiales de Movistar Plus actualizados: {summary}")


if __name__ == "__main__":
    main()
