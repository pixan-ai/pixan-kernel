#!/usr/bin/env python3
"""What the agent sent through cron comes back into its context, without writing into the session."""
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "kernel" / "bin"))
import cron  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.td = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.env = unittest.mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.td)})
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("KERNEL_CRON_JOB", None)
        self.now = datetime(2026, 9, 16, 9, 0, tzinfo=cron.TZ)

    def record(self, task_id="follow-up", text="Morning follow-up: 3 orders in transit",
               minutes=10, chat="-100000001"):
        cron.record_delivery(task_id, chat, text, self.now - timedelta(minutes=minutes))


class TestDeliveryLog(Base):
    def test_a_delivery_is_recorded(self):
        self.record()
        lines = (self.td / cron.DELIVERIES).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["id"], "follow-up")

    def test_long_text_is_clipped(self):
        self.record(text="x" * 5000)
        self.assertLessEqual(len(json.loads((self.td / cron.DELIVERIES).read_text())["text"]),
                             cron.CLIP)

    def test_does_not_grow_without_limit(self):
        for i in range(cron.DELIVERIES_MAX + 20):
            self.record(task_id=f"t{i}")
        self.assertEqual(len((self.td / cron.DELIVERIES).read_text().splitlines()),
                         cron.DELIVERIES_MAX)

    def test_unwritable_log_does_not_break_delivery(self):
        with unittest.mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/does/not/exist"}):
            cron.record_delivery("x", "1", "hello", self.now)   # must not raise


class TestContext(Base):
    def test_reports_what_the_session_did_not_see(self):
        self.record()
        text = cron.context(self.now)
        self.assertIn("scheduled tasks", text)
        self.assertIn("Morning follow-up", text)
        self.assertIn("-100000001", text)

    def test_says_it_was_already_delivered(self):
        """Without this, the agent may resend the report thinking it was asked to."""
        self.record()
        self.assertIn("do not send it again", cron.context(self.now))

    def test_each_delivery_is_reported_once(self):
        self.record()
        self.assertTrue(cron.context(self.now))
        self.assertEqual(cron.context(self.now), "")

    def test_a_new_delivery_is_reported(self):
        self.record(minutes=30)
        cron.context(self.now)
        self.record(task_id="evening", minutes=2)
        self.assertIn("evening", cron.context(self.now))

    def test_old_deliveries_are_not_news(self):
        self.record(minutes=60 * (cron.CONTEXT_HOURS + 2))
        self.assertEqual(cron.context(self.now), "")

    def test_does_not_flood_the_context(self):
        for i in range(cron.CONTEXT_MAX + 6):
            self.record(task_id=f"t{i}", minutes=i + 1)
        text = cron.context(self.now)
        self.assertEqual(text.count("· to chat"), cron.CONTEXT_MAX)

    def test_no_log_says_nothing(self):
        self.assertEqual(cron.context(self.now), "")

    def test_silent_inside_the_task_itself(self):
        """The cron's `claude -p` inherits the hooks; there this makes no sense."""
        self.record()
        with unittest.mock.patch.dict(os.environ, {"KERNEL_CRON_JOB": "1"}):
            self.assertEqual(cron.context(self.now), "")


class TestWiring(unittest.TestCase):
    def test_hook_is_in_managed_settings(self):
        d = json.loads((ROOT / "kernel/managed-settings.json").read_text(encoding="utf-8"))
        args = [h.get("args") for b in d["hooks"]["UserPromptSubmit"] for h in b["hooks"]]
        self.assertIn(["/opt/kernel/bin/cron.py", "context"], args)

    def test_managed_settings_are_baked_root_owned(self):
        """Hooks live in managed settings: the image installs them where users cannot edit."""
        docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("/etc/claude-code/managed-settings.json", docker)

    def test_task_runs_marked_as_such(self):
        self.assertIn('KERNEL_CRON_JOB="1"', (ROOT / "kernel/bin/cron.py").read_text(encoding="utf-8"))

    def test_context_types_nothing(self):
        """Rule: context is added, nothing is typed into the session."""
        source = (ROOT / "kernel/bin/cron.py").read_text(encoding="utf-8")
        self.assertNotIn("send-keys", source)


if __name__ == "__main__":
    unittest.main()
