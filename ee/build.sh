#!/bin/bash
# Build the vme-stack EE from the COMMITTED code (git archive), so logs,
# rendered seeds and other local files under ansible/build never get in.
#
#   ee/build.sh
#       local build for this machine -> vme-stack-ee:<ee/VERSION> and :latest
#   PLATFORMS=linux/amd64,linux/arm64 IMAGE=ghcr.io/<owner>/vme-stack-ee ee/build.sh
#       multi-arch build with docker buildx, pushed as $IMAGE:<version> and :latest
#       (needs a buildx builder with those platforms, e.g. QEMU on CI;
#        PUSH=false builds all platforms without pushing)
#
# Optional: VME_TESTED (label), VME_SOURCE (repo URL label, links the GHCR package).
set -euo pipefail
cd "$(dirname "$0")"
VERSION=$(cat VERSION)
TESTED=${VME_TESTED:-"VME 9.1.0, hvmcli 1.0.0, HPE_HVM_Install_26.04_S6E64-11270"}

rm -rf _stage context
mkdir -p _stage/code
git -C .. archive --format=tar HEAD ansible | tar -x -C _stage/code --strip-components=1
echo "$VERSION" > _stage/code/VERSION

# ansible-builder writes the build context (Dockerfile + files); the build itself
# is a plain docker build, so local and multi-arch builds use the same context.
ansible-builder create -f execution-environment.yml --context context --output-filename Dockerfile -v 1
rm -rf _stage

BUILD_ARGS=(--build-arg VME_STACK_VERSION="$VERSION" --build-arg VME_TESTED="$TESTED"
            --build-arg VME_SOURCE="${VME_SOURCE:-}")
# Pass a proxy from the environment into the build (Docker's predefined proxy args).
for v in HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy; do
  [ -n "${!v:-}" ] && BUILD_ARGS+=(--build-arg "$v=${!v}")
done

if [ -n "${PLATFORMS:-}" ]; then
  : "${IMAGE:?set IMAGE (e.g. ghcr.io/<owner>/vme-stack-ee) for a multi-arch build}"
  # PUSH=false: build all platforms but keep nothing (checks the build only).
  if [ "${PUSH:-true}" = true ]; then OUT=(--push); else OUT=(--output type=cacheonly); fi
  docker buildx build --platform "$PLATFORMS" "${BUILD_ARGS[@]}" \
    -t "$IMAGE:$VERSION" -t "$IMAGE:latest" "${OUT[@]}" context
else
  docker build "${BUILD_ARGS[@]}" -t "vme-stack-ee:$VERSION" -t vme-stack-ee:latest context
fi
