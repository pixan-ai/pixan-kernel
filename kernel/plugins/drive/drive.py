#!/usr/bin/env python3
"""Read and write the agent's Google Drive, through rclone.

  drive.py ls [path]                 list
  drive.py drives                    shared drives this agent can see
  drive.py find "text" [path]        search by name
  drive.py get report.pdf [--out /tmp/x.pdf]
  drive.py put /tmp/report.md [path]
  drive.py info                      which account and what it sees
  drive.py --remote user ls          use another rclone remote

A path may start with a shared drive name ("Clients/Reports") or with @shared
(what people shared directly with the agent); otherwise it is relative to RCLONE_ROOT.

The rclone config comes from env RCLONE_CONF and is written to a private temp file
(mode 600, outside the volume); rclone refreshes tokens there while the container lives.
The real scope is set by Drive itself: the agent sees what was shared with its account.
Exit 0 ok · 1 rclone failed · 2 missing config or args
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TIMEOUT = 180
EXPORT = ["--drive-export-formats", "txt,csv,pdf"]  # Google Docs are not files without this
SHARED = "@shared"
_REMOTE_OVERRIDE: str | None = None


def conf_path() -> Path:
    return Path(os.environ.get("RCLONE_CONFIG_FILE") or Path(tempfile.gettempdir()) / f"pixan-rclone-{os.getuid()}.conf")


def _conf() -> str:
    path, raw = conf_path(), os.environ.get("RCLONE_CONF", "")
    if not path.is_file():
        if not raw.strip():
            raise SystemExit("ERROR: no Drive configured for this agent (RCLONE_CONF is not set).")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(raw if raw.endswith("\n") else raw + "\n")
    return str(path)


def _root() -> str:
    if _REMOTE_OVERRIDE is not None:
        return f"{_REMOTE_OVERRIDE}:"
    r = os.environ.get("RCLONE_ROOT", "").strip()
    if not r:
        raise SystemExit("ERROR: RCLONE_ROOT is not set (e.g. 'gdrive:' or 'gdrive:Reports')")
    return r.rstrip("/")


def _is_default_remote() -> bool:
    default = os.environ.get("RCLONE_ROOT", "").strip().split(":", 1)[0]
    return _REMOTE_OVERRIDE is None or (bool(default) and _REMOTE_OVERRIDE == default)


def join(base: str, sub: str) -> str:
    """`gdrive:` takes no slash; `gdrive:x` does."""
    return base if not sub else f"{base}{'' if base.endswith(':') else '/'}{sub}"


def _no_escape(sub: str) -> str:
    """Not a boundary (root_folder_id in the rclone config is), just stops accidental `../`."""
    sub = (sub or "").strip().strip("/")
    if sub and ".." in Path(sub).parts:
        raise SystemExit(f"ERROR: path {sub!r} leaves the agent's folder")
    return sub


def target(sub: str = "") -> str:
    sub = _no_escape(sub)
    return join(_root(), sub) if sub else _root()


def _remote() -> str:
    return _root().split(":", 1)[0]


def share_email() -> str:
    """The address people share with (a group, never the service-account address)."""
    return os.environ.get("DRIVE_SHARE_EMAIL", "").strip()


def resolve(sub: str, drives: list[dict]) -> tuple[str, list[str]]:
    """Agent path → (rclone path, extra flags). The first segment decides."""
    sub = _no_escape(sub)
    first, _, rest = sub.partition("/")
    if first.casefold() == SHARED:  # shared-with-me lives outside any drive: clear the configured one
        return join(f"{_remote()}:", rest), ["--drive-team-drive", "", "--drive-shared-with-me"]
    for d in drives:
        if d.get("name", "").casefold() == first.casefold():
            return join(f"{_remote()},team_drive={d['id']}:", rest), []
    return target(sub), []


def rclone(args: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["rclone", "--config", _conf(), *args], capture_output=True, text=True, timeout=TIMEOUT)
    except FileNotFoundError:
        raise SystemExit("ERROR: rclone is not installed (the client image must install it)")
    except subprocess.TimeoutExpired:
        raise SystemExit(f"ERROR: rclone took more than {TIMEOUT}s")


def shared_drives() -> list[dict]:
    """Asked every call on purpose: a newly shared drive shows up with no redeploy."""
    r = rclone(["backend", "drives", f"{_remote()}:"])
    if r.returncode != 0:
        return []
    try:
        return [{"id": d["id"], "name": d["name"]} for d in json.loads(r.stdout or "[]")]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []


def path(sub: str) -> tuple[str, list[str]]:
    """Like resolve(), asking for drives only when the path could name one."""
    first = (sub or "").strip().strip("/").partition("/")[0]
    return resolve(sub, [] if not first or first.casefold() == SHARED else shared_drives())


def main(argv: list[str] | None = None) -> int:
    global _REMOTE_OVERRIDE
    ap = argparse.ArgumentParser(description="Agent's Google Drive, via rclone")
    ap.add_argument("--remote", default="", help="optional rclone remote; default from RCLONE_ROOT")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ls")
    p.add_argument("sub", nargs="?", default="")
    p = sub.add_parser("find")
    p.add_argument("text")
    p.add_argument("sub", nargs="?", default="")
    p = sub.add_parser("get")
    p.add_argument("file")
    p.add_argument("--out", default="")
    p = sub.add_parser("put")
    p.add_argument("local")
    p.add_argument("sub", nargs="?", default="")
    sub.add_parser("drives")
    sub.add_parser("info")
    a = ap.parse_args(argv)
    _REMOTE_OVERRIDE = a.remote.rstrip(":") if a.remote else None
    try:
        if a.cmd == "drives":
            ds = shared_drives()
            print("\n".join(f"{d['name']}\t{d['id']}" for d in ds) or "(no shared drives; ask for one to be shared)")
            return 0
        if a.cmd == "info":
            mail = share_email() if _is_default_remote() else os.environ.get("MAIL_ADDRESS", "").strip()
            r0 = rclone(["listremotes"])
            print(f"active remote: {_remote()}\nremotes: {', '.join(x.rstrip(':') for x in r0.stdout.split()) or '(none)'}")
            print("to share something with you, share it to: " + (mail or "(no address configured; ask the owner)"))
            ds = shared_drives()
            print(f"root: {_root()}\nshared drives: {', '.join(d['name'] for d in ds) or '(none)'}")
            r = rclone(["about", f"{_remote()}:"])
            print(((r.stdout or r.stderr).strip()[:400]) or "own space: none; you can only create files inside a shared drive")
            return 0 if r.returncode == 0 else 1
        if a.cmd == "ls":
            dest, flags = path(a.sub)
            r = rclone(["lsf", "--max-depth", "1", *flags, dest])
        elif a.cmd == "find":
            dest, flags = path(a.sub)
            r = rclone(["lsf", "-R", "--include", f"*{a.text}*", *flags, dest])
        elif a.cmd == "get":
            dest, flags = path(a.file)
            out = a.out or f"/tmp/{Path(a.file).name}"
            r = rclone(["copyto", *flags, dest, out, *EXPORT])
            if r.returncode == 0:
                print(out)
                return 0
        else:
            local = Path(a.local)
            if not local.is_file():
                print(f"ERROR: file does not exist: {local}", file=sys.stderr)
                return 2
            base, flags = path(a.sub)
            r = rclone(["copyto", *flags, str(local), join(base, local.name)])
            if r.returncode == 0:  # the path the person typed, not rclone's team_drive=… form
                print(f"uploaded: {join(a.sub.strip().strip('/') or _root(), local.name)}")
                return 0
    except SystemExit as e:
        if isinstance(e.code, str):
            print(e.code, file=sys.stderr)
            return 2
        raise
    if r.returncode != 0:
        err = (r.stderr or r.stdout).strip()
        if "storageQuotaExceeded" in err or "do not have storage quota" in err:
            print("ERROR: you cannot create new files here. A service account can only write inside a shared drive: "
                  "pick one from `drive.py drives`, or ask for one to be shared." if _is_default_remote() else
                  "ERROR: you cannot create the file here: write to your My Drive or a folder shared with edit access.",
                  file=sys.stderr)
        else:
            print(err[:400], file=sys.stderr)
        return 1
    print((r.stdout or "").strip() or "(empty)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
