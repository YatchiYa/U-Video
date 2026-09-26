#!/bin/sh
# Prepare the data folders, then run as the host user (UGC_UID/UGC_GID) so files written to the bind-mounted
# outputs/models folders stay editable on the host. Tool environments created by `ugc setup` persist in
# $UGC_VENDOR together with the Python interpreters uv installs for them.
set -e
UID_="${UGC_UID:-1000}"
GID_="${UGC_GID:-1000}"
export HOME=/data/home UV_PYTHON_INSTALL_DIR="$UGC_VENDOR/python" UV_CACHE_DIR=/tmp/uv-cache  # cache dies with the container
mkdir -p "$UGC_OUTPUTS" "$UGC_VENDOR" "$HF_HOME" "$HOME"
for d in "$UGC_VENDOR" "$HF_HOME" "$HOME" "$UGC_OUTPUTS"; do
  [ "$(stat -c %u "$d")" = "$UID_" ] || chown "$UID_:$GID_" "$d"
done
if [ "$(id -u)" = "0" ] && [ "$UID_" != "0" ]; then
  exec setpriv --reuid="$UID_" --regid="$GID_" --clear-groups "$@"
fi
exec "$@"
