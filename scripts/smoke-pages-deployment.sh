#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
deployment_url="${1:-}"
base_url="$(node "$script_dir/pages-smoke-url.mjs" "$deployment_url")"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

request() {
  local path="$1"
  local body="$2"
  local headers="$3"
  curl --silent --show-error \
    --proto '=https' --tlsv1.2 --connect-timeout 10 --max-time 30 \
    --retry 2 --retry-all-errors \
    --output "$body" --dump-header "$headers" --write-out '%{http_code}' \
    "$base_url$path"
}

require_header() {
  local expression="$1"
  local headers="$2"
  grep -Eiq "$expression" "$headers" || { echo "Missing required header $expression." >&2; exit 1; }
}

final_headers() {
  local raw_headers="$1"
  local normalized_headers="$2"
  awk '
    function finish_block() {
      if (block ~ /^HTTP\/[0-9.]+ [0-9][0-9][0-9]/) last_block = block
      block = ""
    }
    {
      sub(/\r$/, "")
    }
    /^[[:space:]]*$/ {
      finish_block()
      next
    }
    {
      block = block $0 "\n"
    }
    END {
      if (block != "") finish_block()
      printf "%s", last_block
    }
  ' "$raw_headers" > "$normalized_headers"
  [ -s "$normalized_headers" ] || { echo 'Response did not include a final HTTP header block.' >&2; exit 1; }
}

root_status="$(request / "$work_dir/root.html" "$work_dir/root.headers")"
[ "$root_status" = '200' ] || { echo "Root returned HTTP $root_status." >&2; exit 1; }
final_headers "$work_dir/root.headers" "$work_dir/root.final.headers"
require_header '^content-type:[[:space:]]*text/html([;[:space:]]|$)' "$work_dir/root.final.headers"
for header in \
  '^x-content-type-options: nosniff' \
  '^referrer-policy: strict-origin-when-cross-origin' \
  '^x-frame-options: deny' \
  '^permissions-policy:' \
  '^content-security-policy:'; do
  require_header "$header" "$work_dir/root.final.headers"
done
grep -Eiq '<link rel="canonical" href="https://benchmark\.0x3\.dev/"' "$work_dir/root.html" || {
  echo 'Root response is missing the expected canonical URL.' >&2
  exit 1
}

not_found_status="$(request "/pages-smoke-not-found-$RANDOM" "$work_dir/404.html" "$work_dir/404.headers")"
[ "$not_found_status" = '404' ] || { echo "Unknown route returned HTTP $not_found_status." >&2; exit 1; }

robots_status="$(request /robots.txt "$work_dir/robots.txt" "$work_dir/robots.headers")"
[ "$robots_status" = '200' ] || { echo "robots.txt returned HTTP $robots_status." >&2; exit 1; }
grep -Eq '^User-agent: \*$' "$work_dir/robots.txt" || { echo 'robots.txt lacks User-agent: *.' >&2; exit 1; }
grep -Eq '^Allow: /$' "$work_dir/robots.txt" || { echo 'robots.txt lacks Allow: /.' >&2; exit 1; }

favicon_status="$(request /favicon.svg "$work_dir/favicon.svg" "$work_dir/favicon.headers")"
[ "$favicon_status" = '200' ] || { echo "favicon.svg returned HTTP $favicon_status." >&2; exit 1; }
final_headers "$work_dir/favicon.headers" "$work_dir/favicon.final.headers"
require_header '^content-type:[[:space:]]*image/svg\+xml([;[:space:]]|$)' "$work_dir/favicon.final.headers"
grep -Fq '<svg' "$work_dir/favicon.svg" || { echo 'favicon.svg response is not SVG.' >&2; exit 1; }

social_preview_status="$(request /social-preview.png "$work_dir/social-preview.png" "$work_dir/social-preview.headers")"
[ "$social_preview_status" = '200' ] || { echo "social-preview.png returned HTTP $social_preview_status." >&2; exit 1; }
final_headers "$work_dir/social-preview.headers" "$work_dir/social-preview.final.headers"
require_header '^content-type:[[:space:]]*image/png([;[:space:]]|$)' "$work_dir/social-preview.final.headers"
[ "$(od -An -tx1 -N8 "$work_dir/social-preview.png" | tr -d ' \n')" = '89504e470d0a1a0a' ] || {
  echo 'social-preview.png response does not have PNG magic bytes.' >&2
  exit 1
}

echo "Pages smoke checks passed for $base_url."
