"""Transport and validation regressions for the independent source updaters."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
import claro_lineal
import globo_sp

class SourceRetryTests(unittest.TestCase):
    def response(self, body=b"verified source"):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = body
        return response

    def test_timeout_then_success(self):
        for module in (globo_sp, claro_lineal):
            with self.subTest(module=module.__name__), patch.object(module, "urlopen", side_effect=[TimeoutError(), self.response()]) as fetch, patch.object(module.time, "sleep") as sleep:
                self.assertEqual(module.fetch_page(), "verified source")
                self.assertEqual(fetch.call_count, 2)
                self.assertEqual([c.kwargs["timeout"] for c in fetch.call_args_list], [30, 45])
                sleep.assert_called_once_with(2)

    def test_read_timeout_also_retries(self):
        for module in (globo_sp, claro_lineal):
            broken = self.response()
            broken.__enter__.return_value.read.side_effect = TimeoutError()
            with self.subTest(module=module.__name__), patch.object(module, "urlopen", side_effect=[broken, self.response()]) as fetch, patch.object(module.time, "sleep"):
                self.assertEqual(module.fetch_page(), "verified source")
                self.assertEqual(fetch.call_count, 2)

    def test_retry_limit(self):
        for module in (globo_sp, claro_lineal):
            with self.subTest(module=module.__name__), patch.object(module, "urlopen", side_effect=TimeoutError()) as fetch, patch.object(module.time, "sleep"):
                with self.assertRaises(TimeoutError):
                    module.fetch_page()
                self.assertEqual(fetch.call_count, 3)

    def test_server_error_retries_but_access_denial_does_not(self):
        for module in (globo_sp, claro_lineal):
            for status, attempts in [(503, 3), (403, 1)]:
                error = HTTPError(module.GUIDE, status, "failure", {}, None)
                with self.subTest(module=module.__name__, status=status), patch.object(module, "urlopen", side_effect=error) as fetch, patch.object(module.time, "sleep"):
                    with self.assertRaises(HTTPError):
                        module.fetch_page()
                    self.assertEqual(fetch.call_count, attempts)

    def test_globo_stale_data_rejected_before_file_access(self):
        now = datetime.now(globo_sp.ET)
        shows = [(now - timedelta(hours=2), now - timedelta(hours=1), "Real title")] * 20
        with patch.object(globo_sp, "fetch", return_value=shows), patch.object(globo_sp.XML, "parse") as parse:
            with self.assertRaises(SystemExit):
                globo_sp.main()
            parse.assert_not_called()

    def test_empty_data_still_fails(self):
        with patch.object(globo_sp, "fetch", return_value=[]):
            with self.assertRaises(SystemExit):
                globo_sp.main()
        with patch.object(claro_lineal, "fetch_page", return_value=""):
            with self.assertRaises(ValueError):
                claro_lineal.schedule()

if __name__ == "__main__":
    unittest.main()
