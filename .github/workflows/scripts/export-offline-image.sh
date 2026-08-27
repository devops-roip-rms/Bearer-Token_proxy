#!/usr/bin/env bash
set -euo pipefail

: "${VERSION:?VERSION is required}"
: "${TAR_FILE:?TAR_FILE is required}"
: "${IMAGE_NAME:?IMAGE_NAME is required}"

docker save -o "$TAR_FILE" "$IMAGE_NAME:$VERSION"

sha256sum "$TAR_FILE" > "$TAR_FILE.sha256"
printf 'IMAGE_TAG=%s\n' "$VERSION" > .env

ls -lh \
  "$TAR_FILE" \
  "$TAR_FILE.sha256" \
  IMAGE_VERSION.txt \
  .env