#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f TAG ]]; then
  echo "ERROR: TAG file does not exist"
  exit 1
fi

VERSION="$(tr -d '[:space:]' < TAG)"

if [[ -z "$VERSION" ]]; then
  echo "ERROR: TAG file is empty"
  exit 1
fi

if [[ ! "$VERSION" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
  echo "ERROR: Invalid Docker image tag: $VERSION"
  exit 1
fi

TAR_FILE="bearer-token-api_proxy_${VERSION}.tar"

echo "version=$VERSION" >> "$GITHUB_OUTPUT"
echo "tar_file=$TAR_FILE" >> "$GITHUB_OUTPUT"

printf '%s\n' "$VERSION" > IMAGE_VERSION.txt

echo "Image version: $VERSION"