#!/usr/bin/env python3
"""Read Televen's dated Venezuela schedule when its official EPG is unavailable."""
import html
import re
import time
from datetime import datetime, timedelta
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

GUIDE = "https://americatvguide.com/es/venezuela/c/televen-tv"
NAME = "Televen (Venezuela)"
VENEZUELA = ZoneInfo("America/Caracas")
HEADING = re.compile(r"<h5>Hoy - (\d{1,2})/(\d{1,2})/(\d{2})")
ITEM = re.compile(r'href="/es/venezuela/c/televen-tv/(\d{6})/[^\"]+" title="([^\"]+)"')


def fetch_page():
    for attempt, timeout in enumerate((30, 45, 60)):
        request = Request(GUIDE, headers={"User-Agent": "Mozilla/5.0 (latam-sports-epg)"})
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except HTTPError as exc:
            if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (URLError, TimeoutError, ConnectionError, IncompleteRead):
            if attempt == 2:
                raise
        print(f"Televen: fallo temporal de fuente; reintento {attempt + 2}/3")
        time.sleep(2 * (attempt + 1))


def parse_schedule(page, now=None):
    now = now or datetime.now(VENEZUELA)
    if now.tzinfo is None:
        raise ValueError("La hora de referencia requiere zona horaria")
    now = now.astimezone(VENEZUELA)
    match = HEADING.search(page)
    if not match:
        raise ValueError("Televen: la fuente no publicó la fecha de hoy")
    day, month, year = map(int, match.groups())
    guide_date = datetime(2000 + year, month, day).date()
    if guide_date != now.date():
        raise ValueError(f"Televen: guía desactualizada ({guide_date})")
    starts = {}
    # The next-day guide ends at midnight of day +2. Use real dates, not
    # replace(day=...), so month/year boundaries remain correct.
    dates = [guide_date + timedelta(days=shift) for shift in (-1, 0, 1, 2)]
    for code, raw_title in ITEM.findall(page):
        date_day, hour, minute = int(code[:2]), int(code[2:4]), int(code[4:6])
        on_date = next((date for date in dates if date.day == date_day), None)
        if on_date is None:
            continue
        title = re.sub(r"^\d{2}:\d{2}\s+", "", html.unescape(raw_title)).strip()
        if not title:
            continue
        start = datetime(on_date.year, on_date.month, on_date.day, hour, minute, tzinfo=VENEZUELA)
        if start in starts and starts[start] != title:
            raise ValueError(f"Televen: títulos contradictorios a las {start}")
        starts[start] = title
    ordered = sorted(starts.items())
    shows = [(start, stop, title, GUIDE)
             for (start, title), (stop, _next_title) in zip(ordered, ordered[1:])
             if stop > start]
    if len(shows) < 8 or max(stop for _start, stop, _title, _source in shows) < now + timedelta(hours=6):
        raise ValueError("Televen: guía incompleta o cobertura menor de seis horas")
    return {NAME: shows}


def fetch():
    """Return only sourced intervals; propagate failures for caller fallback policy."""
    return parse_schedule(fetch_page())
