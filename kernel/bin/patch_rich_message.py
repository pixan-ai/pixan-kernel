#!/usr/bin/env python3
"""Parcha el puente de Telegram para que entienda rich messages (Bot API 10.1).

Un mensaje enriquecido llega en `message.rich_message`, no en `message.text`.
El plugin registra handlers por campo (`message:text`, `:photo`, `:voice`…) y
la version de grammY que trae es anterior al campo, asi que ningun filtro lo
reclama y el update se descarta **sin error y sin rastro**.

Solo los agentes mandan `sendRichMessage` — las personas escriben texto plano —
asi que el unico trafico que se rompe es el de agente a agente, en silencio.

Segundo parche, en el mismo pase: el puente deja la hora del ultimo mensaje
que le entrego a la sesion en `$TELEGRAM_STATE_DIR/last-inbound`. El latido la
compara con el transcript: si entro un mensaje y la sesion no escribio nada
despues, esta en cola de verdad. Leerlo de la pantalla no sirve, porque el
marcador `← telegram ·` se queda pintado despues de atendido.

Idempotente: cada parche reconoce su propia marca y no vuelve a insertar.
"""
import glob
import os
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
STAMP_MARK = "// --- kernel: hora del ultimo mensaje entregado"
STAMP_PATCH = (
    "  // --- kernel: hora del ultimo mensaje entregado a la sesion. El latido la\n"
    "  // compara con el transcript para saber si un mensaje entro y nadie lo tomo.\n"
    "  try { writeFileSync(join(STATE_DIR, 'last-inbound'), String(Date.now())) } catch {}\n"
)


def _insert(path, anchor, mark, text, tag):
    """Inserta `text` antes de `anchor`. Devuelve patched/already/no-anchor/missing."""
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
    """Parche de rich messages sobre un server.ts."""
    return _insert(path, ANCHOR, MARK, PATCH, "rich")


def patch_stamp(path):
    """Parche de la hora del ultimo mensaje entregado sobre un server.ts."""
    return _insert(path, STAMP_ANCHOR, STAMP_MARK, STAMP_PATCH, "stamp")


def patch_all(cache_root):
    """Parcha todas las versiones del plugin telegram bajo un cache de plugins."""
    pattern = os.path.join(cache_root, "*", "telegram", "*", "server.ts")
    return [(p, "rich %s, stamp %s" % (patch(p), patch_stamp(p)))
            for p in sorted(glob.glob(pattern))]


def main(argv):
    cache_root = argv[1] if len(argv) > 1 else os.path.join(
        os.environ.get("CLAUDE_CONFIG_DIR", "/data/config"), "plugins", "cache"
    )
    results = patch_all(cache_root)
    if not results:
        # Primer arranque: el plugin se descarga al iniciar claude, asi que aun
        # no hay nada que parchar. Entra en el siguiente arranque.
        print("sin plugin en cache (%s) — parche pendiente al proximo arranque" % cache_root)
        return 0
    for path, status in results:
        print("%s: %s" % (path, status))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
