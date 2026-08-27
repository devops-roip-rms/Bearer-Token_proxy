#!/usr/bin/env bash
set -euo pipefail

docker build \
  --build-arg APP_VERSION="$VERSION" \
  --label org.opencontainers.image.revision="$GITHUB_SHA" \
  --label org.opencontainers.image.source="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY" \
  -t "$IMAGE_NAME:$VERSION" \
  .