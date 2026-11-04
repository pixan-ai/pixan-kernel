#!/usr/bin/env python3
"""Unit tests: encrypted backup (needs the `age` binary; skipped without it)."""
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "kernel", "bin"))
import backup  # noqa: E402

SECRET = "sk-ant-api03-" + "Z" * 40
HAS_AGE = bool(shutil.which("age") and shutil.which("age-keygen"))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data = os.path.join(self.tmp, "data")
        files = {
            "workspace/MEMORY.md": "remember: %s\n" % SECRET,
            "workspace/SOUL.md": "soul\n",
            "workspace/.env": "X=1\n",
            "workspace/notes.md.bak-1": "old\n",
            "workspace/blob.bin": b"\xff\xfe" + SECRET.encode(),
            "config/.credentials.json": "{}",
            "config/.claude.json": "{}",
            "config/cron.json": "[]",
            "config/projects/p/s.jsonl": '{"t":"hi"}\n',
            "config/plugins/x.json": "{}",
            "config/channels/telegram/access.json": "{}",
            "backups/old.tar.age": "x",
        }
        for rel, body in files.items():
            p = os.path.join(self.data, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(body if isinstance(body, bytes) else body.encode())
        self.env = mock.patch.dict(os.environ, {"DATA_DIR": self.data, "AGENT_NAME": "t"}, clear=False)
        self.env.start()
        for k in [k for k in os.environ if k.startswith("BACKUP_")]:
            os.environ.pop(k)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp)


class TestContents(Base):
    def test_includes_excludes_and_redacts(self):
        raw, n_files, n_red = backup.build_tar()
        with tarfile.open(fileobj=io.BytesIO(raw)) as t:
            names = set(t.getnames())
            memory = t.extractfile("workspace/MEMORY.md").read().decode()
        self.assertEqual(names, {"workspace/MEMORY.md", "workspace/SOUL.md", "config/cron.json",
                                 "config/projects/p/s.jsonl", "config/channels/telegram/access.json"})
        self.assertNotIn(SECRET, memory)
        self.assertIn("[REDACTED]", memory)
        self.assertEqual(n_red, 2)  # one redacted text file, one binary left out
        self.assertNotIn(SECRET.encode(), raw)

    def test_off_without_recipient(self):
        self.assertIn("off", backup.backup())
        self.assertEqual(backup.main(["tick"]), 0)

    def test_due(self):
        self.assertTrue(backup.due(1e9))
        os.makedirs(os.path.dirname(backup.stamp_path()), exist_ok=True)
        backup.stamp_path().write_text("1000")
        self.assertFalse(backup.due(1000 + 3599))
        self.assertTrue(backup.due(1000 + 3600))

    def test_r2_needs_all_four(self):
        os.environ.update(BACKUP_R2_ENDPOINT="https://x.r2.cloudflarestorage.com", BACKUP_R2_BUCKET="b",
                          BACKUP_R2_ACCESS_KEY_ID="id")
        self.assertIsNone(backup.r2_settings())
        os.environ["BACKUP_R2_SECRET_ACCESS_KEY"] = "sec"
        self.assertIsNotNone(backup.r2_settings())

    def test_r2_credentials_on_stdin_only(self):
        seen = {}

        def runner(cmd, input=None, capture_output=None):
            seen["cmd"], seen["input"] = cmd, input
            return subprocess.CompletedProcess(cmd, 0, b"", b"")
        cfg = {"BACKUP_R2_ENDPOINT": "https://e", "BACKUP_R2_BUCKET": "b",
               "BACKUP_R2_ACCESS_KEY_ID": "KEYID123", "BACKUP_R2_SECRET_ACCESS_KEY": "SECRET456"}
        backup.upload_r2(backup.Path("/x/t-1.tar.age"), cfg, runner)
        self.assertNotIn("SECRET456", " ".join(seen["cmd"]))
        self.assertIn(b"KEYID123:SECRET456", seen["input"])
        self.assertEqual(seen["cmd"][-1], "https://e/b/t/t-1.tar.age")


class TestLargeBinary(Base):
    def test_unscannable_binary_left_out(self):
        big = os.path.join(self.data, "workspace", "big.bin")
        with open(big, "wb") as f:
            f.write(b"\xff" * (backup.MAX_SCAN + 1024 * 1024) + SECRET.encode())
        raw, _, _ = backup.build_tar()
        with tarfile.open(fileobj=io.BytesIO(raw)) as t:
            self.assertNotIn("workspace/big.bin", t.getnames())
        self.assertNotIn(SECRET.encode(), raw)


@unittest.skipUnless(HAS_AGE, "age not installed")
class TestEncrypted(Base):
    def test_roundtrip_and_prune(self):
        key = os.path.join(self.tmp, "key.txt")
        subprocess.run(["age-keygen", "-o", key], check=True, capture_output=True)
        pub = subprocess.run(["age-keygen", "-y", key], check=True, capture_output=True, text=True).stdout.strip()
        os.environ.update(BACKUP_AGE_RECIPIENT=pub, BACKUP_KEEP="2")
        for i in range(3):
            self.assertTrue(backup.backup(now=1_700_000_000 + i).startswith("OK"))
        folder = os.path.join(self.data, "backups")
        kept = sorted(f for f in os.listdir(folder) if f.startswith("t-"))
        self.assertEqual(len(kept), 2)
        enc = open(os.path.join(folder, kept[-1]), "rb").read()
        self.assertNotIn(b"soul", enc)
        plain = subprocess.run(["age", "-d", "-i", key], input=enc, check=True, capture_output=True).stdout
        with tarfile.open(fileobj=io.BytesIO(plain)) as t:
            self.assertEqual(t.extractfile("workspace/SOUL.md").read(), b"soul\n")
        self.assertFalse(backup.due(1_700_000_002 + 10))

    def test_r2_failure_no_retry_storm(self):
        key = os.path.join(self.tmp, "key.txt")
        subprocess.run(["age-keygen", "-o", key], check=True, capture_output=True)
        pub = subprocess.run(["age-keygen", "-y", key], check=True, capture_output=True, text=True).stdout.strip()
        os.environ.update(BACKUP_AGE_RECIPIENT=pub, BACKUP_KEEP="3", BACKUP_R2_ENDPOINT="https://e",
                          BACKUP_R2_BUCKET="b", BACKUP_R2_ACCESS_KEY_ID="id", BACKUP_R2_SECRET_ACCESS_KEY="sec")

        def runner(cmd, input=None, capture_output=None):
            if cmd[0] == "curl":
                return subprocess.CompletedProcess(cmd, 6, b"", b"")
            return subprocess.run(cmd, input=input, capture_output=True)
        folder = os.path.join(self.data, "backups")
        os.makedirs(folder, exist_ok=True)
        for old in ("t-20000101-000000.tar.age", "t-20000101-010000.tar.age"):
            open(os.path.join(folder, old), "w").close()
        now = 1_700_000_000
        with self.assertRaises(backup.R2Error):
            backup.backup(now=now, runner=runner)
        self.assertFalse(backup.due(now + 30))  # next heartbeat: no new backup
        kept = sorted(f for f in os.listdir(folder) if f.startswith("t-"))
        self.assertEqual(len(kept), 3)
        self.assertIn("t-20000101-000000.tar.age", kept)

    def test_bad_recipient_fails_cleanly(self):
        os.environ["BACKUP_AGE_RECIPIENT"] = "not-a-key"
        self.assertEqual(backup.main(["now"]), 1)
        self.assertEqual([f for f in os.listdir(os.path.join(self.data, "backups")) if f.startswith("t-")], [])


if __name__ == "__main__":
    unittest.main()
