#!/usr/bin/env sh
# Switch an existing SearXNG deployment to the validated domestic profile.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

SETTINGS_FILE=settings.yml
TEMPLATE_FILE=settings.domestic.yml.example

if [ ! -f "$SETTINGS_FILE" ] || [ ! -f "$TEMPLATE_FILE" ]; then
  echo "settings.yml or $TEMPLATE_FILE is missing" >&2
  exit 1
fi

SECRET=$(sed -n 's/^[[:space:]]*secret_key:[[:space:]]*"\([0-9a-fA-F]\{64\}\)"[[:space:]]*$/\1/p' "$SETTINGS_FILE" | head -n 1)
if [ -z "$SECRET" ]; then
  echo "Cannot find a 64-character hexadecimal server.secret_key in $SETTINGS_FILE" >&2
  exit 1
fi

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_FILE="$SETTINGS_FILE.bak.$STAMP"
NEXT_FILE="$SETTINGS_FILE.next"
HOST_PORT=8088
if [ -f .env ]; then
  CONFIGURED_PORT=$(sed -n 's/^SEARXNG_HOST_PORT=\([0-9][0-9]*\)$/\1/p' .env | head -n 1)
  if [ -n "$CONFIGURED_PORT" ]; then
    HOST_PORT=$CONFIGURED_PORT
  fi
fi

cp "$SETTINGS_FILE" "$BACKUP_FILE"
sed "s/replace-with-a-random-64-character-secret/$SECRET/" "$TEMPLATE_FILE" > "$NEXT_FILE"
chmod 600 "$NEXT_FILE"
mv "$NEXT_FILE" "$SETTINGS_FILE"

if ! docker compose up -d --force-recreate; then
  cp "$BACKUP_FILE" "$SETTINGS_FILE"
  docker compose up -d --force-recreate || true
  echo "Container recreation failed; restored $BACKUP_FILE" >&2
  exit 1
fi

echo "Domestic profile started. Backup: $BACKUP_FILE"
echo "Verify with: curl -fsS 'http://127.0.0.1:$HOST_PORT/search?q=%E5%9F%8E%E5%B8%82%E5%85%AC%E5%9B%AD&categories=images&format=json'"
echo "Rollback with: cp '$BACKUP_FILE' '$SETTINGS_FILE' && docker compose up -d --force-recreate"
