import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
import scraper

class ScraperTests(unittest.TestCase):
    def test_overnight_is_previous_day_and_outer_table_ignored(self):
        page = """<script>utcOffset:0</script><table><tr><td>
        <table class="tbl_EPG"><tr><th>Hora Inicio</th><th>Hora Fin</th><th>Programa</th></tr>
        <tr><td class="tbl_EPG_TimesColumnOutOfSchedule"><time>23:30</time></td><td><time>01:00</time></td><td><div class="div_program_title_on_channel">SportsCenter</div></td></tr>
        <tr><td><time>01:00</time></td><td><time>02:00</time></td><td>News</td></tr>
        </table></td></tr></table>"""
        with patch.object(scraper, 'get', return_value=page):
            shows = scraper.scrape_gato_channel('https://example.test','Test')
        self.assertEqual(len(shows),2)
        self.assertEqual(shows[0][1],shows[1][0])
        self.assertEqual(shows[0][1]-shows[0][0],timedelta(hours=1,minutes=30))

    def test_normal_midnight_crossing(self):
        page = '<table class="tbl_EPG"><tr><th>Hora Inicio Hora Fin Programa</th></tr><tr><td><time>23:00</time></td><td class="tbl_EPG_TimesColumnOutOfSchedule"><time>01:00</time></td><td>Live</td></tr></table>'
        with patch.object(scraper,'get',return_value=page):
            shows=scraper.scrape_gato_channel('https://example.test','Test')
        self.assertEqual(shows[0][1]-shows[0][0],timedelta(hours=2))
        self.assertEqual(shows[0][0].date(),datetime.now(scraper.timezone_for('Test')).date())

    def test_bad_manual_item_does_not_drop_valid_channels_or_make_fillers(self):
        payload={'channels':{'A':[{'title':'Incomplete','start':'2026-11-15T10:00:00Z'}, {'title':'Valid','start':'2026-11-15T11:00:00Z','stop':'2026-11-15T12:00:00Z'}], 'B':[{'title':'No final','start':'2026-11-15T10:00:00Z','stop':None}]}}
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'manual.json';p.write_text(json.dumps(payload));r=scraper.load_manual_channels(p)
        self.assertEqual(len(r['A']),1); self.assertEqual(r['A'][0][2],'Valid');self.assertEqual(r['B'],[])

    def test_gap_validation_remains(self):
        now=datetime.now(timezone.utc)
        channels={'ESPN Sur':[(now,now+timedelta(hours=1),'a','s'),(now+timedelta(hours=3),now+timedelta(hours=4),'b','s')]}
        with self.assertRaisesRegex(SystemExit,'hueco'):
            scraper.validate_fresh_guide(channels)
if __name__ == '__main__':unittest.main()
