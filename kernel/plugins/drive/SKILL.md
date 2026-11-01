---
name: plugin-drive
description: Read and write the agent's Google Drive when someone asks "find the file", "read me that document", "upload it to Drive".
allowed-tools: Bash, Read
---
# Google Drive (rclone)

```bash
D={{KERNEL}}/plugins/drive/drive.py
python3 $D drives                      # shared drives you can see
python3 $D ls [Reports]                # list (a subfolder, a shared drive name, or @shared)
python3 $D find "quote" ["Clients"]    # search by name
python3 $D get report.pdf              # downloads to /tmp and prints the path; then Read it
python3 $D put /tmp/report.md "Clients/Reports"
python3 $D info                        # account, remotes, and the address to share with
python3 $D --remote user ls            # a second remote (e.g. user OAuth), if configured
```

- The first path segment decides: a shared drive name enters that drive; `@shared` is what people shared
  directly with you; anything else is a subfolder of where you start. Unsure? `drives` then `ls`; never guess names.
- Google Docs download converted to txt/csv/pdf.
- You only see what was shared with your account. Missing access? Ask for that folder or drive to be shared;
  do not look for a way around it.
- **Where to share:** read the address from `info` (never give the long service-account address).
  A loose folder lets you read/edit existing files but not create new ones; a **shared drive** lets you deliver files.
