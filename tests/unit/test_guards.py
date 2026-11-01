"""Seed guards and hooks: SSRF, send_rich, clock, hard_deny, hooks in settings."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "kernel" / "bin"


class TestSsrfGuard(unittest.TestCase):
    def _check(self, url: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "ssrf_guard.py"), "--check", url],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_allow_public_https(self):
        # Use a hostname that resolves public (or fail-open only if public IP)
        proc = self._check("https://example.com/")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_deny_localhost(self):
        for url in (
            "http://localhost/x",
            "http://127.0.0.1/",
            "https://[::1]/",
            "http://169.254.169.254/latest/meta-data/",
            "http://192.168.1.1/",
            "http://10.0.0.5/",
            "http://172.16.0.1/",
            "file:///etc/passwd",
            "ftp://example.com/",
        ):
            with self.subTest(url=url):
                proc = self._check(url)
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)

    def test_pretooluse_deny_json(self):
        payload = json.dumps(
            {"hook_event_name": "PreToolUse", "tool_input": {"url": "http://127.0.0.1/x"}}
        )
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "ssrf_guard.py")],
            input=payload,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 2)
        data = json.loads(proc.stdout)
        self.assertEqual(
            data["hookSpecificOutput"]["permissionDecision"], "deny"
        )


class TestSendRichHelpers(unittest.TestCase):
    def test_escape_and_table(self):
        sys.path.insert(0, str(SCRIPTS))
        import send_rich  # noqa: E402

        self.assertEqual(send_rich.escape_html("a<b>&c"), "a&lt;b&gt;&amp;c")
        tbl = send_rich.table_html([["A", "B"], ["1", "2"]])
        self.assertIn("<pre>", tbl)
        self.assertIn("A", tbl)
        self.assertIn("1", tbl)
        # max cols
        wide = send_rich.table_html([["a", "b", "c", "d", "e"]], max_cols=4)
        self.assertNotIn(">e<", wide.replace(" ", ""))
        self.assertIn("d", wide)


class TestSettingsP1(unittest.TestCase):
    def test_webfetch_ssrf_hook(self):
        settings = json.loads((ROOT / "kernel/managed-settings.json").read_text())
        pre = settings["hooks"]["PreToolUse"]
        found = False
        for block in pre:
            if block.get("matcher") == "WebFetch":
                cmds = [h.get("args", [None])[0] for h in block.get("hooks", [])]
                self.assertTrue(any("ssrf_guard.py" in str(a) for a in cmds))
                found = True
        self.assertTrue(found, "WebFetch PreToolUse SSRF hook missing")


class TestClockHook(unittest.TestCase):
    def test_user_prompt_injects_local_time(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "clock.py")],
            input='{"hook_event_name":"UserPromptSubmit"}',
            text=True,
            capture_output=True,
            check=True,
        )
        data = json.loads(proc.stdout)
        ctx = data["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn(os.environ.get("TZ") or "America/Mexico_City", ctx)
        self.assertIn("Do not use UTC timestamps", ctx)
        self.assertTrue("CST" in ctx or "CDT" in ctx)

    def test_session_start_event_name(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "clock.py")],
            input='{"hook_event_name":"SessionStart","source":"startup"}',
            text=True,
            capture_output=True,
            check=True,
        )
        data = json.loads(proc.stdout)
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "SessionStart")


class TestHardDenySeed(unittest.TestCase):
    def test_automode_hard_deny_and_hooks(self):
        settings = json.loads((ROOT / "kernel/managed-settings.json").read_text())
        hd = settings["autoMode"]["hard_deny"]
        self.assertIn("$defaults", hd)
        self.assertTrue(any("exfiltrat" in x.lower() or "secret" in x.lower() for x in hd))
        hooks = settings["hooks"]
        self.assertIn("SessionStart", hooks)
        self.assertIn("UserPromptSubmit", hooks)
        deny = settings["permissions"]["deny"]
        self.assertTrue(any("rm -rf /" in x for x in deny))


class TestSendRichMessage(unittest.TestCase):
    """Capacidad nueva: sendRichMessage (Bot API 10.x). Lo viejo (--text) sigue igual."""

    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))
        import send_rich
        self.sr = send_rich
        self.calls: list[tuple] = []
        self._orig = send_rich._api
        send_rich._api = lambda token, method, data=None, files=None, multipart=False: (
            self.calls.append((method, data, files, multipart)) or {"ok": True}
        )
        self.td = tempfile.TemporaryDirectory()
        self.png = Path(self.td.name) / "graf.png"
        self.png.write_bytes(b"\x89PNG fake")
        # The test chat must be allowed: send_rich checks the access list
        # just like the channel's `reply` tool.
        tg = Path(self.td.name) / "channels/telegram"
        tg.mkdir(parents=True)
        (tg / "access.json").write_text(json.dumps({"allowFrom": ["42"], "groups": {}}))
        self.state_dir = str(tg)

    def tearDown(self):
        self.sr._api = self._orig
        self.td.cleanup()

    def _run(self, *argv, token="t"):
        env = {k: v for k, v in os.environ.items() if k != "TELEGRAM_BOT_TOKEN"}
        env["TELEGRAM_STATE_DIR"] = self.state_dir
        if token:
            env["TELEGRAM_BOT_TOKEN"] = token
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
             unittest.mock.patch.object(sys, "argv", ["send_rich.py", "--chat-id", "42", *argv]):
            return self.sr.main()

    def test_payload_se_arma_bien(self):
        rich, files = self.sr.build_rich_message("# Hola\n![](tg://photo?id=graf)", {"graf": str(self.png)})
        self.assertEqual(rich["markdown"], "# Hola\n![](tg://photo?id=graf)")
        self.assertEqual(rich["media"], [{"id": "graf", "media": {"type": "photo", "media": "attach://graf"}}])
        self.assertEqual(files, {"graf": str(self.png)})

    def test_img_local_va_como_attach_y_campo_multipart(self):
        rc = self._run("--markdown", "![](tg://photo?id=graf)", "--img", f"graf={self.png}")
        self.assertEqual(rc, 0)
        method, data, files, multipart = self.calls[0]
        self.assertEqual(method, "sendRichMessage")
        self.assertTrue(multipart)
        self.assertEqual(json.loads(data["rich_message"])["media"][0]["media"]["media"], "attach://graf")
        self.assertEqual(files, {"graf": str(self.png)})

    def test_img_url_no_manda_archivo(self):
        rc = self._run("--markdown", "x", "--img", "graf=https://example.com/a.png")
        self.assertEqual(rc, 0)
        _, data, files, _ = self.calls[0]
        self.assertEqual(files, {})
        self.assertEqual(json.loads(data["rich_message"])["media"][0]["media"]["media"], "https://example.com/a.png")

    def test_markdown_file(self):
        md = Path(self.td.name) / "m.md"
        md.write_text("| a | b |\n|---|---|\n| 1 | 2 |")
        self.assertEqual(self._run("--markdown-file", str(md)), 0)
        self.assertEqual(self.calls[0][0], "sendRichMessage")

    def test_text_sigue_usando_send_message(self):
        self.assertEqual(self._run("--text", "<b>hola</b>"), 0)
        method, data, files, multipart = self.calls[0]
        self.assertEqual(method, "sendMessage")
        self.assertEqual(data["parse_mode"], "HTML")
        self.assertFalse(multipart)

    def test_sin_token_exit_2(self):
        self.assertEqual(self._run("--markdown", "x", token=""), 2)
        self.assertEqual(self.calls, [])

    def test_limites_y_errores_de_uso_exit_2(self):
        self.assertEqual(self._run("--markdown", "x", "--img", "mal id=/nope"), 2)
        self.assertEqual(self._run("--markdown", "x", "--img", "graf=/no/existe.png"), 2)
        self.assertEqual(self._run("--markdown", "|" + " a |" * 21), 2)
        self.assertEqual(self._run("--markdown", "x", "--text", "y"), 2)
        self.assertEqual(self.calls, [])

    def test_api_ok_false_exit_1(self):
        self.sr._api = lambda *a, **k: {"ok": False, "description": "Bad Request"}
        self.assertEqual(self._run("--markdown", "x"), 1)


class TestDestinatarioPermitido(unittest.TestCase):
    """send_rich talks to the Bot API directly: without this lock it bypasses the access list."""

    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))
        import send_rich
        self.sr = send_rich
        self.td = tempfile.TemporaryDirectory()
        tg = Path(self.td.name) / "channels/telegram"
        tg.mkdir(parents=True)
        (tg / "access.json").write_text(json.dumps({
            "dmPolicy": "pairing", "allowFrom": ["123456789"],
            "groups": {"-100123": {"requireMention": False}},
        }))
        self.env = {"TELEGRAM_STATE_DIR": str(tg)}

    def tearDown(self):
        self.td.cleanup()

    def test_permite_a_quien_esta_en_allowfrom(self):
        with unittest.mock.patch.dict(os.environ, self.env):
            self.sr.assert_chat_allowed("123456789")

    def test_permite_un_grupo_dado_de_alta(self):
        with unittest.mock.patch.dict(os.environ, self.env):
            self.sr.assert_chat_allowed("-100123")

    def test_rechaza_a_un_desconocido(self):
        with unittest.mock.patch.dict(os.environ, self.env):
            with self.assertRaises(SystemExit) as e:
                self.sr.assert_chat_allowed("999999")
        self.assertIn("is not in the access list", str(e.exception))

    def test_sin_access_json_no_manda_a_ciegas(self):
        with unittest.mock.patch.dict(os.environ, {"TELEGRAM_STATE_DIR": "/no/existe"}):
            with self.assertRaises(SystemExit):
                self.sr.assert_chat_allowed("123456789")

    def test_el_cli_corta_con_exit_2(self):
        env = {**os.environ, **self.env, "TELEGRAM_BOT_TOKEN": "t"}
        r = subprocess.run([sys.executable, str(SCRIPTS / "send_rich.py"),
                            "--chat-id", "999999", "--markdown", "x"],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("access list", r.stderr)


if __name__ == "__main__":
    unittest.main()
