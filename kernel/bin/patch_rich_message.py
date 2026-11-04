#!/usr/bin/env python3
"""Patches the Telegram bridge so it understands rich messages (Bot API 10.1).

A rich message arrives in `message.rich_message`, not in `message.text`.
The plugin registers handlers per field (`message:text`, `:photo`, `:voice`...)
and its bundled grammY predates the field, so no filter claims it and the
update is dropped **without an error and without a trace**.

Only agents send `sendRichMessage` (people type plain text), so the only
traffic that breaks is agent-to-agent, silently.

Second patch, in the same pass: the bridge writes the time of the last message
it delivered to the session to `$TELEGRAM_STATE_DIR/last-inbound`. The
heartbeat compares it with the transcript: if a message came in and the session
wrote nothing afterwards, it is really queued. Reading the screen does not
work, because the `← telegram ·` marker stays painted after it was handled.

Third patch: `/start` answers "Hello World, I am a Pixan agent." instead of the
plugin's pairing instructions (the kernel already paired the owner).

Idempotent: each patch recognizes its own mark and never inserts twice.
"""

import glob
import json
import os
import re
import shutil
import sys
from datetime import datetime

ANCHOR = "type AttachmentMeta = {"
MARK = "// --- Bot API 10.1 rich messages"

PATCH = '''// --- Bot API 10.1 rich messages ------------------------------------------
// A rich message arrives in `message.rich_message`, not `message.text`, so no
// `message:*` filter matches and the update is dropped without a trace — the
// bundled grammY predates the field. Registered after every typed handler:
// those end their own chain, so only unclaimed updates reach this one.
function richToText(node: unknown): string {
  if (node == null) return ''
  if (typeof node === 'string') return node
  if (Array.isArray(node)) return node.map(richToText).filter(Boolean).join('\\n')
  if (typeof node === 'object') {
    const o = node as Record<string, unknown>
    // Block variants nest differently and new ones keep being added, so read
    // the shallowest text we find instead of enumerating 20-odd block types.
    if (typeof o.text === 'string') return o.text
    if (typeof o.caption === 'string') return o.caption
    const parts: string[] = []
    for (const v of Object.values(o)) {
      if (v !== null && typeof v === 'object') {
        const s = richToText(v)
        if (s) parts.push(s)
      }
    }
    return parts.join('\\n')
  }
  return ''
}

bot.on('message', async ctx => {
  const rich = (ctx.message as unknown as { rich_message?: unknown }).rich_message
  if (!rich) return
  const text = richToText(rich).trim()
  await handleInbound(ctx, text || '(rich message)', undefined)
})

'''


STAMP_ANCHOR = "  mcp.notification({\n    method: 'notifications/claude/channel',\n"
STAMP_MARK = "// --- kernel: time of the last message delivered"
STAMP_PATCH = (
    "  // --- kernel: time of the last message delivered to the session. The heartbeat\n"
    "  // compares it with the transcript to tell whether a message came in and nobody took it.\n"
    "  try { writeFileSync(join(STATE_DIR, 'last-inbound'), String(Date.now())) } catch {}\n"
)


def _insert(path, anchor, mark, text, tag):
    """Insert `text` before `anchor`. Returns patched/already/no-anchor/missing."""
    if not os.path.exists(path):
        return "missing"
    with open(path, encoding="utf-8") as f:
        src = f.read()
    if mark in src:
        return "already"
    if anchor not in src:
        return "no-anchor"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, "%s.bak-%s-pre%s" % (path, stamp, tag))
    with open(path, "w", encoding="utf-8") as f:
        f.write(src.replace(anchor, text + anchor, 1))
    return "patched"


def patch(path):
    """Rich-message patch on a server.ts."""
    return _insert(path, ANCHOR, MARK, PATCH, "rich")


def patch_stamp(path):
    """Last-delivered-message timestamp patch on a server.ts."""
    return _insert(path, STAMP_ANCHOR, STAMP_MARK, STAMP_PATCH, "stamp")


DEFAULT_START_TEXT = "Hello World, I am a Pixan agent."
# The plugin's /start handler: `await ctx.reply(<pairing instructions>)`. The agent is
# already paired with its owner by the kernel, so those instructions would only confuse.
START_RE = re.compile(r"(bot\.command\('start', async ctx => \{\n\s*if \(!dmCommandGate\(ctx\)\) return\n"
                      r"\s*await ctx\.reply\()(.*?)(\)\n\}\))", re.S)


def patch_start(path, text=None):
    """/start answers `text` (default: env START_TEXT, else DEFAULT_START_TEXT).
    Returns patched/already/no-anchor/missing."""
    if not os.path.exists(path):
        return "missing"
    with open(path, encoding="utf-8") as f:
        src = f.read()
    m = START_RE.search(src)
    if not m:
        return "no-anchor"
    new = json.dumps(text or os.environ.get("START_TEXT", "").strip() or DEFAULT_START_TEXT)
    if m.group(2).strip() == new:
        return "already"
    shutil.copy2(path, "%s.bak-%s-prestart" % (path, datetime.now().strftime("%Y%m%d-%H%M%S")))
    with open(path, "w", encoding="utf-8") as f:
        f.write(src[:m.start(2)] + new + src[m.end(2):])
    return "patched"


def patch_all(cache_root):
    """Patch every version of the telegram plugin under a plugin cache."""
    pattern = os.path.join(cache_root, "*", "telegram", "*", "server.ts")
    return [(p, "rich %s, stamp %s, start %s" % (patch(p), patch_stamp(p), patch_start(p)))
            for p in sorted(glob.glob(pattern))]


def main(argv):
    cache_root = argv[1] if len(argv) > 1 else os.path.join(
        os.environ.get("CLAUDE_CONFIG_DIR", "/data/config"), "plugins", "cache"
    )
    results = patch_all(cache_root)
    if not results:
        # The entrypoint exits before this when the baked plugin is missing.
        print("no plugin in cache (%s), nothing patched" % cache_root)
        return 0
    for path, status in results:
        print("%s: %s" % (path, status))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
