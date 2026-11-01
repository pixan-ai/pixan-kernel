#!/usr/bin/env python3
"""ElevenLabs voice: text-to-speech, speech-to-text, and Telegram voice notes.

  voice.py tts "<text>" [--voice ID] [--model ID] [--lang es] [--tempo 1.0] [--out x.mp3]
  voice.py stt <audio> [--lang es] [--diarize]
  voice.py send --chat-id N --audio x.mp3 [--caption ...] [--reply-to N]

Keys come from env only (ELEVENLABS_API_KEY, TELEGRAM_BOT_TOKEN); never from files.
Exit 0 ok · 1 HTTP/network error · 2 missing config or file.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

API = "https://api.elevenlabs.io/v1"
FALLBACK_VOICE = "xzWD1ftyNVsuUMY2ll3j"  # public ElevenLabs library voice (multilingual)
DEFAULT_MODEL = "eleven_v3"


def default_voice() -> str:
    return os.environ.get("ELEVENLABS_VOICE_ID", "").strip() or FALLBACK_VOICE


def need(var: str) -> str:
    val = os.environ.get(var, "").strip()
    if not val:
        sys.stderr.write(f"ERROR: {var} is not set in the environment.\n")
        raise SystemExit(2)
    return val


def multipart(fields: dict, file_field: str, path: Path, mime: str | None = None) -> tuple[bytes, str]:
    b = "----pixan" + uuid.uuid4().hex
    out = b""
    for k, v in fields.items():
        out += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    mime = mime or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    out += (f'--{b}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{path.name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{b}--\r\n".encode()
    return out, b


def post(req: urllib.request.Request, timeout: int) -> bytes:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}\n")
    except urllib.error.URLError as e:
        sys.stderr.write(f"Network error: {e}\n")
    raise SystemExit(1)


def ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        sys.stderr.write("ERROR: ffmpeg is not installed (the client image must install it).\n")
        raise SystemExit(2)
    return exe


def cmd_tts(a) -> int:
    key = need("ELEVENLABS_API_KEY")
    voice = a.voice or default_voice()
    settings = {"stability": 0.5, "use_speaker_boost": True}  # v3 takes discrete stability steps
    payload = {"text": a.text, "model_id": a.model, "voice_settings": settings}
    if a.lang:
        payload["language_code"] = a.lang
    req = urllib.request.Request(
        f"{API}/text-to-speech/{voice}?output_format=mp3_44100_128", data=json.dumps(payload).encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"}, method="POST")
    audio = post(req, 120)
    out = Path(a.out or Path(tempfile.gettempdir()) / "voice" / f"tts_{int(time.time())}.mp3")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
    if abs(a.tempo - 1.0) > 1e-6:  # v3 ignores `speed`; atempo keeps the pitch
        fast = out.with_suffix(".tempo.mp3")
        r = subprocess.run([ffmpeg(), "-y", "-i", str(out), "-filter:a", f"atempo={a.tempo}", str(fast)],
                           capture_output=True)
        if r.returncode == 0:
            fast.replace(out)
    print(out)
    return 0


def cmd_stt(a) -> int:
    key = need("ELEVENLABS_API_KEY")
    path = Path(a.audio).expanduser()
    if not path.is_file():
        sys.stderr.write(f"ERROR: file does not exist: {path}\n")
        return 2
    fields = {"model_id": "scribe_v1"}
    if a.lang:
        fields["language_code"] = a.lang
    if a.diarize:
        fields["diarize"] = "true"
    body, b = multipart(fields, "file", path)
    req = urllib.request.Request(f"{API}/speech-to-text", data=body, method="POST", headers={
        "xi-api-key": key, "Content-Type": f"multipart/form-data; boundary={b}", "Accept": "application/json"})
    data = json.loads(post(req, 300))
    sys.stderr.write(json.dumps({"language": data.get("language_code"),
                                 "duration_seconds": data.get("duration_seconds")}) + "\n")
    print(data.get("text", "").strip())
    return 0


def duration_secs(src: str) -> int | None:
    """Telegram shows 0:00 unless `duration` is sent; ffmpeg prints it on stderr (no ffprobe needed)."""
    err = subprocess.run([ffmpeg(), "-i", src], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):(\d+)\.(\d+)", err)
    if not m:
        return None
    h, mi, s, cs = (int(g) for g in m.groups())
    return round(h * 3600 + mi * 60 + s + cs / 100)


def cmd_send(a) -> int:
    """Send as a voice note (sendVoice, OGG/Opus), never as an mp3 file (sendAudio auto-plays the chat)."""
    token = need("TELEGRAM_BOT_TOKEN")
    if not Path(a.audio).is_file():
        sys.stderr.write(f"ERROR: file does not exist: {a.audio}\n")
        return 2
    ogg = Path(tempfile.gettempdir()) / f"voice_{uuid.uuid4().hex}.ogg"
    subprocess.run([ffmpeg(), "-y", "-i", a.audio, "-c:a", "libopus", "-b:a", "48k", "-ar", "48000",
                    "-ac", "1", str(ogg)], check=True, capture_output=True)
    fields: dict = {"chat_id": a.chat_id}
    secs = duration_secs(a.audio)
    if secs:
        fields["duration"] = secs
    if a.caption:
        fields["caption"] = a.caption
    if a.reply_to:
        fields["reply_to_message_id"] = a.reply_to
    try:
        body, b = multipart(fields, "voice", ogg, "audio/ogg")
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendVoice", data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={b}"})
        print(post(req, 120).decode("utf-8", "replace"))
    finally:
        ogg.unlink(missing_ok=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tts")
    t.add_argument("text")
    t.add_argument("--voice", default="")
    t.add_argument("--model", default=DEFAULT_MODEL)
    t.add_argument("--lang", default="")
    t.add_argument("--tempo", type=float, default=float(os.environ.get("ELEVENLABS_TEMPO") or 1.0))
    t.add_argument("--out", default="")
    s = sub.add_parser("stt")
    s.add_argument("audio")
    s.add_argument("--lang", default="")
    s.add_argument("--diarize", action="store_true")
    v = sub.add_parser("send")
    v.add_argument("--chat-id", required=True)
    v.add_argument("--audio", required=True)
    v.add_argument("--caption", default="")
    v.add_argument("--reply-to", default="")
    a = ap.parse_args(argv)
    return {"tts": cmd_tts, "stt": cmd_stt, "send": cmd_send}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
