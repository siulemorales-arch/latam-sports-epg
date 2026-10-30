#!/usr/bin/env python3
"""Agrega SBT News Brasil desde su señal oficial continua."""

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup


SOURCE_URL = "https://sbtnews.sbt.com.br/videos/ao-vivo"
CHANNEL_ID = "sbt.news.brasil.latam"
DISPLAY_NAMES = ("SBT News Brasil", "SBT News")
ET_ZONE = ZoneInfo("America/New_York")


def verify_official_live_signal():
    response = requests.get(
        SOURCE_URL,
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0 (compatible; latam-sports-epg/1.0)"},
    )
    response.raise_for_status()
    text = " ".join(BeautifulSoup(response.text, "html.parser").stripped_strings)
    normalized = text.casefold()
    if "sbt news" not in normalized or "ao vivo" not in normalized:
        raise SystemExit("La fuente oficial no confirmó la señal SBT News en vivo")


def fmt(value):
    return value.strftime("%Y%m%d%H%M%S %z")


def main():
    verify_official_live_signal()

    xml_path = Path("epg.xml")
    tree = ET.parse(xml_path)
    root = tree.getroot()

    channels = [node for node in root.findall("channel") if node.get("id") == CHANNEL_ID]
    if len(channels) > 1:
        for duplicate in channels[1:]:
            root.remove(duplicate)
    if channels:
        channel = channels[0]
    else:
        channel = ET.Element("channel", {"id": CHANNEL_ID})
        first_programme = next(
            (index for index, node in enumerate(root) if node.tag == "programme"),
            len(root),
        )
        root.insert(first_programme, channel)

    existing_names = {node.text for node in channel.findall("display-name")}
    for name in DISPLAY_NAMES:
        if name not in existing_names:
            ET.SubElement(channel, "display-name", {"lang": "pt"}).text = name

    for programme in list(root.findall("programme")):
        if programme.get("channel") == CHANNEL_ID:
            root.remove(programme)

    today = datetime.now(ET_ZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    for offset in range(8):
        start = today + timedelta(days=offset)
        stop = start + timedelta(days=1)
        programme = ET.SubElement(
            root,
            "programme",
            {"start": fmt(start), "stop": fmt(stop), "channel": CHANNEL_ID},
        )
        ET.SubElement(programme, "title", {"lang": "pt"}).text = "SBT News — Ao vivo"
        ET.SubElement(programme, "desc", {"lang": "pt"}).text = (
            "Sinal oficial contínuo do SBT News."
        )
        ET.SubElement(programme, "category", {"lang": "pt"}).text = "Notícias"

    ET.indent(tree, space="  ")
    temporary = xml_path.with_suffix(".xml.tmp")
    tree.write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace(xml_path)
    print(f"SBT News Brasil: 8 blocos diários; ET; fonte oficial {SOURCE_URL}")


if __name__ == "__main__":
    main()
