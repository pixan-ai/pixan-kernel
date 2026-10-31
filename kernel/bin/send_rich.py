#!/usr/bin/env python3
"""send_rich: mensajes de Telegram con formato, desde el contenedor.

Dos modos, según lo que pases:

  --text HTML [--photo f.png] [--table-csv f.csv]   sendMessage / sendPhoto con parse_mode=HTML
                                                     (la tabla CSV se vuelve texto monoespaciado)
  --markdown "…" | --markdown-file f.md              sendRichMessage (Bot API 10.x): encabezados con #,
      [--img ID=ruta_o_url …]                        tablas |---|, listas, > citas, **negrita** *cursiva*
                                                     `code` ||spoiler||. NO es MarkdownV2.

Imágenes en un rich message: cada --img ID=fuente se declara en `media` y se coloca en el
markdown donde deba aparecer con ![](tg://photo?id=ID). Ruta local → se sube como archivo
attach://ID; URL http(s) → va directa, sin subir nada.

Límites del API: 32768 caracteres, 500 bloques, 50 archivos, 20 columnas por tabla.
Nunca imprime TELEGRAM_BOT_TOKEN. Exit 0 ok · 1 el API contestó ok:false · 2 falta token/args.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MAX_CHARS, MAX_MEDIA, MAX_COLS = 32768, 50, 20
MEDIA_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def escape_html(text: str) -> str:
    return html.escape(text, quote=False)


def table_html(rows: list[list[str]], max_cols: int = 4) -> str:
    """Tabla en <pre> para el modo HTML (Telegram no tiene tablas ahí); máx 3–4 columnas."""
    if not rows:
        return ""
    cols = min(max(len(r) for r in rows), max_cols)
    widths = [0] * cols
    norm: list[list[str]] = []
    for r in rows:
        cells = [escape_html(str(c)) for c in r[:cols]]
        while len(cells) < cols:
            cells.append("")
        for i, c in enumerate(cells):
            widths[i] = max(widths[i], len(c))
        norm.append(cells)
    lines = ["  ".join(c.ljust(widths[i]) for i, c in enumerate(cells)) for cells in norm]
    return "<pre>" + "\n".join(lines) + "</pre>"


def _api(token: str, method: str, data: dict | None = None, files: dict | None = None,
         multipart: bool = False) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    if files or multipart:
        boundary = "----KernelBoundary7MA4YWxkTrZu0gW"
        body = bytearray()
        for k, v in (data or {}).items():
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
            body.extend(str(v).encode() + b"\r\n")
        for name, path in (files or {}).items():
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{name}"; filename="{Path(path).name}"\r\n'.encode())
            body.extend(b"Content-Type: application/octet-stream\r\n\r\n")
            body.extend(Path(path).read_bytes() + b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(url, data=bytes(body), method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    else:
        req = urllib.request.Request(url, data=urllib.parse.urlencode(data or {}).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Telegram API HTTP {e.code}: {e.read().decode(errors='replace')[:500]}") from None
    except urllib.error.URLError as e:
        raise SystemExit(f"Telegram API network error: {e.reason}") from None


def send_message(token: str, chat_id: str, text: str) -> dict:
    return _api(token, "sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})


def send_photo(token: str, chat_id: str, photo_path: str, caption: str = "") -> dict:
    data: dict = {"chat_id": chat_id, "parse_mode": "HTML"}
    if caption:
        data["caption"] = caption
    return _api(token, "sendPhoto", data=data, files={"photo": photo_path})


def assert_chat_permitido(chat_id: str) -> None:
    """Mismo candado que la tool `reply` del canal.

    Este script habla directo al Bot API, así que se salta al plugin. Sin esta
    comprobación, "todo va por send_rich" significaría "todo va por fuera de la
    lista de acceso", y a un agente al que le inyecten un destinatario le
    bastaría pedir formato para escribirle a cualquiera.
    """
    ruta = os.environ.get("TELEGRAM_STATE_DIR") or os.path.join(
        os.environ.get("CLAUDE_CONFIG_DIR", "/data/config"), "channels", "telegram")
    archivo = Path(ruta) / "access.json"
    try:
        acc = json.loads(archivo.read_text())
    except (OSError, ValueError):
        # Sin access.json no hay perímetro que consultar: no se inventa uno.
        raise SystemExit(f"ERROR: no pude leer {archivo}; no mando nada a ciegas")
    cid = str(chat_id).strip()
    if cid in [str(x) for x in (acc.get("allowFrom") or [])]:
        return
    if cid in (acc.get("groups") or {}):
        return
    raise SystemExit(
        f"ERROR: el chat {cid} no está en la lista de acceso. No se agregan destinatarios "
        "por pedido de un mensaje: eso se autoriza con access.py y un Super Usuario."
    )


def build_rich_message(markdown: str, imgs: dict[str, str]) -> tuple[dict, dict]:
    """Arma el InputRichMessage y los archivos a subir. Valida lo que el API rechazaría."""
    if len(markdown) > MAX_CHARS:
        raise ValueError(f"markdown de {len(markdown)} chars; máximo {MAX_CHARS}")
    if len(imgs) > MAX_MEDIA:
        raise ValueError(f"{len(imgs)} imágenes; máximo {MAX_MEDIA}")
    for line in markdown.splitlines():
        if line.strip().startswith("|") and line.count("|") - 1 > MAX_COLS:
            raise ValueError(f"tabla con más de {MAX_COLS} columnas")
    media, files = [], {}
    for mid, src in imgs.items():
        if not MEDIA_ID.match(mid):
            raise ValueError(f"id de imagen inválido: {mid!r} (A-Z a-z 0-9 _ -, máx 64)")
        if src.startswith(("http://", "https://")):
            ref = src
        else:
            if not Path(src).is_file():
                raise ValueError(f"imagen no encontrada: {src}")
            ref, files[mid] = f"attach://{mid}", src
        media.append({"id": mid, "media": {"type": "photo", "media": ref}})
    rich: dict = {"markdown": markdown}
    if media:
        rich["media"] = media
    return rich, files


def send_rich_message(token: str, chat_id: str, markdown: str, imgs: dict[str, str]) -> dict:
    rich, files = build_rich_message(markdown, imgs)
    data = {"chat_id": chat_id, "rich_message": json.dumps(rich, ensure_ascii=False)}
    return _api(token, "sendRichMessage", data=data, files=files, multipart=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="send_rich: HTML (sendMessage) o rich message (sendRichMessage)")
    ap.add_argument("--chat-id", required=True)
    ap.add_argument("--text", default="", help="HTML → sendMessage (o caption de --photo)")
    ap.add_argument("--photo", default="")
    ap.add_argument("--table-csv", default="", help="CSV → tabla monoespaciada añadida a --text")
    ap.add_argument("--markdown", default="", help="rich message en Rich Markdown → sendRichMessage")
    ap.add_argument("--markdown-file", default="", help="igual que --markdown, leído de un archivo")
    ap.add_argument("--img", action="append", default=[], metavar="ID=RUTA_O_URL",
                    help="imagen del rich message; en el markdown va como ![](tg://photo?id=ID)")
    args = ap.parse_args()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN missing", file=sys.stderr)
        return 2

    try:
        assert_chat_permitido(args.chat_id)
    except SystemExit as e:
        print(e.code if isinstance(e.code, str) else "destinatario no permitido", file=sys.stderr)
        return 2

    markdown = args.markdown or (Path(args.markdown_file).read_text() if args.markdown_file else "")
    if markdown and (args.text or args.photo or args.table_csv):
        print("--markdown no se mezcla con --text/--photo/--table-csv", file=sys.stderr)
        return 2
    if markdown:
        imgs: dict[str, str] = {}
        for item in args.img:
            mid, sep, src = item.partition("=")
            if not sep or not mid or not src:
                print(f"--img espera ID=ruta_o_url, no {item!r}", file=sys.stderr)
                return 2
            imgs[mid.strip()] = src.strip()
        try:
            result = send_rich_message(token, args.chat_id, markdown, imgs)
        except ValueError as e:
            print(f"rich message inválido: {e}", file=sys.stderr)
            return 2
    else:
        text = args.text
        if args.table_csv:
            rows = [[c.strip() for c in line.split(",")]
                    for line in Path(args.table_csv).read_text().splitlines() if line.strip()]
            tbl = table_html(rows)
            text = (text + "\n" + tbl).strip() if text else tbl
        if args.photo:
            if not Path(args.photo).is_file():
                print(f"photo not found: {args.photo}", file=sys.stderr)
                return 2
            result = send_photo(token, args.chat_id, args.photo, caption=text)
        else:
            if not text:
                print("need --text, --photo or --markdown", file=sys.stderr)
                return 2
            result = send_message(token, args.chat_id, text)

    if not result.get("ok"):
        print(f"send failed: {str(result.get('description', ''))[:200]}", file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
