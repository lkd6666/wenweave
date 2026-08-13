# SearXNG image search service

This directory runs an unmodified official SearXNG image as a loopback-only
dependency. It is not exposed by the application Nginx configuration.
The default domestic profile uses Baidu Images, Sogou Images, and Bing Images
through `https://cn.bing.com`. They are queried concurrently; individual
engine failures do not fail a partial JSON response. Baidu publisher-page URLs
are safely upgraded from HTTP to HTTPS only for its trusted engine results;
image originals remain HTTPS-only.

## Verify domestic sources

Before changing a production instance, create a separate verification settings
file with a throwaway secret and start the isolated service on loopback port
8089:

```bash
cd /opt/yibanpaiban/deploy/searxng
cp settings.verify.yml.example settings.verify.yml
SECRET=$(openssl rand -hex 32)
sed -i "s/replace-with-a-random-64-character-verification-secret/$SECRET/" settings.verify.yml
docker compose -p yibanpaiban-searxng-verify -f compose.verify.yaml up -d
../../backend/venv/bin/python verify_domestic_sources.py --searxng-secret "$SECRET"
docker compose -p yibanpaiban-searxng-verify -f compose.verify.yaml down
rm -f settings.verify.yml
```

The verifier checks three Chinese queries, counts raw SearXNG results and
application-eligible candidates, then reads a preview and original image with
the same fallback path used by the application. It promotes only engines with
at least six valid candidates for two queries. The current tested profile is
Baidu Images, Sogou Images, and Bing Images through `cn.bing.com`.

To switch an existing verified production service, run
`./apply-domestic-profile.sh`. It preserves `server.secret_key`, creates a
timestamped `settings.yml` backup, and recreates only the SearXNG container.

## Linux

```bash
cd /opt/yibanpaiban/deploy/searxng
cp settings.yml.example settings.yml
SECRET=$(openssl rand -hex 32)
sed -i "s/replace-with-a-random-64-character-secret/$SECRET/" settings.yml
chmod 600 settings.yml
printf 'SEARXNG_HOST_PORT=8088\nSEARXNG_SECRET=%s\n' "$SECRET" > .env
chmod 600 .env
docker compose pull
docker compose up -d
curl -fsS 'http://127.0.0.1:8088/search?q=test&categories=images&format=json' >/dev/null
```

The application and container both read the scoped `deploy/searxng/.env`, so
the SearXNG secret is not mixed with database or application credentials. Keep
`SEARXNG_BASE_URL=http://127.0.0.1:8088` in `backend/.env`. To use another
loopback port, change both `SEARXNG_HOST_PORT` and `SEARXNG_BASE_URL`. Upgrade by
reviewing a new official multi-architecture image digest, updating
`compose.yaml`, and rerunning the pull and smoke test. Do not switch to an
uncontrolled `latest` tag in production.

The default profile is for a constrained application host: one uWSGI worker,
one thread, a 320 MiB hard memory limit, a 160 MiB reservation, and 96 PIDs.
Override `SEARXNG_UWSGI_WORKERS`, `SEARXNG_UWSGI_THREADS`,
`SEARXNG_MEMORY_LIMIT`, `SEARXNG_MEMORY_RESERVATION`, or
`SEARXNG_PIDS_LIMIT` in `.env` only after measuring production traffic. A 2C2G
host can run this search sidecar at low concurrency when the database is
external; running MySQL, the application, and other services on the same 2G
machine leaves too little headroom for production traffic.

## Windows development

Copy `settings.yml.example` to the ignored `settings.yml`, replace the example
secret with a random value and put the same value in the ignored
`deploy/searxng/.env` together with `SEARXNG_HOST_PORT=8088`, start Docker Desktop,
then run:

```powershell
docker compose -f deploy/searxng/compose.yaml up -d
```

The application search deadline is four seconds. SearXNG fans out to the
enabled engines with a 3.2 second request timeout, so a slow source is skipped
while faster sources can still provide candidates.
