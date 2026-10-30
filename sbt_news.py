#!/usr/bin/env python3
"""Actualiza SBT News Brasil desde las emisiones oficiales programadas."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


SOURCE_URL = "https://www.youtube.com/@SBTNews/streams?hl=en&gl=US"
WATCH_URL = "https://www.youtube.com/watch?v={video_id}&hl=pt-BR&gl=BR"
CHANNEL_ID = "sbt.news.brasil.latam"
DISPLAY_NAMES = ("SBT News Brasil", "SBT News")
ET_ZONE = ZoneInfo("America/New_York")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
}


def extract_json(html, markers):
    decoder = json.JSONDecoder()
    for marker in markers:
        marker_index = html.find(marker)
        if marker_index < 0:
            continue
        object_index = html.find("{", marker_index + len(marker))
        if object_index < 0:
            continue
        try:
            return decoder.raw_decode(html[object_index:])[0]
        except json.JSONDecodeError:
            continue
    return None


def live_start(video_id, session):
    response = session.get(
        WATCH_URL.format(video_id=video_id),
        timeout=30,
        headers=HEADERS,
    )
    response.raise_for_status()
    player = extract_json(
        response.text,
        ("var ytInitialPlayerResponse =", "ytInitialPlayerResponse ="),
    )
    if not player:
        return None
    details = (
        player.get("microformat", {})
        .get("playerMicroformatRenderer", {})
        .get("liveBroadcastDetails", {})
    )
    raw = details.get("startTimestamp")
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def official_events():
    session = requests.Session()
    events = {}
    schedule_pattern = re.compile(
        r"Scheduled for\s+(\d{1,2}/\d{1,2}/\d{2,4},\s+\d{1,2}:\d{2}\s+[AP]M)",
        re.IGNORECASE,
    )
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(
                locale="en-US",
                timezone_id="America/New_York",
            )
            page = context.new_page()
            page.goto(SOURCE_URL, wait_until="domcontentloaded", timeout=60000)
            cards = page.locator("ytd-rich-item-renderer")
            cards.first.wait_for(state="attached", timeout=30000)
            page.wait_for_timeout(2500)

            for index in range(min(cards.count(), 80)):
                card = cards.nth(index)
                links = card.locator("a#video-title-link, a#video-title")
                if not links.count():
                    continue
                link = links.first
                title = (link.get_attribute("title") or link.inner_text()).strip()
                href = link.get_attribute("href") or ""
                video_id = parse_qs(urlparse(href).query).get("v", [""])[0]
                if not video_id or not title:
                    continue

                metadata = card.inner_text()
                match = schedule_pattern.search(metadata)
                start = None
                if match:
                    raw_start = match.group(1)
                    year_format = "%Y" if len(raw_start.split(",", 1)[0].split("/")[-1]) == 4 else "%y"
                    start = datetime.strptime(
                        raw_start,
                        f"%m/%d/{year_format}, %I:%M %p",
                    ).replace(tzinfo=ET_ZONE)
                elif "watching" in metadata.casefold():
                    try:
                        start = live_start(video_id, session)
                    except requests.RequestException:
                        start = None

                if start:
                    events[video_id] = (start.astimezone(ET_ZONE), title)

            context.close()
            browser.close()
    except PlaywrightTimeoutError as exc:
        raise RuntimeError("YouTube no cargó la agenda oficial de SBT News") from exc

    return sorted(events.values(), key=lambda item: item[0])


def fmt(value):
    return value.strftime("%Y%m%d%H%M%S %z")


def existing_coverage(root):
    now = datetime.now(timezone.utc)
    stops = []
    for programme in root.findall("programme"):
        if programme.get("channel") != CHANNEL_ID:
            continue
        try:
            stops.append(datetime.strptime(programme.get("stop", ""), "%Y%m%d%H%M%S %z"))
        except ValueError:
            continue
    return max(stops, default=now - timedelta(days=1))


def main():
    xml_path = Path("epg.xml")
    tree = ET.parse(xml_path)
    root = tree.getroot()
    now = datetime.now(timezone.utc)

    try:
        events = official_events()
    except (requests.RequestException, RuntimeError) as exc:
        if existing_coverage(root) >= now + timedelta(hours=12):
            print(f"SBT News conservó la última guía válida: {exc}")
            return
        raise SystemExit(f"No se pudo actualizar SBT News: {exc}")

    future = [
        event
        for event in events
        if event[0].astimezone(timezone.utc) >= now - timedelta(hours=8)
    ]
    print(
        f"SBT News detectó {len(events)} emisiones oficiales; "
        f"{len(future)} vigentes o futuras"
    )
    if (
        len(future) < 5
        or max(start for start, _title in future).astimezone(timezone.utc)
        < now + timedelta(hours=24)
    ):
        if existing_coverage(root) >= now + timedelta(hours=12):
            print("SBT News conservó la última guía válida: agenda oficial insuficiente")
            return
        raise SystemExit("La agenda oficial de SBT News es insuficiente")

    channels = [
        node for node in root.findall("channel") if node.get("id") == CHANNEL_ID
    ]
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

    for index, (start, title) in enumerate(future):
        if index + 1 < len(future):
            stop = future[index + 1][0]
        else:
            stop = start + timedelta(hours=4)
        if stop <= start:
            continue
        programme = ET.SubElement(
            root,
            "programme",
            {"start": fmt(start), "stop": fmt(stop), "channel": CHANNEL_ID},
        )
        clean_title = re.sub(r"^[^\wÀ-ÿ]+", "", title).strip()
        ET.SubElement(programme, "title", {"lang": "pt"}).text = clean_title
        ET.SubElement(programme, "category", {"lang": "pt"}).text = "Notícias"

    ET.indent(tree, space="  ")
    temporary = xml_path.with_suffix(".xml.tmp")
    tree.write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace(xml_path)

    coverage = max(
        datetime.strptime(programme.get("stop"), "%Y%m%d%H%M%S %z")
        for programme in root.findall("programme")
        if programme.get("channel") == CHANNEL_ID
    )
    print(
        f"SBT News Brasil: {len(future)} programas oficiales; "
        f"ET; cobertura hasta {coverage.isoformat()}"
    )


if __name__ == "__main__":
    main()
