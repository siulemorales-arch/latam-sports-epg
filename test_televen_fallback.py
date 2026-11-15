import unittest
from datetime import datetime,timedelta
from unittest.mock import MagicMock,patch
from urllib.error import HTTPError
import televen_fallback as source


def fixture(day, count=10):
    rows=[f'<h5>Hoy - {day:%d/%m/%y}</h5>']
    start=day.replace(hour=12)
    for i in range(count+1):
        at=start+timedelta(hours=4*i)
        rows.append(f'<a href="/es/venezuela/c/televen-tv/{at:%d%H%M}/show" title="{at:%H:%M} Show {i}">x</a>')
    return ''.join(rows)


class TelevenTests(unittest.TestCase):
    def test_month_boundary_and_day_plus_two(self):
        now=datetime(2026,11,30,12,tzinfo=source.VENEZUELA)
        result=source.parse_schedule(fixture(now),now)[source.NAME]
        self.assertEqual(len(result),10)
        self.assertEqual(result[-1][1],datetime(2026,12,2,4,tzinfo=source.VENEZUELA))
        self.assertTrue(all(b>a for a,b,_,_ in result))
        self.assertTrue(all(s==source.GUIDE for _,_,_,s in result))

    def test_year_boundary(self):
        now=datetime(2026,12,31,12,tzinfo=source.VENEZUELA)
        result=source.parse_schedule(fixture(now),now)[source.NAME]
        self.assertEqual(result[-1][1].year,2027)

    def test_stale_date_rejected(self):
        now=datetime(2026,11,15,12,tzinfo=source.VENEZUELA)
        with self.assertRaisesRegex(ValueError,'desactualizada'):
            source.parse_schedule(fixture(now-timedelta(days=1)),now)

    def test_duplicates_removed(self):
        now=datetime(2026,11,15,12,tzinfo=source.VENEZUELA)
        page=fixture(now)
        self.assertEqual(len(source.parse_schedule(page+page,now)[source.NAME]),10)

    def test_short_or_expired_coverage_rejected(self):
        now=datetime(2026,11,15,12,tzinfo=source.VENEZUELA)
        with self.assertRaises(ValueError): source.parse_schedule(fixture(now,3),now)
        page=fixture(now.replace(hour=0))
        # Eight compact intervals, ending earlier on the current date.
        page='<h5>Hoy - 15/11/26</h5>'+''.join(f'<a href="/es/venezuela/c/televen-tv/15{i:02d}00/x" title="X">x</a>' for i in range(10))
        with self.assertRaises(ValueError): source.parse_schedule(page,now)

    def test_transport_retry_and_403(self):
        response=MagicMock();response.__enter__.return_value.read.return_value=b'page'
        with patch.object(source,'urlopen',side_effect=[TimeoutError(),response]) as fetch,patch.object(source.time,'sleep'):
            self.assertEqual(source.fetch_page(),'page');self.assertEqual(fetch.call_count,2)
        error=HTTPError(source.GUIDE,403,'Forbidden',{},None)
        with patch.object(source,'urlopen',side_effect=error) as fetch:
            with self.assertRaises(HTTPError):source.fetch_page()
            self.assertEqual(fetch.call_count,1)

if __name__=='__main__':unittest.main()
