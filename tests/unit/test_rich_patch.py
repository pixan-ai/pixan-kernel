#!/usr/bin/env python3
"""Unit tests: rich message patch for the Telegram bridge."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "kernel", "bin"))
from patch_rich_message import MARK, STAMP_MARK, patch, patch_all, patch_stamp  # noqa: E402

# Minimal shape of the real server.ts: typed handlers, then the declaration we
# use as the anchor.
SERVER = """bot.on('message:text', async ctx => {
  await handleInbound(ctx, ctx.message.text, undefined)
})

type AttachmentMeta = {
  kind: string
}

async function handleInbound(ctx: Context, text: string): Promise<void> {
  if (permMatch) {
    void mcp.notification({
      method: 'notifications/claude/channel/permission',
      params: {},
    })
    return
  }
  mcp.notification({
    method: 'notifications/claude/channel',
    params: {
      content: text,
    },
  })
}
"""


class TestRichMessagePatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _server(self, body=SERVER, rel="cache/claude-plugins-official/telegram/0.0.7"):
        d = os.path.join(self.root, rel)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "server.ts")
        with open(p, "w") as f:
            f.write(body)
        return p

    def test_patch_inserts_handler_before_anchor(self):
        p = self._server()
        self.assertEqual(patch(p), "patched")
        out = open(p).read()
        self.assertIn(MARK, out)
        self.assertIn("rich_message", out)
        self.assertIn("richToText", out)
        # The handler must go BEFORE the anchor, not at the end of the file.
        self.assertLess(out.index(MARK), out.index("type AttachmentMeta = {"))

    def test_patch_is_idempotent(self):
        p = self._server()
        self.assertEqual(patch(p), "patched")
        first = open(p).read()
        self.assertEqual(patch(p), "already")
        self.assertEqual(open(p).read(), first)
        self.assertEqual(first.count(MARK), 1)

    def test_patch_keeps_a_backup(self):
        p = self._server()
        patch(p)
        d = os.path.dirname(p)
        baks = [f for f in os.listdir(d) if "prerich" in f]
        self.assertEqual(len(baks), 1)
        self.assertEqual(open(os.path.join(d, baks[0])).read(), SERVER)

    def test_patch_refuses_without_anchor(self):
        p = self._server(body="bot.on('message:text', () => {})\n")
        self.assertEqual(patch(p), "no-anchor")
        self.assertNotIn(MARK, open(p).read())

    def test_patch_reports_missing_file(self):
        self.assertEqual(patch(os.path.join(self.root, "nope.ts")), "missing")

    def test_patch_all_covers_every_version(self):
        self._server(rel="cache/claude-plugins-official/telegram/0.0.6")
        self._server(rel="cache/claude-plugins-official/telegram/0.0.7")
        results = patch_all(os.path.join(self.root, "cache"))
        self.assertEqual([s for _, s in results],
                         ["rich patched, stamp patched"] * 2)

    def test_patch_all_on_empty_cache_is_not_an_error(self):
        self.assertEqual(patch_all(os.path.join(self.root, "cache")), [])



class TestInboundStampPatch(unittest.TestCase):
    """Time of the last delivered message: the heartbeat derives `queue=` from it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "server.ts")
        with open(self.path, "w") as f:
            f.write(SERVER)

    def tearDown(self):
        self.tmp.cleanup()

    def test_stamp_goes_right_before_delivery_to_the_session(self):
        self.assertEqual(patch_stamp(self.path), "patched")
        out = open(self.path).read()
        at = out.index(STAMP_MARK)
        self.assertIn("last-inbound", out)
        self.assertLess(at, out.index("method: 'notifications/claude/channel',"))
        # Not in the permission shortcut: that one does not deliver a message to the session.
        self.assertGreater(at, out.index("channel/permission"))

    def test_a_failed_write_never_breaks_delivery(self):
        patch_stamp(self.path)
        linea = [l for l in open(self.path).read().splitlines() if "last-inbound" in l]
        self.assertEqual(len(linea), 1)
        self.assertIn("try {", linea[0])
        self.assertIn("catch {}", linea[0])

    def test_stamp_is_idempotent_and_independent_of_rich(self):
        self.assertEqual(patch(self.path), "patched")
        self.assertEqual(patch_stamp(self.path), "patched")
        once = open(self.path).read()
        self.assertEqual(patch_stamp(self.path), "already")
        self.assertEqual(patch(self.path), "already")
        self.assertEqual(open(self.path).read(), once)

    def test_stamp_refuses_without_anchor(self):
        with open(self.path, "w") as f:
            f.write("type AttachmentMeta = {\n}\n")
        self.assertEqual(patch_stamp(self.path), "no-anchor")


if __name__ == "__main__":
    unittest.main()
