---
name: plugin-voice
description: Speak and listen with ElevenLabs. Text to speech (voice notes on Telegram) and speech to text for voice messages people send.
allowed-tools: Bash, Read
---
# Voice (ElevenLabs)

Script: `{{KERNEL}}/plugins/voice/voice.py`. The key is `ELEVENLABS_API_KEY` in the environment; never ask for it in chat.

- **Reply with audio** (only when someone asks for it):
  1. `python3 {{KERNEL}}/plugins/voice/voice.py tts "[warmly] text..."` prints the mp3 path.
  2. `python3 {{KERNEL}}/plugins/voice/voice.py send --chat-id <chat_id> --audio <path> [--reply-to <message_id>]`
  Always send as a **voice note** with `send` (sendVoice, OGG/Opus, with duration). Never attach the mp3 with `reply`:
  Telegram treats it as music and auto-plays older tracks.
- **A voice message arrives:** download it with the Telegram tool, then
  `python3 {{KERNEL}}/plugins/voice/voice.py stt <path>` prints the text. Act on what it asks, not just echo it.
- Model `eleven_v3`: emotion goes in audio tags inside the text (`[warmly]`, `[excited]`, `[whispers]`, `...` pauses).
  Speed: `--tempo 1.2` (ffmpeg atempo; v3 ignores `speed`). Voice: `ELEVENLABS_VOICE_ID` or `--voice`.
- ElevenLabs charges per character / per minute. Do not turn secrets or sensitive data into audio.
- Exit 2 = key, file or ffmpeg missing: tell the owner which one.
