#!/usr/bin/env python3
"""Conserva IDs y alias anteriores aunque una fuente omita señales."""
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as XML


def main():
    previous = XML.parse("epg.previous.xml").getroot()
    document = XML.parse("epg.xml")
    root = document.getroot()
    current = {c.get("id"): c for c in root.findall("channel")}
    restored = set()
    for channel in previous.findall("channel"):
        cid = channel.get("id")
        if cid not in current:
            copy = deepcopy(channel)
            root.insert(len(root.findall("channel")), copy)
            current[cid] = copy
            restored.add(cid)
        else:
            names = {n.text for n in current[cid].findall("display-name")}
            for name in channel.findall("display-name"):
                if name.text not in names:
                    current[cid].append(deepcopy(name))
                    names.add(name.text)
    # Los atributos opcionales de XMLTV se preservan tal como los dio la fuente.
    for programme in previous.findall("programme"):
        if programme.get("channel") in restored:
            root.append(deepcopy(programme))
    assert {c.get("id") for c in previous.findall("channel")} <= set(current)
    XML.indent(root, space="  ")
    temporary = Path("epg.xml.tmp")
    document.write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace("epg.xml")
    print(f"Canales anteriores conservados: {len(current)}; restaurados: {len(restored)}")


if __name__ == "__main__":
    main()
