#!/usr/bin/env python3
"""Publish a static site on <sub>.<VERCEL_DOMAIN>, with no git repo involved.

  vercel_publish.py --sub sales --dir ./dashboard
  vercel_publish.py --sub sales --file index.html
  cat page.html | vercel_publish.py --sub sales --stdin

Uploads files straight to the Vercel API, creates the project if needed, attaches
<sub>.<VERCEL_DOMAIN>, and does NOT report success until the URL answers 200
(on Vercel, READY can coexist with a page that does not load).

Env: VERCEL_TOKEN and VERCEL_DOMAIN (required) · VERCEL_TEAM_ID (only with several teams)
Exit 0 ok · 1 API failed or page not serving · 2 missing config or args
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.vercel.com"
UA = "curl/8.5.0"  # Cloudflare rejects urllib's default user-agent (error 1010, reads like a 403)
SKIP = {".git", "__pycache__", ".DS_Store", "node_modules"}


def _api(token: str, method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        API + path, data=json.dumps(body).encode() if body is not None else None, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"ERROR: Vercel {method} {path} → HTTP {e.code}: {e.read().decode(errors='replace')[:400]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"ERROR: network error talking to Vercel: {e.reason}")


def team_qs(token: str) -> str:
    """Team goes in the query string. With a single team there is no need to set it."""
    tid = os.environ.get("VERCEL_TEAM_ID", "").strip()
    if not tid:
        teams = _api(token, "GET", "/v2/teams").get("teams") or []
        if len(teams) == 1:
            tid = teams[0]["id"]
        elif len(teams) > 1:
            names = ", ".join(f"{t['slug']}={t['id']}" for t in teams)
            raise SystemExit(f"ERROR: the account has several teams; set VERCEL_TEAM_ID ({names})")
    return f"?teamId={tid}" if tid else ""


def collect_files(a: argparse.Namespace) -> list[dict]:
    """Everything goes base64: works the same for HTML and images."""
    raw: list[tuple[str, bytes]] = []
    if a.stdin:
        raw.append(("index.html", sys.stdin.buffer.read()))
    for f in a.file:
        p = Path(f)
        if not p.is_file():
            raise SystemExit(f"ERROR: file does not exist: {f}")
        raw.append((p.name, p.read_bytes()))
    if a.dir:
        root = Path(a.dir)
        if not root.is_dir():
            raise SystemExit(f"ERROR: folder does not exist: {a.dir}")
        for p in sorted(root.rglob("*")):
            if p.is_file() and not any(s in p.parts for s in SKIP):
                raw.append((p.relative_to(root).as_posix(), p.read_bytes()))
    if not raw:
        raise SystemExit("ERROR: give --dir, --file or --stdin")
    if not any(n == "index.html" for n, _ in raw):
        raise SystemExit("ERROR: index.html is missing; without it the site root is a 404")
    return [{"file": n, "data": base64.b64encode(b).decode(), "encoding": "base64"} for n, b in raw]


def wait_ready(token: str, dep_id: str, qs: str, timeout: int = 300) -> str:
    end, state = time.time() + timeout, "?"
    while time.time() < end:
        d = _api(token, "GET", f"/v13/deployments/{dep_id}{qs}")
        state = d.get("readyState") or d.get("status") or "?"
        if state in ("READY", "ERROR", "CANCELED"):
            return state
        time.sleep(5)
    return state


def answers_200(url: str, tries: int = 12) -> int:
    """READY does not mean the page loads. This does."""
    code = 0
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20) as r:
                code = r.status
                if code == 200:
                    return 200
        except urllib.error.HTTPError as e:
            code = e.code
        except urllib.error.URLError:
            code = 0
        time.sleep(5 if i < 3 else 10)
    return code


def main() -> int:
    ap = argparse.ArgumentParser(description="Publish a site on <sub>.<domain> via Vercel")
    ap.add_argument("--sub", required=True, help="subdomain, e.g. sales")
    ap.add_argument("--dir", default="", help="folder to publish (must contain index.html)")
    ap.add_argument("--file", action="append", default=[], help="single file (repeatable)")
    ap.add_argument("--stdin", action="store_true", help="read HTML from stdin as index.html")
    ap.add_argument("--project", default="", help="project name (default: the subdomain)")
    a = ap.parse_args()

    token = os.environ.get("VERCEL_TOKEN", "").strip()
    domain = os.environ.get("VERCEL_DOMAIN", "").strip().strip(".")
    for var, val in (("VERCEL_TOKEN", token), ("VERCEL_DOMAIN", domain)):
        if not val:
            print(f"ERROR: {var} is not set in the environment", file=sys.stderr)
            return 2
    sub = a.sub.strip().lower().rstrip(".")
    if not re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?", sub):
        print(f"ERROR: '{sub}' is not a valid subdomain (a-z, 0-9, hyphens)", file=sys.stderr)
        return 2
    project, host = (a.project or sub).strip().lower(), f"{sub}.{domain}"
    try:
        files = collect_files(a)
        qs = team_qs(token)
        print(f"publishing {len(files)} file(s) to {host} (project {project})…")
        dep = _api(token, "POST", f"/v13/deployments{qs}", {
            "name": project, "files": files, "target": "production", "projectSettings": {"framework": None}})
        state = wait_ready(token, dep["id"], qs)
        if state != "READY":
            print(f"ERROR: the deployment ended in {state}", file=sys.stderr)
            return 1
        d = _api(token, "POST", f"/v10/projects/{project}/domains{qs}", {"name": host})
        if not d.get("verified", False):
            challenge = json.dumps(d.get("verification") or [])[:300]
            print(f"ERROR: {host} is not verified. Pending challenge: {challenge}", file=sys.stderr)
            return 1
    except SystemExit as e:
        if not isinstance(e.code, str):
            raise
        if "domain_already_in_use" in e.code or "already exists on the project" in e.code:
            print(f"(domain {host} was already on {project})")  # re-attaching is not a failure
        else:
            print(e.code, file=sys.stderr)
            return 1
    url = f"https://{host}"
    code = answers_200(url)
    if code != 200:
        print(f"ERROR: {url} answers HTTP {code or 'no response'}: the site is not serving", file=sys.stderr)
        return 1
    print(f"ok: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
