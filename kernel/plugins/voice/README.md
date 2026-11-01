# Plugin: voice (ElevenLabs)

TTS (`eleven_v3`), STT (`scribe_v1`) and Telegram voice notes (`sendVoice`, OGG/Opus mono 48k, explicit duration).

| | |
|---|---|
| Enable | `PIXAN_PLUGINS=voice` |
| Env | `ELEVENLABS_API_KEY` (required), `ELEVENLABS_VOICE_ID`, `ELEVENLABS_TEMPO` (default 1.0) |
| Needs in client image | `ffmpeg` (tempo and voice notes) |
| Domains | `api.elevenlabs.io`, `api.telegram.org` |

Ported from pixan-railway-agent `elevenlabs-tts` (generate/transcribe/send_voice merged into one script).
Not ported: per-call usage logs, the `.env` token fallback (env only).
