#!/usr/bin/env python3
"""Add provider display names for Sky Sports+ event feeds 11–13."""

from pathlib import Path
from xml.etree import ElementTree as ET

xml_path = Path("epg.xml")
tree = ET.parse(xml_path)
root = tree.getroot()
for number in range(11, 14):
    channel_id = f"sky.sports.{number}.latam"
    channel = root.find(f"./channel[@id='{channel_id}']")
    if channel is None:
        raise SystemExit(f"Missing Sky Sports+ channel: {channel_id}")
    current = {name.text for name in channel.findall("display-name")}
    for alias in (
        f"SKY SPORTS+ {number}",
        f"SKY SPORT+ {number}",
        f"UK| SKY SPORT+ {number:02d}",
    ):
        if alias not in current:
            ET.SubElement(channel, "display-name", {"lang": "es"}).text = alias
ET.indent(root, space="  ")
temp_path = xml_path.with_suffix(".xml.tmp")
tree.write(temp_path, encoding="utf-8", xml_declaration=True)
temp_path.replace(xml_path)
print("Sky Sports+ 11–13: provider aliases verified")
