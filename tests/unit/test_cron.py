"""cron: a scheduled task runs once per slot, survives restarts, and never floods the chat."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "kernel", "bin"))
import cron  # noqa: E402

TZ = cron.TZ


def at(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = os.path.join(self.tmp.name, "config")
        os.makedirs(cfg)
        with open(os.path.join(cfg, "settings.json"), "w") as f:
            json.dump({"enabledPlugins": {"telegram@claude-plugins-official": True},
                       "channelsEnabled": True, "hooks": {"SessionStart": []},
                       "permissions": {"deny": ["Read(**/.env)"]}}, f)
        self.env = mock.patch.dict(os.environ, {
            "CLAUDE_CONFIG_DIR": cfg,
            "CRON_FILE": os.path.join(cfg, "cron.json"),
            "CRON_CLAUDE_CONFIG_DIR": os.path.join(self.tmp.name, "cron-config"),
            "AGENT_WORKSPACE": self.tmp.name,
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def add_daily(self, task_id="purchase-order", hhmm="09:00", created="2026-09-13 12:00", **kw):
        h, m = hhmm.split(":")
        return cron.add(task_id, "123", "Alice", "Follow up on PO-4512",
                        schedule=f"{int(m)} {int(h)} * * *", now=at(created), **kw)


class TestSchedule(Base):
    def test_weekdays_at_nine(self):
        p = cron.parse_schedule("0 9 * * 1-5")
        self.assertTrue(cron.matches(p, at("2026-09-14 09:00")))   # Monday
        self.assertFalse(cron.matches(p, at("2026-09-13 09:00")))  # Sunday
        self.assertFalse(cron.matches(p, at("2026-09-14 09:01")))

    def test_sunday_is_zero_or_seven(self):
        self.assertEqual(cron.parse_schedule("0 9 * * 7")["dows"], {0})

    def test_next_run_skips_to_the_next_valid_day(self):
        p = cron.parse_schedule("30 8 * * 1")
        self.assertEqual(cron.next_run(p, at("2026-09-14 09:00")), at("2026-09-21 08:30"))

    def test_rejects_garbage_and_too_frequent(self):
        for bad in ("0 9 * *", "61 9 * * *", "a b c d e", "0 0 31 2 *"):
            with self.assertRaises(ValueError, msg=bad):
                cron.validate_schedule(bad, at("2026-09-13 12:00"))
        with self.assertRaises(ValueError):
            cron.validate_schedule("*/5 * * * *", at("2026-09-13 12:00"))
        cron.validate_schedule("*/15 * * * *", at("2026-09-13 12:00"))


class TestAdd(Base):
    def test_validates_input_and_limits(self):
        with self.assertRaises(ValueError):
            cron.add("X", "123", "Alice", "hello", schedule="0 9 * * *")      # bad id
        with self.assertRaises(ValueError):
            cron.add("ok-id", "abc", "Alice", "hello", schedule="0 9 * * *")  # bad chat
        with self.assertRaises(ValueError):
            cron.add("ok-id", "123", "Alice", "hello")                         # no schedule nor at
        with mock.patch.dict(os.environ, {"CRON_MAX_TASKS": "1"}):
            self.add_daily("one")
            with self.assertRaises(ValueError):
                self.add_daily("two")

    def test_duplicate_id_is_refused(self):
        self.add_daily()
        with self.assertRaises(ValueError):
            self.add_daily()


class TestDue(Base):
    def test_runs_once_per_slot(self):
        self.add_daily(hhmm="09:00")
        launched = []
        launch = lambda tid: launched.append(tid) or 999999  # noqa: E731
        with mock.patch.object(cron, "running_pid", return_value=None):
            cron.tick(at("2026-09-14 08:59"), launch)
            cron.tick(at("2026-09-14 09:00"), launch)
            cron.tick(at("2026-09-14 09:00"), launch)
            cron.tick(at("2026-09-14 09:30"), launch)
            cron.tick(at("2026-09-15 09:00"), launch)
        self.assertEqual(launched, ["purchase-order", "purchase-order"])

    def test_a_missed_slot_runs_on_return_within_grace_only(self):
        self.add_daily(hhmm="05:00")
        tasks = cron.load()
        self.assertEqual([t["id"] for _, t in cron.due(tasks, at("2026-09-14 06:30"))], ["purchase-order"])
        self.assertEqual(cron.due(tasks, at("2026-09-14 07:30")), [])

    def test_a_task_created_after_todays_slot_waits_for_tomorrow(self):
        self.add_daily(hhmm="09:00", created="2026-09-14 09:30")
        self.assertEqual(cron.due(cron.load(), at("2026-09-14 09:31")), [])
        self.assertEqual(len(cron.due(cron.load(), at("2026-09-15 09:00"))), 1)

    def test_nothing_launches_while_a_job_is_running(self):
        self.add_daily()
        launched = []
        with mock.patch.object(cron, "running_pid", return_value=4242):
            cron.tick(at("2026-09-14 09:00"), lambda tid: launched.append(tid) or 1)
        self.assertEqual(launched, [])
        self.assertEqual(len(cron.due(cron.load(), at("2026-09-14 09:00"))), 1)  # still pending

    def test_until_and_missed_one_shot_close_the_task(self):
        self.add_daily("with-end", until="2026-09-14")
        cron.add("one-shot", "123", "Bob", "remind me", at="2026-09-14 10:00", now=at("2026-09-13 12:00"))
        tasks = cron.load()
        closed = cron.expire(tasks, at("2026-09-15 13:00"))
        self.assertEqual(sorted(closed), ["one-shot", "with-end"])
        self.assertFalse(tasks["with-end"]["enabled"])

    def test_paused_tasks_do_not_run(self):
        self.add_daily()
        cron.set_enabled("purchase-order", False)
        self.assertEqual(cron.due(cron.load(), at("2026-09-14 09:00")), [])


class TestRun(Base):
    def fake_claude(self, stdout="", code=0, exc=None):
        calls = []

        def runner(cmd, **kw):
            calls.append((cmd, kw))
            if exc:
                raise exc
            return subprocess.CompletedProcess(cmd, code, stdout=stdout, stderr="boom" if code else "")
        return runner, calls

    def sender(self):
        sent = []
        return (lambda chat, text: sent.append((chat, text)) or (True, "ok")), sent

    def test_delivers_the_answer_through_the_runner_not_the_model(self):
        self.add_daily()
        runner, calls = self.fake_claude("PO-4512 is still in transit.")
        send, sent = self.sender()
        self.assertEqual(cron.run("purchase-order", at("2026-09-14 09:00"), runner, send), 0)
        self.assertEqual(sent, [("123", "PO-4512 is still in transit.")])
        cmd, kw = calls[0]
        self.assertEqual(cmd[:2], ["claude", "-p"])
        self.assertIn("Follow up on PO-4512", cmd[-1])
        task = cron.load()["purchase-order"]
        self.assertEqual((task["runs"], task["last_status"]), (1, "delivered"))

    def test_job_runs_without_the_telegram_plugin(self):
        self.add_daily()
        runner, calls = self.fake_claude("ok")
        send, _ = self.sender()
        cron.run("purchase-order", at("2026-09-14 09:00"), runner, send)
        job_cfg = calls[0][1]["env"]["CLAUDE_CONFIG_DIR"]
        with open(os.path.join(job_cfg, "settings.json")) as f:
            settings = json.load(f)
        self.assertEqual(settings, {})  # hooks and deny rules come from managed settings

    def test_quiet_answer_sends_nothing(self):
        self.add_daily()
        runner, _ = self.fake_claude(cron.QUIET)
        send, sent = self.sender()
        cron.run("purchase-order", at("2026-09-14 09:00"), runner, send)
        self.assertEqual(sent, [])
        self.assertEqual(cron.load()["purchase-order"]["last_status"], "no update")

    def test_the_agent_can_close_its_own_task(self):
        self.add_daily()
        runner, _ = self.fake_claude(f"PO-4512 was delivered.\n{cron.STOP}")
        send, sent = self.sender()
        cron.run("purchase-order", at("2026-09-14 09:00"), runner, send)
        self.assertEqual(sent, [("123", "PO-4512 was delivered.")])
        self.assertFalse(cron.load()["purchase-order"]["enabled"])

    def test_failure_tells_the_chat_instead_of_going_silent(self):
        self.add_daily()
        runner, _ = self.fake_claude(exc=subprocess.TimeoutExpired("claude", 900))
        send, sent = self.sender()
        self.assertEqual(cron.run("purchase-order", at("2026-09-14 09:00"), runner, send), 1)
        self.assertEqual(len(sent), 1)
        self.assertIn("purchase-order", sent[0][1])
        self.assertTrue(cron.load()["purchase-order"]["enabled"])  # a failure does not cancel it

    def test_previous_report_is_given_to_the_next_run(self):
        self.add_daily()
        send, _ = self.sender()
        cron.run("purchase-order", at("2026-09-14 09:00"), self.fake_claude("In transit.")[0], send)
        runner, calls = self.fake_claude(cron.QUIET)
        cron.run("purchase-order", at("2026-09-15 09:00"), runner, send)
        self.assertIn("In transit.", calls[0][0][-1])

    def test_one_shot_disables_after_running(self):
        cron.add("one-shot", "123", "Bob", "remind me", at="2026-09-14 10:00", now=at("2026-09-13 12:00"))
        send, _ = self.sender()
        cron.run("one-shot", at("2026-09-14 10:00"), self.fake_claude("Reminder")[0], send)
        self.assertFalse(cron.load()["one-shot"]["enabled"])


class TestJobAuth(Base):
    """A failed run names the credential the entrypoint resolved (AUTH_VIA)."""

    def test_failure_names_the_credential_in_use(self):
        self.add_daily()
        sent = []
        runner = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="401")  # noqa: E731
        with mock.patch.dict(os.environ, {"AUTH_VIA": "CLAUDE_CODE_OAUTH_TOKEN"}):
            cron.run("purchase-order", at("2026-09-14 09:00"), runner,
                     lambda chat, text: sent.append(text) or (True, "ok"))
        self.assertIn("if this persists, check that CLAUDE_CODE_OAUTH_TOKEN is valid", sent[0])
        self.assertNotIn("tok)", sent[0])


class TestWiring(unittest.TestCase):
    ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def test_the_heartbeat_ticks_the_scheduler(self):
        with open(os.path.join(self.ROOT, "kernel", "entrypoint.sh"), encoding="utf-8") as f:
            self.assertIn("/bin/cron.py\" tick", f.read())

    def test_agents_are_told_they_do_have_cron(self):
        skill = os.path.join(self.ROOT, "kernel", "seed", "workspace", ".claude", "skills", "scheduled-tasks", "SKILL.md")
        with open(skill, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("cron.py add", text)
        self.assertIn(cron.QUIET, text)
        self.assertIn(cron.STOP, text)


if __name__ == "__main__":
    unittest.main()
