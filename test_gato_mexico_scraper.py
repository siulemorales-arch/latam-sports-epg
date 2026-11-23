"""Cover the isolated Mexico source paths and the actual workflow validator."""
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone, UTC
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from xml.etree import ElementTree as XML

import requests

import gato_mexico_scraper as gato


ROOT = Path(__file__).resolve().parent
STAMP = "%Y%m%d%H%M%S %z"
FOX = tuple(cid for cid, _name, _slug in gato.CHANNELS[1:])


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "epg.xml"
        self.now = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)
        tree = XML.Element("tv")
        for cid, name, _slug in gato.CHANNELS:
            channel = XML.SubElement(tree, "channel", id=cid)
            XML.SubElement(channel, "display-name").text = name
            programme = XML.SubElement(tree, "programme", channel=cid)
            XML.SubElement(programme, "title").text = "Previously verified"
        XML.ElementTree(tree).write(self.path)

    def update(self, side_effect, channels=gato.CHANNELS):
        out = StringIO()
        with patch.object(gato, "fetch_channel", side_effect=side_effect), redirect_stdout(out):
            gato.update(self.path, channels, self.now)
        xml = XML.parse(self.path).getroot()
        self.assertEqual([c.get("id") for c in xml.findall("channel")],
                         [row[0] for row in gato.CHANNELS])
        return {p.get("channel"): p.findtext("title") for p in xml.findall("programme")}, out.getvalue()

    def test_each_fox_failure_is_independent_of_working_tvc_and_other_fox(self):
        current = [(self.now, self.now + timedelta(hours=25), "TVC real title")]
        other_fox = [(self.now, self.now + timedelta(hours=26), "Fox real title")]
        programmes, warnings = self.update([current, [], requests.HTTPError("403"), other_fox])
        self.assertEqual(programmes[gato.TVC_ID], "TVC real title")
        self.assertEqual(programmes[FOX[0]], "Previously verified")
        self.assertEqual(programmes[FOX[1]], "Previously verified")
        self.assertEqual(programmes[FOX[2]], "Fox real title")
        self.assertIn("::warning::Fox Sports México 1", warnings)
        self.assertIn("::warning::Fox Sports México 2", warnings)

    def test_all_stale_or_empty_fox_leave_xml_unchanged(self):
        before = self.path.read_bytes()
        stale = [(self.now - timedelta(days=2), self.now, "Stale")]
        _programmes, warnings = self.update([stale, [], requests.Timeout()], gato.CHANNELS[1:])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(warnings.count("::warning::"), 3)

    def test_tvc_empty_remains_a_hard_error(self):
        before = self.path.read_bytes()
        with self.assertRaisesRegex(SystemExit, "TVC Deportes"):
            self.update([[]], gato.CHANNELS[:1])
        self.assertEqual(self.path.read_bytes(), before)


class SourceDateTests(unittest.TestCase):
    def test_accepts_only_verified_requested_page_and_date(self):
        slug = "tvc_deportes"
        day = date(2026, 11, 23)
        url = f"{gato.GUIDE_ROOT}/{slug}/{day}"
        table = """<table><tr><th>Hora Inicio</th><th>Hora Fin</th><th>Programa</th></tr>
        <tr><td><time>22:00</time></td><td><time>23:00</time></td><td>Real title</td></tr>
        </table>"""
        for marker, status, final_url, expected in [
            (f'<time datetime="{day}"></time>', 200, url, ["Real title"]),
            ('<time datetime="2026-11-22"></time>', 200, url, []),
            ('<time>22:00</time>', 200, url, []),
            (f'<time datetime="{day}"></time>', 302, url, []),
            (f'<time datetime="{day}"></time>', 200, f"{gato.GUIDE_ROOT}/otro/{day}", []),
        ]:
            with self.subTest(marker=marker, status=status, url=final_url):
                response = Mock(url=final_url, status_code=status, text=marker + table)
                with patch.object(gato.requests, "get", return_value=response) as fetch:
                    self.assertEqual([item[2] for item in gato.fetch_day(slug, day)], expected)
                    self.assertFalse(fetch.call_args.kwargs["allow_redirects"])


class WorkflowValidationTests(unittest.TestCase):
    def test_actual_inline_validator_allows_fox_gaps_but_not_tvc_sbt_or_id_loss(self):
        body = (ROOT / ".github/workflows/update.yml").read_text()
        body = body.split("      - name: Validar XMLTV", 1)[1]
        body = body.split("          python - <<'PY'\n", 1)[1].split("          PY\n", 1)[0]
        code = compile("\n".join(line[10:] for line in body.splitlines()),
                       "workflow XMLTV validator", "exec")
        now = datetime.now(UTC)
        tree = XML.parse(ROOT / "epg.xml")
        root = tree.getroot()
        for item in list(root.findall("programme")):
            cid = item.get("channel")
            if cid in FOX[:2]:
                root.remove(item)
                continue
            if cid in FOX:
                item.set("stop", (now - timedelta(hours=1)).strftime(STAMP))
                continue
            # Test the validator, not live provider timing. Leave the fixed
            # historical Claro event's start intact as required by the workflow.
            item.set("stop", (now + timedelta(days=2)).strftime(STAMP))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "epg.xml"
            previous = Path(directory) / "epg.previous.xml"
            previous.write_bytes((ROOT / "epg.xml").read_bytes())
            real_parse = XML.parse

            def parse(relative):
                return real_parse(Path(directory) / relative)

            with patch.object(XML, "parse", side_effect=parse):
                tree.write(path)
                out = StringIO()
                with redirect_stdout(out):
                    exec(code, {})
                self.assertEqual(out.getvalue().count("::warning::fox."), 3)
                broken_tvc = [item for item in root.findall("programme") if item.get("channel") == gato.TVC_ID]
                for item in broken_tvc:
                    item.set("stop", (now - timedelta(hours=1)).strftime(STAMP))
                tree.write(path)
                with self.assertRaisesRegex(AssertionError, "TVC Deportes"):
                    exec(code, {})
                for item in broken_tvc:
                    item.set("stop", (now + timedelta(days=2)).strftime(STAMP))
                for item in root.findall("programme"):
                    if item.get("channel") == "sbt.news.brasil.latam":
                        item.set("stop", (now - timedelta(hours=1)).strftime(STAMP))
                tree.write(path)
                with self.assertRaisesRegex(AssertionError, "SBT News"):
                    exec(code, {})
                lost = next(c for c in root.findall("channel") if c.get("id") == FOX[0])
                root.remove(lost)
                tree.write(path)
                with self.assertRaisesRegex(AssertionError, "perdió canales"):
                    exec(code, {})
