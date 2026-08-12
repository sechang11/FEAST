#!/usr/bin/env bash
# Collect the packaged app for every platform into release/, one folder each.
#
#   bash packaging/fetch-releases.sh [run-id]
#
# Only one platform can be built on any given machine -- macOS bundles need a
# Mac, Linux bundles need Linux -- so the four builds only ever exist together
# in CI. This pulls them down into a single tree so there is one place that
# holds a complete, consistent set:
#
#   release/FEAST-windows-x64/    <- unzip and run FEAST.exe
#   release/FEAST-linux-x64/      <- ./FEAST
#   release/FEAST-macos-arm64/    <- FEAST.app  (Apple Silicon)
#   release/FEAST-macos-x64/      <- FEAST.app  (Intel Macs)
#
# With no run-id it takes the most recent successful run of build-libfeast on
# the current branch, so you cannot accidentally assemble a release out of a
# run where something was red.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
REPO="${FEAST_REPO:-sechang11/FEAST}"
OUT="$ROOT/release"

# Prefer the GitHub CLI when it is installed; otherwise fall back to the REST
# API with whatever token git already has for github.com, so this works on a
# machine with nothing extra set up.
HAVE_GH=0
command -v gh >/dev/null 2>&1 && HAVE_GH=1
TOKEN=""
if [ "$HAVE_GH" -eq 0 ]; then
  TOKEN="${GITHUB_TOKEN:-$(printf 'protocol=https\nhost=github.com\n\n' \
          | git credential fill 2>/dev/null | sed -n 's/^password=//p')}"
  [ -n "$TOKEN" ] || {
    echo "no gh CLI and no GitHub token. Install gh, set GITHUB_TOKEN, or" >&2
    echo "download the artifacts from https://github.com/$REPO/actions" >&2
    exit 1
  }
fi

api() { curl -sL -H "Authorization: Bearer $TOKEN" "$@"; }

RUN="${1:-}"
if [ -z "$RUN" ]; then
  if [ "$HAVE_GH" -eq 1 ]; then
    RUN="$(gh run list --repo "$REPO" --workflow build-libfeast \
             --status success --limit 1 --json databaseId --jq '.[0].databaseId')"
  else
    RUN="$(api "https://api.github.com/repos/$REPO/actions/workflows/build-libfeast.yml/runs?status=success&per_page=1" \
           | python -c 'import json,sys; r=json.load(sys.stdin)["workflow_runs"]; print(r[0]["id"] if r else "")')"
  fi
  [ -n "$RUN" ] || { echo "no successful build-libfeast run found" >&2; exit 1; }
fi
echo "collecting from run $RUN"

mkdir -p "$OUT"
for arch in windows-x64 linux-x64 macos-arm64 macos-x64; do
  dest="$OUT/FEAST-$arch"
  echo "  $arch ..."
  rm -rf "$dest"
  mkdir -p "$dest"
  got=1
  if [ "$HAVE_GH" -eq 1 ]; then
    gh run download "$RUN" --repo "$REPO" --name "FEAST-app-$arch" \
       --dir "$dest" 2>/dev/null || got=0
  else
    aid="$(api "https://api.github.com/repos/$REPO/actions/runs/$RUN/artifacts?per_page=100" \
           | python -c "
import json,sys
want='FEAST-app-$arch'
print(next((str(a['id']) for a in json.load(sys.stdin)['artifacts']
            if a['name']==want), ''))")"
    if [ -n "$aid" ]; then
      zip="$dest/.artifact.zip"
      api -o "$zip" \
        "https://api.github.com/repos/$REPO/actions/artifacts/$aid/zip" \
        && python -c "
import zipfile,sys
zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$zip" "$dest" || got=0
      rm -f "$zip"
    else
      got=0
    fi
  fi
  if [ "$got" -eq 0 ]; then
    echo "     no artifact FEAST-app-$arch in this run -- skipped"
    rm -rf "$dest"
    continue
  fi
  # An artifact may arrive with its top directory still wrapped around it.
  if [ -d "$dest/FEAST-$arch" ]; then
    mv "$dest/FEAST-$arch"/* "$dest"/ 2>/dev/null || true
    rmdir "$dest/FEAST-$arch" 2>/dev/null || true
  fi
  # The Unix launchers lose their executable bit travelling through a zip.
  for exe in "$dest/FEAST" "$dest/FEAST.app/Contents/MacOS/FEAST"; do
    [ -f "$exe" ] && chmod +x "$exe"
  done
  echo "     $(du -sh "$dest" | cut -f1)"
done

echo
echo "release tree:"
for d in "$OUT"/*/; do
  [ -d "$d" ] || continue
  printf '  %-28s %s\n' "$(basename "$d")" "$(du -sh "$d" | cut -f1)"
done
echo
echo "Note: macOS bundles are unsigned. Until they are notarized, a Mac will"
echo "refuse to open one downloaded through a browser -- right-click > Open, or"
echo "xattr -dr com.apple.quarantine FEAST.app"
