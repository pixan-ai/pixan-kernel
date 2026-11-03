#!/usr/bin/env python3
"""Unit tests: /start reply patch."""
import glob
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "kernel", "bin"))
from patch_rich_message import START_TEXT, patch_start  # noqa: E402

SERVER = """bot.command('start', async ctx => {
  if (!dmCommandGate(ctx)) return
  await ctx.reply(
    `This bot bridges Telegram to a Claude Code session.\\n\\n` +
    `To pair:\\n1. DM me anything`,
  )
})

bot.command('help', async ctx => {
  await ctx.reply('help')
})
"""


class TestStartPatch(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "server.ts")
        with open(self.path, "w") as f:
            f.write(SERVER)

    def read(self):
        with open(self.path) as f:
            return f.read()

    def test_replaces_reply_only(self):
        self.assertEqual(patch_start(self.path), "patched")
        src = self.read()
        self.assertIn('await ctx.reply("%s")' % START_TEXT, src)
        self.assertNotIn("To pair", src)
        self.assertIn("if (!dmCommandGate(ctx)) return", src)
        self.assertIn("await ctx.reply('help')", src)
        self.assertEqual(len(glob.glob(self.path + ".bak-*")), 1)

    def test_idempotent(self):
        patch_start(self.path)
        once = self.read()
        self.assertEqual(patch_start(self.path), "already")
        self.assertEqual(self.read(), once)

    def test_no_anchor_and_missing(self):
        with open(self.path, "w") as f:
            f.write("bot.command('help', x)\n")
        self.assertEqual(patch_start(self.path), "no-anchor")
        self.assertEqual(patch_start(os.path.join(self.dir, "nope.ts")), "missing")


if __name__ == "__main__":
    unittest.main()
