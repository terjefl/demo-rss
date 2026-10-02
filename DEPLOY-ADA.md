# Oppdrag til Ada: deploy demo-rss på DOCKERSRV1

demo-rss henter lydklipp fra Demo (demodemo.no) og serverer dem som private
podcast-feeder, i samme stil som `pasjonsfrukt` (podme.flagan.net) og `podimo`
(podimo.flagan.net). Gjør det på samme måte som de to.

## 0. Forutsetning

Repoet `terjefl/demo-rss` er pushet til GitHub, og workflowen
«Create and publish a Docker image» har bygget `ghcr.io/terjefl/demo-rss:latest`.
Sjekk at pakken er **public** på ghcr (som podimo), ellers får ikke DOCKERSRV1 hentet den.

## 1. Mapper og filer på DOCKERSRV1 (10.11.12.16)

```bash
mkdir -p /home/dockeradmin/docker_volumes/demorss /mnt/TNAS02_Media01/Podcast/Demo
```

`/home/dockeradmin/docker_volumes/demorss/crontab`:

```cron
*/15 5-22 * * * cd /app || exit 1; PATH=$PATH:/usr/local/bin demorss harvest >> /var/log/demorss.log 2>&1
# Empty line to please the cron gods ...
```

`/home/dockeradmin/docker_volumes/demorss/config.yaml` (chmod 600) — bygg den fra
`config.template.yaml` i repoet:

- `host: "https://demo.flagan.net"`
- `users:` med alias `terje` og en ny, lang tilfeldig secret
  (`openssl rand -hex 24`), samme mønster som podimo
- `auth.email` / `auth.password`: **Terje fyller inn selv** — ikke be om dem i chat
- `feeds:` som i malen (`morgenfugl`, `demontert`, `demo`)

## 2. Stack i Docker-repoet

`DOCKERSRV1/demorss/compose.yml`:

```yaml
services:
  demorss:
    image: ghcr.io/terjefl/demo-rss:latest
    container_name: demorss
    restart: unless-stopped
    ports:
      - "8300:8000"
    environment:
      - TZ=Europe/Oslo
    volumes:
      - /home/dockeradmin/docker_volumes/demorss/config.yaml:/app/config.yaml:ro
      - /home/dockeradmin/docker_volumes/demorss/crontab:/etc/cron.d/demorss-crontab:ro
      - /mnt/TNAS02_Media01/Podcast/Demo:/app/yield
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8000/openapi.json || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s
```

Legg til en rad i `DOCKERSRV1/README.md`, commit, og opprett stacken i Portainer
(endpoint DOCKERSRV1) via GitOps-kilden `Docker-terjef` (SourceID 3),
`ComposeFile=DOCKERSRV1/demorss/compose.yml`. Ingen auto-update/polling.
Port 8300 er sjekket ledig 2026-10-02.

## 3. Cloudflare

Public hostname `demo.flagan.net` → `http://10.11.12.16:8300` i samme tunnel og
med samme Access-oppsett som `podimo.flagan.net` / `podme.flagan.net`
(podcast-apper kan ikke logge inn i Access, så feed-stiene må slippe gjennom slik
de gjør for podimo).

## 4. Verifisering

```bash
docker exec demorss demorss harvest morgenfugl demontert   # virker uten Demo-innlogging
docker exec demorss demorss harvest demo                   # krever auth i config.yaml
curl -s -o /dev/null -w '%{http_code}\n' https://demo.flagan.net/morgenfugl            # 401
curl -s -o /dev/null -w '%{http_code}\n' "https://demo.flagan.net/morgenfugl?secret=…" # 200
```

Send Terje lenken til indekssiden `https://demo.flagan.net/?secret=…` — den har
«Overcast»-knapper for hver feed.

Feilsøking: `docker logs demorss`. «Supabase password grant failed» betyr feil
e-post/passord, eller at kontoen bruker Google/Apple-innlogging — da må
`auth.refresh_token` brukes i stedet (se README).
