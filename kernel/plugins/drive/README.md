# Plugin: drive (Google Drive via rclone)

`ls`, `drives`, `find`, `get`, `put`, `info`, optional `--remote`. Shared drives are addressed by name; `@shared` = shared with me.

| | |
|---|---|
| Enable | `PIXAN_PLUGINS=drive` |
| Env | `RCLONE_CONF` (the full rclone.conf text), `RCLONE_ROOT` (e.g. `gdrive:`), `DRIVE_SHARE_EMAIL` |
| Needs in client image | `rclone` |
| Domains | `www.googleapis.com`, `oauth2.googleapis.com` |

Ported from pixan-railway-agent `drive.py` / `drive` skill. Changes: the config is written from env to a
private temp file (mode 600, `RCLONE_CONFIG_FILE` to override), never to the volume; `@compartidos` → `@shared`.
Not ported: `drive_onboard.py` (one-time service-account setup helper).
