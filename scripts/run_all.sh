#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

docker compose up -d

ready=0
for _ in $(seq 1 60); do
  if docker compose exec -T hive beeline -u 'jdbc:hive2://localhost:10000/' -e 'SHOW DATABASES;' >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 5
done
if [ "$ready" -ne 1 ]; then
  echo 'HiveServer2 did not become ready. Inspect: docker compose logs hive' >&2
  exit 1
fi

for file in \
  01_create_tables.sql \
  02_load_raw.sql \
  03_build_dwd.sql \
  04_build_dws.sql \
  05_build_ads.sql \
  06_quality_checks.sql \
  07_assert_quality.sql; do
  echo "Running $file"
  docker compose exec -T hive beeline -u 'jdbc:hive2://localhost:10000/' -f "/project/sql/$file"
done

echo 'Pipeline finished. Compare dashboard rows with data/expected_dashboard.csv.'
