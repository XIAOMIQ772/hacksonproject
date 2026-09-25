import argparse
import contextlib
import http.client
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import arc_fetch as arc


class PlatformContractTests(unittest.TestCase):
    def test_disconnects_retry_reads_but_never_duplicate_posts(self):
        response = io.BytesIO(b'{}')
        response.headers = {"content-type": "application/json"}
        disconnected = http.client.RemoteDisconnected("Remote end closed connection")
        with patch.object(arc.urllib.request, "urlopen", side_effect=[disconnected, response]) as request, \
                patch.object(arc.time, "sleep"):
            self.assertEqual(arc.get_json("https://example.invalid", "session"), {})
            self.assertEqual(request.call_count, 2)
        with patch.object(arc.urllib.request, "urlopen", side_effect=disconnected) as request:
            with self.assertRaises(arc.ApiError):
                arc.post_empty("https://example.invalid/start", "session")
            self.assertEqual(request.call_count, 1, "ambiguous writes require state reconciliation")

    def test_hidden_tests_do_not_abort_requirement_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            replies = [
                {"requirements_markdown": "# Task", "requirements_yaml": "id: ROOT"},
                arc.ApiError("Not found", status=404),
            ]
            with patch.object(arc, "get_json", side_effect=replies), \
                    patch.object(arc.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
                arc.fetch_task({"id": "hackathon--github", "display_id": "TASK-011"},
                               "hackathon", "session", Path(tmp), False)
            task = Path(tmp) / "011-github"
            self.assertEqual((task / "requirements.yaml").read_text(), "id: ROOT")
            self.assertIs(json.loads((task / "meta.json").read_text())["tests_available"], False)

    def test_test_download_auth_error_is_not_hidden(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(arc, "get_json", side_effect=[{}, arc.ApiError("Unauthorized", status=401)]):
            with self.assertRaises(arc.ApiError):
                arc.fetch_task({"id": "hackathon--github"}, "hackathon", "session", Path(tmp), False)

    def test_official_upload_omits_personal_key_and_uses_platform_gateway(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "agent.zip"
            archive.write_bytes(b"PK")
            args = argparse.Namespace(zip=str(archive), api_key=None, model="deepseek-v4-flash",
                                      visual_model=None, base_url=None, competition="hackathon",
                                      runtime="python", catalog="competition", name="test",
                                      credential_mode="official_evaluation", template_selections=None)
            with patch.dict(os.environ, {"OPENAI_API_KEY": "personal-secret", "OPENAI_BASE_URL": "https://personal.invalid/v1"}), \
                    patch.object(arc, "post_multipart", return_value={"submission": {"id": "s1"}}) as post, \
                    contextlib.redirect_stdout(io.StringIO()):
                arc.cmd_upload(args, "session")
            fields = post.call_args.args[1]
            self.assertEqual(fields["credential_mode"], "official_evaluation")
            self.assertNotIn("api_key", fields)
            self.assertEqual(fields["base_url"], "https://api.arc-bench.com/v1")

    def test_http_errors_preserve_status_and_server_reason(self):
        error = urllib.error.HTTPError("https://example.invalid", 400, "Bad Request", {},
                                       io.BytesIO(b'{"detail":"Official evaluation requires registration"}'))
        with patch.object(arc.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(arc.ApiError) as raised:
                arc.post_empty("https://example.invalid", "session")
        self.assertEqual(raised.exception.status, 400)
        self.assertIn("requires registration", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
