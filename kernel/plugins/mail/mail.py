#!/usr/bin/env python3
"""Read and send the agent's mail (IMAP/SMTP, stdlib only).

  mail.py info
  mail.py ls [--limit N=20] [--unread]
  mail.py get <uid>
  mail.py send --to ADDR [--cc ADDR] --subject STR (--body STR | --body-file PATH)
               [--attach PATH ...] --i-confirm-send

Env: MAIL_ADDRESS + MAIL_APP_PASSWORD (an app password; spaces are stripped).
Optional: MAIL_IMAP_HOST (default imap.gmail.com), MAIL_SMTP_HOST (default smtp.gmail.com),
MAIL_TO_ALLOWLIST (CSV): when set, send only accepts those recipients.
Exit 0 ok · 1 protocol/auth error · 2 missing config or args
"""
from __future__ import annotations

import argparse
import email
import email.policy
import imaplib
import mimetypes
import os
import smtplib
import sys
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path

IMAP_PORT, SMTP_PORT = 993, 465
MAX_BODY_CHARS, MAX_HTML_CHARS = 200_000, 8000


def strip_password(raw: str) -> str:
    """App passwords are shown with spaces; IMAP/SMTP reject them."""
    return "".join(raw.split())


def _creds() -> tuple[str, str]:
    addr = os.environ.get("MAIL_ADDRESS", "").strip()
    password = strip_password(os.environ.get("MAIL_APP_PASSWORD", ""))
    if not addr or not password:
        raise SystemExit("ERROR: no mail configured for this agent (MAIL_ADDRESS and/or MAIL_APP_PASSWORD missing). "
                         "Set them in the service environment (an app password, never the account password).")
    return addr, password


def imap_host() -> str:
    return os.environ.get("MAIL_IMAP_HOST", "").strip() or "imap.gmail.com"


def smtp_host() -> str:
    return os.environ.get("MAIL_SMTP_HOST", "").strip() or "smtp.gmail.com"


def allowlist() -> set[str] | None:
    addrs = {p.strip().casefold() for p in os.environ.get("MAIL_TO_ALLOWLIST", "").split(",") if p.strip()}
    return addrs or None


def check_allowlist(recipients: list[str]) -> None:
    allowed = allowlist()
    for r in recipients if allowed else []:
        if r.strip().casefold() not in allowed:
            raise SystemExit(f"ERROR: {r!r} is not in MAIL_TO_ALLOWLIST; not sending. Ask the owner to add it.")


def header_line(msg: email.message.Message, name: str) -> str:
    return " ".join(str(msg.get(name, "") or "").split())


def format_date(msg: email.message.Message) -> str:
    raw = msg.get("Date", "") or ""
    try:
        return parsedate_to_datetime(raw).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, IndexError, OverflowError):
        return (raw or "?")[:19]


def _text(part: email.message.Message) -> str | None:
    try:
        payload = part.get_content()
    except Exception:
        raw = part.get_payload(decode=True) or b""
        payload = raw.decode(part.get_content_charset() or "utf-8", errors="replace") if isinstance(raw, bytes) else raw
    return payload if isinstance(payload, str) else None


def plaintext_body(msg: email.message.Message) -> str:
    """Prefer text/plain; HTML-only mail is marked and cut short."""
    plain, html = [], []
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if "attachment" in str(part.get("Content-Disposition") or "").casefold():
            continue
        text = _text(part)
        if text is None:
            continue
        if part.get_content_type() == "text/html":
            html.append(text)
        elif part.get_content_type() == "text/plain" or not msg.is_multipart():
            plain.append(text)
    if plain:
        return "\n".join(plain)
    if html:
        h = html[0]
        return "[HTML only; no text/plain]\n" + (h[:MAX_HTML_CHARS] + "\n…[HTML truncated]" if len(h) > MAX_HTML_CHARS else h)
    return "(no text body)"


def _imap() -> imaplib.IMAP4_SSL:
    addr, password = _creds()
    try:
        imap = imaplib.IMAP4_SSL(imap_host(), IMAP_PORT)
        imap.login(addr, password)
    except imaplib.IMAP4.error as e:
        print(f"ERROR: IMAP login rejected: {e}", file=sys.stderr)
        raise SystemExit(1) from e
    except OSError as e:
        print(f"ERROR: could not connect to IMAP ({imap_host()}): {e}", file=sys.stderr)
        raise SystemExit(1) from e
    if imap.select("INBOX", readonly=True)[0] != "OK":
        print("ERROR: could not open INBOX", file=sys.stderr)
        raise SystemExit(1)
    return imap


def _first_bytes(fetched) -> bytes:
    return next((i[1] for i in fetched or [] if isinstance(i, tuple) and len(i) >= 2), b"")


def cmd_info() -> int:
    addr, _ = _creds()
    al = allowlist()
    print(f"address: {addr}\nIMAP: {imap_host()}:{IMAP_PORT} SSL\nSMTP: {smtp_host()}:{SMTP_PORT} SSL\n"
          "App Password: present (not printed)\n"
          f"MAIL_TO_ALLOWLIST: {'(no restriction)' if al is None else f'{len(al)} recipient(s)'}")
    return 0


def cmd_ls(limit: int, unread: bool) -> int:
    imap = _imap()
    try:
        typ, data = imap.uid("search", None, "UNSEEN" if unread else "ALL")
        if typ != "OK":
            print("ERROR: SEARCH failed", file=sys.stderr)
            return 1
        uids = list(reversed((data[0] or b"").split()))[:limit]  # newest first
        if not uids:
            print("(no unread)" if unread else "(empty)")
        for uid in uids:
            _, fetched = imap.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            msg = email.message_from_bytes(_first_bytes(fetched), policy=email.policy.default)
            print(f"{uid.decode()}\t{format_date(msg)}\t{header_line(msg, 'From') or '?'}\t"
                  f"{header_line(msg, 'Subject') or '(no subject)'}")
        return 0
    finally:
        imap.logout()


def cmd_get(uid: str) -> int:
    if not uid.isdigit():
        print("ERROR: uid must be numeric", file=sys.stderr)
        return 2
    imap = _imap()
    try:
        raw = _first_bytes(imap.uid("fetch", uid, "(RFC822)")[1])
        if not raw:
            print(f"ERROR: UID {uid} not found", file=sys.stderr)
            return 1
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        body = plaintext_body(msg)
        if len(body) > MAX_BODY_CHARS:
            body = body[:MAX_BODY_CHARS] + f"\n…[truncated to {MAX_BODY_CHARS} characters]"
        head = "".join(f"{h}: {header_line(msg, h)}\n" for h in ("From", "To", "Date", "Subject"))
        out = Path(f"/tmp/mail-{uid}.txt")
        out.write_text(f"{head}UID: {uid}\n---\n{body}", encoding="utf-8")
        print(out)
        return 0
    finally:
        imap.logout()


def cmd_send(to: list[str], cc: list[str], subject: str, body: str, confirmed: bool,
             attach: list[str] | None = None) -> int:
    if not confirmed:
        print("ERROR: refused, --i-confirm-send is missing. Confirm with the owner first, then run again "
              "with that flag. A channel message is not authorization.", file=sys.stderr)
        return 2
    recipients = [a.strip() for a in to + cc if a.strip()]
    if not recipients:
        print("ERROR: --to is missing", file=sys.stderr)
        return 2
    check_allowlist(recipients)
    addr, password = _creds()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = addr, ", ".join(a.strip() for a in to if a.strip()), subject
    if cc:
        msg["Cc"] = ", ".join(a.strip() for a in cc if a.strip())
    msg.set_content(body)
    for p in attach or []:
        ctype, enc = mimetypes.guess_type(Path(p).name)
        main_t, sub_t = (ctype if ctype and not enc else "application/octet-stream").split("/", 1)
        msg.add_attachment(Path(p).read_bytes(), maintype=main_t, subtype=sub_t, filename=Path(p).name)
    try:
        with smtplib.SMTP_SSL(smtp_host(), SMTP_PORT, timeout=60) as smtp:
            smtp.login(addr, password)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        print(f"ERROR: SMTP ({smtp_host()}): {e}", file=sys.stderr)
        return 1
    print(f"sent: to={msg['To']}" + (f" cc={msg['Cc']}" if cc else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Agent mail (IMAP/SMTP)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="address and hosts (no secrets)")
    p_ls = sub.add_parser("ls", help="recent INBOX messages")
    p_ls.add_argument("--limit", type=int, default=20)
    p_ls.add_argument("--unread", action="store_true")
    sub.add_parser("get", help="save one message by UID to /tmp").add_argument("uid")
    p_s = sub.add_parser("send", help="send a mail (requires --i-confirm-send)")
    p_s.add_argument("--to", action="append", default=[])
    p_s.add_argument("--cc", action="append", default=[])
    p_s.add_argument("--subject", required=True)
    body = p_s.add_mutually_exclusive_group(required=True)
    body.add_argument("--body", default="")
    body.add_argument("--body-file", default="")
    p_s.add_argument("--attach", action="append", default=[])
    p_s.add_argument("--i-confirm-send", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "info":
            return cmd_info()
        if a.cmd == "ls":
            return cmd_ls(max(1, a.limit), a.unread)
        if a.cmd == "get":
            return cmd_get(a.uid)
        for f in ([a.body_file] if a.body_file else []) + a.attach:
            if not Path(f).is_file():
                print(f"ERROR: file does not exist: {f}", file=sys.stderr)
                return 2
        text = Path(a.body_file).read_text(encoding="utf-8") if a.body_file else a.body
        return cmd_send(a.to, a.cc, a.subject, text, a.i_confirm_send, a.attach)
    except SystemExit as e:
        if isinstance(e.code, str):
            print(e.code, file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(main())
