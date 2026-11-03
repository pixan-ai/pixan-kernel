#!/usr/bin/env python3
"""Encrypted backups of the agent's memory, encrypted on this machine.

  backup.py tick   # called by the heartbeat: backs up if the last one is older than BACKUP_INTERVAL_SEC
  backup.py now    # back up now

What goes in: the workspace (CLAUDE/SOUL/IDENTITY/USER/STACK/MEMORY, skills, files),
conversation transcripts and Claude's own memory (config/projects), scheduled tasks
and the Telegram access list. What never goes in: credential files, .claude.json,
.env files, keys, plugins, caches. Every text file passes the secret filter first.

The archive is encrypted with `age` to BACKUP_AGE_RECIPIENT, a public key. Only the
client holds the matching private key, so nobody else (not the storage, not the
installer) can read a backup. Off until BACKUP_AGE_RECIPIENT is set.

Copies: always one in BACKUP_DIR (keep the newest BACKUP_KEEP); optionally one in
Cloudflare R2 when BACKUP_R2_ENDPOINT, BACKUP_R2_BUCKET, BACKUP_R2_ACCESS_KEY_ID and
BACKUP_R2_SECRET_ACCESS_KEY are all set. R2 credentials go to curl on stdin, never
on the command line or in a log.

Restore: age -d -i key.txt agent-YYYYmmdd-HHMMSS.tar.age | tar -x -C /restore
Exit 0 ok or nothing to do, 1 failed.
"""
from __future__ import annotations

import fnmatch
import io
import os
import subprocess
import sys
import tarfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from secret_filter import redact  # noqa: E402

DEFAULTS = {"BACKUP_INTERVAL_SEC": 3600, "BACKUP_KEEP": 48}
MAX_TEXT = 5 * 1024 * 1024   # bigger files are copied only if they have no secret shape at all
# Relative to /data. Directories are walked; missing ones are skipped.
INCLUDE = ["workspace", "config/projects", "config/cron.json", "config/channels/telegram/access.json"]
EXCLUDE = [".credentials.json", ".claude.json*", ".env", ".env.*", "*.pem", "*.key", "id_rsa*",
           "id_ed25519*", "*.bak-*", "node_modules", ".git", "__pycache__", "*.age"]


def _int(name: str) -> int:
    try:
        return int(os.environ.get(name) or DEFAULTS[name])
    except ValueError:
        return DEFAULTS[name]


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "/data"))


def backup_dir() -> Path:
    return Path(os.environ.get("BACKUP_DIR") or data_dir() / "backups")


def stamp_path() -> Path:
    return data_dir() / "config" / "backup-last"


def _excluded(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE)


def files() -> list[Path]:
    root, out = data_dir(), []
    skip = backup_dir().resolve()
    for rel in INCLUDE:
        p = root / rel
        if p.is_file() and not _excluded(p.name):
            out.append(p)
        elif p.is_dir():
            for dirpath, dirnames, filenames in os.walk(p):
                d = Path(dirpath)
                dirnames[:] = sorted(n for n in dirnames if not _excluded(n) and (d / n).resolve() != skip)
                out.extend(d / n for n in sorted(filenames) if not _excluded(n) and not (d / n).is_symlink())
    return out


def build_tar() -> tuple[bytes, int, int]:
    """Plain tar (in memory) of every file, secrets redacted. Returns (bytes, files, redactions)."""
    buf, n_files, n_redacted = io.BytesIO(), 0, 0
    root = data_dir()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for path in files():
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = None
            if text is not None:
                clean, n = redact(text)
                if n:
                    raw, n_redacted = clean.encode("utf-8"), n_redacted + n
            elif len(raw) <= MAX_TEXT and redact(raw.decode("latin-1"))[1]:
                n_redacted += 1
                continue  # binary file with a secret shape inside: leave it out
            info = tarfile.TarInfo(str(path.relative_to(root)))
            info.size, info.mtime, info.mode = len(raw), int(path.stat().st_mtime), 0o600
            tar.addfile(info, io.BytesIO(raw))
            n_files += 1
    return buf.getvalue(), n_files, n_redacted


def encrypt(plain: bytes, out: Path, recipient: str, runner=subprocess.run) -> None:
    tmp = out.with_name(out.name + ".part")
    r = runner(["age", "-r", recipient, "-o", str(tmp)], input=plain, capture_output=True)
    if r.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"age failed: {(r.stderr or b'').decode(errors='replace').strip()[:200]}")
    os.replace(tmp, out)


def prune(folder: Path, keep: int) -> None:
    for old in sorted(folder.glob("*.tar.age"))[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)


def r2_settings() -> dict | None:
    keys = ("BACKUP_R2_ENDPOINT", "BACKUP_R2_BUCKET", "BACKUP_R2_ACCESS_KEY_ID", "BACKUP_R2_SECRET_ACCESS_KEY")
    vals = {k: os.environ.get(k, "").strip() for k in keys}
    return vals if all(vals.values()) else None


def upload_r2(path: Path, cfg: dict, runner=subprocess.run) -> None:
    url = f"{cfg['BACKUP_R2_ENDPOINT'].rstrip('/')}/{cfg['BACKUP_R2_BUCKET']}/{os.environ.get('AGENT_NAME', 'agent')}/{path.name}"
    conf = f'user = "{cfg["BACKUP_R2_ACCESS_KEY_ID"]}:{cfg["BACKUP_R2_SECRET_ACCESS_KEY"]}"\n'
    r = runner(["curl", "-fsS", "--max-time", "300", "--aws-sigv4", "aws:amz:auto:s3", "-K", "-",
                "-T", str(path), url], input=conf.encode(), capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"R2 upload failed (curl exit {r.returncode})")


def backup(now: float | None = None, runner=subprocess.run) -> str:
    recipient = os.environ.get("BACKUP_AGE_RECIPIENT", "").strip()
    if not recipient:
        return "off (set BACKUP_AGE_RECIPIENT)"
    now = now or time.time()
    folder = backup_dir()
    folder.mkdir(parents=True, exist_ok=True)
    plain, n_files, n_redacted = build_tar()
    name = f"{os.environ.get('AGENT_NAME', 'agent')}-{datetime.fromtimestamp(now).strftime('%Y%m%d-%H%M%S')}.tar.age"
    out = folder / name
    encrypt(plain, out, recipient, runner)
    prune(folder, _int("BACKUP_KEEP"))
    where = "local"
    cfg = r2_settings()
    if cfg:
        upload_r2(out, cfg, runner)
        where = "local + R2"
    stamp_path().parent.mkdir(parents=True, exist_ok=True)
    stamp_path().write_text(str(int(now)), encoding="utf-8")
    return f"OK {name} ({n_files} files, {n_redacted} secrets redacted, {where})"


def due(now: float) -> bool:
    try:
        last = float(stamp_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        last = 0.0
    return now - last >= _int("BACKUP_INTERVAL_SEC")


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd not in ("tick", "now"):
        print(__doc__, file=sys.stderr)
        return 1
    now = time.time()
    if cmd == "tick" and (not os.environ.get("BACKUP_AGE_RECIPIENT") or not due(now)):
        return 0  # off, or not due yet: say nothing
    try:
        print(backup(now))
        return 0
    except (OSError, RuntimeError) as e:
        print(f"ERROR {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
