#!/bin/sh
set -eu

backup_passphrase="${BACKUP_ENCRYPTION_PASSPHRASE:-}"
if [ "${#backup_passphrase}" -lt 32 ]; then
  echo "BACKUP_ENCRYPTION_PASSPHRASE must contain at least 32 characters" >&2
  exit 64
fi
export BACKUP_ENCRYPTION_PASSPHRASE="${backup_passphrase}"

umask 077
mkdir -p /backups

while true; do
  stamp="$(date -u +%Y%m%d_%H%M%S)"
  plain="$(mktemp /tmp/wealthportfolio-backup.XXXXXX)"
  encrypted="/backups/backup_${stamp}.dump.enc"
  temporary="${encrypted}.tmp"

  cleanup() {
    rm -f "${plain}" "${temporary}"
  }
  trap cleanup EXIT INT TERM

  pg_dump --format=custom --no-owner --no-privileges --file="${plain}"
  openssl enc -aes-256-cbc -salt -pbkdf2 -iter 200000 -md sha256 \
    -pass env:BACKUP_ENCRYPTION_PASSPHRASE \
    -in "${plain}" \
    -out "${temporary}"
  mv "${temporary}" "${encrypted}"
  rm -f "${plain}"
  trap - EXIT INT TERM

  find /backups -type f -name 'backup_*.dump.enc' \
    -mtime "+${BACKUP_RETENTION_DAYS:-30}" -delete
  sleep "${BACKUP_INTERVAL_SECONDS:-86400}"
done
