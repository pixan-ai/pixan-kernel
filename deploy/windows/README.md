# Windows (WSL2 + Docker Desktop)

1. Dedicated Windows account for the agent (not an admin's daily account). Sign in with it.
2. BitLocker on the system drive (IT). `install.ps1` warns if it is off.
3. Install WSL2 (`wsl --install`) and Docker Desktop with the WSL2 backend. In Docker Desktop
   settings, enable "Start Docker Desktop when you sign in".
4. Copy `.env.example` to `.env`, fill it (pin `CLIENT_IMAGE` by digest), then run
   `install.ps1` in an elevated PowerShell. It locks `.env` permissions, disables sleep on AC
   and starts the container with `restart: always`.
5. Backups: the agent's memory is the Docker volume `<AGENT_NAME>-data`. Back it up daily to
   a location IT approves, for example:
   `docker run --rm -v agent-data:/data -v C:\Backups:/b debian tar czf /b/agent-%DATE%.tgz /data`
   (automated, encrypted backups are batch 2).
6. Rollback: set `CLIENT_IMAGE` to the previous digest and `docker compose up -d`.

If the laptop is off, the agent is off. The firewall (`KERNEL_FIREWALL=1`) needs the
`NET_ADMIN`/`NET_RAW` capabilities already in `docker-compose.yml`; add internal hosts the agent
may reach to `KERNEL_EGRESS_ALLOW` / `KERNEL_EGRESS_ALLOW_CIDR`.
