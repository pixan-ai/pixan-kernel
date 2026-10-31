#!/usr/bin/env python3
"""send_rich: formatted Telegram messages, from inside the container.

Two modes, depending on what you pass:

  --text HTML [--photo f.png] [--table-csv f.csv]   sendMessage / sendPhoto with parse_mode=HTML
                                                     (the CSV table becomes monospaced text)
  --markdown "..." | --markdown-file f.md            sendRichMessage (Bot API 10.x): # headings,
      [--img ID=path_or_url ...]                     |---| tables, lists, > quotes, **bold** *italic*
                                                     `code` ||spoiler||. This is NOT MarkdownV2.

Images in a rich message: each --img ID=source is declared in `media` and placed in the
markdown where it should appear with ![](tg://photo?id=ID). Local path -> uploaded as file
attach://ID; http(s) URL -> sent as is, nothing uploaded.

API limits: 32768 characters, 500 blocks, 50 files, 20 columns per table.
Never prints TELEGRAM_BOT_TOKEN. Exit 0 ok, 1 the API answered ok:false, 2 missing token/args.
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
    """Table in <pre> for HTML mode (Telegram has no tables there); max 3-4 columns."""
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


def assert_chat_allowed(chat_id: str) -> None:
    """Same lock as the channel's `reply` tool.

    This script talks to the Bot API directly, so it bypasses the plugin. Without
    this check, "everything goes through send_rich" would mean "everything goes
    around the access list", and an agent fed an injected recipient would only
    need to ask for formatting to write to anyone.
    """
    state_dir = os.environ.get("TELEGRAM_STATE_DIR") or os.path.join(
        os.environ.get("CLAUDE_CONFIG_DIR", "/data/config"), "channels", "telegram")
    access_file = Path(state_dir) / "access.json"
    try:
        acc = json.loads(access_file.read_text())
    except (OSError, ValueError):
        # Without access.json there is no perimeter to check: do not invent one.
        raise SystemExit(f"ERROR: could not read {access_file}; not sending anything blindly")
    cid = str(chat_id).strip()
    if cid in [str(x) for x in (acc.get("allowFrom") or [])]:
        return
    if cid in (acc.get("groups") or {}):
        return
    raise SystemExit(
        f"ERROR: chat {cid} is not in the access list. Recipients are never added "
        "because a message asks for it: only the owner adds them to access.json."
    )


def build_rich_message(markdown: str, imgs: dict[str, str]) -> tuple[dict, dict]:
    """Build the InputRichMessage and the files to upload. Validates what the API would reject."""
    if len(markdown) > MAX_CHARS:
        raise ValueError(f"markdown is {len(markdown)} chars; max {MAX_CHARS}")
    if len(imgs) > MAX_MEDIA:
        raise ValueError(f"{len(imgs)} images; max {MAX_MEDIA}")
    for line in markdown.splitlines():
        if line.strip().startswith("|") and line.count("|") - 1 > MAX_COLS:
            raise ValueError(f"table with more than {MAX_COLS} columns")
    media, files = [], {}
    for mid, src in imgs.items():
        if not MEDIA_ID.match(mid):
            raise ValueError(f"invalid image id: {mid!r} (A-Z a-z 0-9 _ -, max 64)")
        if src.startswith(("http://", "https://")):
            ref = src
        else:
            if not Path(src).is_file():
                raise ValueError(f"image not found: {src}")
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
    ap = argparse.ArgumentParser(description="send_rich: HTML (sendMessage) or rich message (sendRichMessage)")
    ap.add_argument("--chat-id", required=True)
    ap.add_argument("--text", default="", help="HTML -> sendMessage (or caption for --photo)")
    ap.add_argument("--photo", default="")
    ap.add_argument("--table-csv", default="", help="CSV -> monospaced table appended to --text")
    ap.add_argument("--markdown", default="", help="rich message in Rich Markdown -> sendRichMessage")
    ap.add_argument("--markdown-file", default="", help="same as --markdown, read from a file")
    ap.add_argument("--img", action="append", default=[], metavar="ID=PATH_OR_URL",
                    help="rich message image; place it in the markdown as ![](tg://photo?id=ID)")
    args = ap.parse_args()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN missing", file=sys.stderr)
        return 2

    try:
        assert_chat_allowed(args.chat_id)
    except SystemExit as e:
        print(e.code if isinstance(e.code, str) else "recipient not allowed", file=sys.stderr)
        return 2

    markdown = args.markdown or (Path(args.markdown_file).read_text() if args.markdown_file else "")
    if markdown and (args.text or args.photo or args.table_csv):
        print("--markdown cannot be combined with --text/--photo/--table-csv", file=sys.stderr)
        return 2
    if markdown:
        imgs: dict[str, str] = {}
        for item in args.img:
            mid, sep, src = item.partition("=")
            if not sep or not mid or not src:
                print(f"--img expects ID=path_or_url, not {item!r}", file=sys.stderr)
                return 2
            imgs[mid.strip()] = src.strip()
        try:
            result = send_rich_message(token, args.chat_id, markdown, imgs)
        except ValueError as e:
            print(f"invalid rich message: {e}", file=sys.stderr)
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
