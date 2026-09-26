#!/bin/sh
# Next.js resolves `rewrites` at build time: the image is built with a placeholder API address and this script
# writes the real one (UGC_API_URL, e.g. http://api:8000) into the built server files at every start.
set -e
PLACEHOLDER="http://ugc-api-url-placeholder:8000"
TARGET="${UGC_API_URL:-http://api:8000}"
TARGET="${TARGET%/}"
for f in server.js .next/routes-manifest.json .next/required-server-files.json; do
  if [ -f "$f.orig" ]; then
    sed "s#${PLACEHOLDER}#${TARGET}#g" "$f.orig" > "$f"
  fi
done
echo "UGC Studio web -> API at ${TARGET}"
exec "$@"
