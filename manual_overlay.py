#!/usr/bin/env python3
"""Aplica las capturas manuales al XMLTV incluso si falla el scraper principal."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as XML
from zoneinfo import ZoneInfo


ET = ZoneInfo("America/New_York")
XMLTV = "%Y%m%d%H%M%S %z"


def channel_id(name):
    if name.startswith("Sky Sports+ "):
        return f"sky.sports.{int(name.split('+ ')[1])}.latam"
    if name.startswith("Peacock "):
        return f"peacock.{int(name.split()[-1]):02d}.latam"
    if name.startswith("Coupang Play "):
        return f"coupang.play.{int(name.split()[-1])}.latam"
    if name.startswith("Amazon UK "):
        return f"amazon.uk.{int(name.split()[-1])}.latam"
    return None


def parse(value):
    return datetime.strptime(value, XMLTV).astimezone(timezone.utc)


def fmt(value):
    return value.astimezone(ET).strftime(XMLTV)


def main():
    payload = json.loads(Path("manual_channels.json").read_text(encoding="utf-8"))
    document = XML.parse("epg.xml")
    root = document.getroot()
    channels = {c.findtext("display-name"): c for c in root.findall("channel")}
    ids = {c.get("id") for c in root.findall("channel")}
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=2)
    horizon = now + timedelta(days=3)
    count = 0
    for name, items in payload["channels"].items():
        events = []
        for item in items:
            start = datetime.fromisoformat(item["start"].replace("Z", "+00:00"))
            stop = datetime.fromisoformat(item["stop"].replace("Z", "+00:00"))
            if stop > window_start and start < horizon and stop > start:
                events.append((start, stop, item["title"]))
        if not events:
            continue
        channel = channels.get(name)
        if channel is None:
            cid = channel_id(name)
            if not cid or cid in ids:
                raise ValueError(f"Canal manual sin equivalencia segura: {name}")
            channel = XML.Element("channel", {"id": cid})
            aliases = [name]
            if name.startswith("Sky Sports+ "):
                number = int(name.split("+ ")[1])
                aliases += [f"SKY SPORTS+ {number}", f"SKY SPORT+ {number}", f"UK| SKY SPORT+ {number:02d}"]
            for alias in aliases:
                XML.SubElement(channel, "display-name", {"lang": "es"}).text = alias
            root.insert(len(root.findall("channel")), channel)
            channels[name] = channel
            ids.add(cid)
        if name.startswith("Amazon UK "):
            number = int(name.split()[-1])
            aliases = [f"AMAZON UK {number}", f"AMAZON PRIME UK {number}",
                       f"UK| AMAZON PRIME PPV {number:02d}"]
            if number == 1:
                aliases.append("UK| AMAZON PRIME PPV")
            present = {node.text for node in channel.findall("display-name")}
            for alias in aliases:
                if alias not in present:
                    XML.SubElement(channel, "display-name", {"lang": "es"}).text = alias
        cid = channel.get("id")
        for event_start, event_stop, title in events:
            for previous in list(root.findall("programme")):
                if previous.get("channel") != cid:
                    continue
                old_start, old_stop = parse(previous.get("start")), parse(previous.get("stop"))
                if old_stop <= event_start or old_start >= event_stop:
                    continue
                if old_start == event_start and old_stop == event_stop and previous.findtext("title") == title:
                    root.remove(previous)
                    continue
                old_title = previous.findtext("title") or ""
                if "No event scheduled" not in old_title:
                    # Una captura nueva reemplaza la emisión anterior en ese intervalo.
                    root.remove(previous)
                    continue
                root.remove(previous)
                for part_start, part_stop in ((old_start, event_start), (event_stop, old_stop)):
                    if part_stop > part_start:
                        piece = XML.SubElement(root, "programme", {
                            "start": fmt(part_start), "stop": fmt(part_stop), "channel": cid,
                        })
                        XML.SubElement(piece, "title", {"lang": "es"}).text = old_title
            programme = XML.SubElement(root, "programme", {
                "start": fmt(event_start), "stop": fmt(event_stop), "channel": cid,
            })
            XML.SubElement(programme, "title", {"lang": "es"}).text = title
            XML.SubElement(programme, "category", {"lang": "es"}).text = "Deportes"
            count += 1
    XML.indent(root, space="  ")
    temporary = Path("epg.xml.tmp")
    document.write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace("epg.xml")
    print(f"Capturas manuales aplicadas: {count} eventos")
    for name, items in payload["channels"].items():
        for item in items:
            start = datetime.fromisoformat(item["start"].replace("Z", "+00:00"))
            stop = datetime.fromisoformat(item["stop"].replace("Z", "+00:00"))
            if stop <= window_start or start >= horizon:
                continue
            cid = channels[name].get("id")
            assert any(p.get("channel") == cid and p.findtext("title") == item["title"]
                       and parse(p.get("start")) == start and parse(p.get("stop")) == stop
                       for p in root.findall("programme")), f"Captura no publicada: {name}: {item['title']}"


if __name__ == "__main__":
    main()
