#!/usr/bin/env python3
"""Incorpora emisiones confirmadas de Claro Sports Premium México al XMLTV."""

from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as XML
from zoneinfo import ZoneInfo


CHANNEL_ID = "claro.sports.premium.mexico.latam"
NAME = "Claro Sports Premium (México)"
ET = ZoneInfo("America/New_York")
# https://www.clarosports.com/futbol/seleccion-mexicana/mexico-vs-colombia-en-vivo-fecha-y-donde-ver-el-primer-partido-del-tri-en-la-era-de-rafa-marquez/
# https://www.clarosports.com/futbol/agenda-deportiva-del-24-al-27-de-septiembre-debut-de-rafa-marquez-con-el-tri-nations-league-y-liga-mx/
# La previa comienza a las 17:00 CDMX (19:00 ET); la cobertura del partido
# figura de 18:45 a 21:00 CDMX (20:45 a 23:00 ET), con inicio a las 21:00 ET.
SHOWS = (
    ("2026-09-26 19:00", "2026-09-26 20:45", "Previa: México vs Colombia"),
    ("2026-09-26 20:45", "2026-09-26 23:00", "México vs Colombia"),
)


def main():
    path = Path("epg.xml")
    document = XML.parse(path)
    root = document.getroot()
    channels = [c for c in root.findall("channel") if c.get("id") == CHANNEL_ID]
    if len(channels) > 1:
        raise SystemExit(f"ID duplicado: {CHANNEL_ID}")
    if not channels:
        channel = XML.Element("channel", {"id": CHANNEL_ID})
        XML.SubElement(channel, "display-name", {"lang": "es"}).text = NAME
        XML.SubElement(channel, "display-name", {"lang": "es"}).text = "Claro Sports Premium México"
        root.insert(len(root.findall("channel")), channel)
    for programme in list(root.findall("programme")):
        if programme.get("channel") == CHANNEL_ID:
            root.remove(programme)
    for raw_start, raw_stop, title in SHOWS:
        start = datetime.strptime(raw_start, "%Y-%m-%d %H:%M").replace(tzinfo=ET)
        stop = datetime.strptime(raw_stop, "%Y-%m-%d %H:%M").replace(tzinfo=ET)
        programme = XML.SubElement(root, "programme", {
            "start": start.strftime("%Y%m%d%H%M%S %z"),
            "stop": stop.strftime("%Y%m%d%H%M%S %z"),
            "channel": CHANNEL_ID,
        })
        XML.SubElement(programme, "title", {"lang": "es"}).text = title
        XML.SubElement(programme, "category", {"lang": "es"}).text = "Deportes"
    XML.indent(root, space="  ")
    temporary = path.with_suffix(".xml.tmp")
    document.write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace(path)
    print(f"{NAME}: {len(SHOWS)} emisiones confirmadas; ET")


if __name__ == "__main__":
    main()
