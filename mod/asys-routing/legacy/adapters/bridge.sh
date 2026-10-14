#!/usr/bin/env bash
set -euo pipefail

# Realm adapter for the Syncthing-backed Akaghef-Bridge file queue.
# All bridge filesystem knowledge stays here; callers use route.sh.

ACTION="${1:?Usage: bridge.sh health|send-packet|send-file|inbox|wait|archive ...}"
shift
ROOT="${AGMSG_BRIDGE_ROOT:-$HOME/Akaghef-Bridge}"

die() { echo "agmsg bridge: $*" >&2; exit 2; }

endpoint_side() {
  case "$1" in
    mac|mac-codex|*-mac) echo mac ;;
    windows|win|windows-codex|*-windows) echo windows ;;
    *) die "endpoint must identify mac or windows: $1" ;;
  esac
}

out_dir_for() {
  case "$(endpoint_side "$1")" in
    mac) echo "$ROOT/pending/windows_to_mac" ;;
    windows) echo "$ROOT/pending/mac_to_windows" ;;
  esac
}

in_dir_for() {
  case "$(endpoint_side "$1")" in
    mac) echo "$ROOT/pending/windows_to_mac" ;;
    windows) echo "$ROOT/pending/mac_to_windows" ;;
  esac
}

archive_dir_for() {
  local self="$1" state="$2" direction
  case "$(endpoint_side "$self")" in
    mac) direction="windows_to_mac" ;;
    windows) direction="mac_to_windows" ;;
  esac
  echo "$ROOT/$state/$direction"
}

json_field() {
  local file="$1" field="$2" escaped
  escaped=$(printf '%s' "$file" | sed "s/'/''/g")
  sqlite3 :memory: "SELECT COALESCE(json_extract(CAST(readfile('$escaped') AS TEXT), '\$.$field'), '');" 2>/dev/null || true
}

validate_packet() {
  local file="$1" escaped
  [ -f "$file" ] || die "packet not found: $file"
  escaped=$(printf '%s' "$file" | sed "s/'/''/g")
  [ "$(sqlite3 :memory: "SELECT json_valid(CAST(readfile('$escaped') AS TEXT));")" = 1 ] || die "packet is not valid JSON: $file"
}

case "$ACTION" in
  health)
    endpoint="${1:?health requires endpoint}"
    incoming="$(in_dir_for "$endpoint")"
    if [ ! -d "$ROOT" ]; then
      echo "status=failed reason=bridge_root_missing root=$ROOT"
      exit 20
    fi
    mkdir -p "$incoming"
    sync="unknown"
    if command -v pgrep >/dev/null 2>&1; then
      pgrep -f '[s]yncthing|Syncthing' >/dev/null 2>&1 && sync=running || sync=not_running
    fi
    echo "status=available realm=personal endpoint=$endpoint root=$ROOT sync=$sync"
    ;;

  send-packet)
    to="${1:?send-packet requires destination endpoint}"
    packet="${2:?send-packet requires JSON packet path}"
    validate_packet "$packet"
    out="$(out_dir_for "$to")"
    mkdir -p "$out"
    base="$(basename "$packet")"
    case "$base" in *.json) ;; *) base="$base.json" ;; esac
    tmp="$out/.$base.$$.$RANDOM.tmp"
    cp "$packet" "$tmp"
    mv "$tmp" "$out/$base"
    echo "status=queued realm=personal to=$to path=$out/$base"
    ;;

  send-file)
    to="${1:?send-file requires destination endpoint}"
    source_file="${2:?send-file requires source path}"
    [ -f "$source_file" ] || die "file not found: $source_file"
    out="$(out_dir_for "$to")/attachments"
    mkdir -p "$out"
    base="$(basename "$source_file")"
    tmp="$out/.$base.$$.$RANDOM.tmp"
    cp "$source_file" "$tmp"; mv "$tmp" "$out/$base"
    echo "status=queued realm=personal to=$to attachment=$out/$base"
    ;;

  inbox)
    self="${1:?inbox requires self endpoint}"
    quiet="${2:-}"
    incoming="$(in_dir_for "$self")"
    [ -d "$incoming" ] || { [ "$quiet" = --quiet ] || echo "No bridge messages."; exit 0; }
    count=0
    while IFS= read -r file; do
      [ -n "$file" ] || continue
      count=$((count + 1))
      printf '%s\t%s\t%s\t%s\t%s\n' \
        "$(json_field "$file" id)" \
        "$(json_field "$file" from)" \
        "$(json_field "$file" kind)" \
        "$(json_field "$file" thread)" \
        "$file"
    done < <(find "$incoming" -maxdepth 1 -type f -name '*.json' -print | sort)
    if [ "$count" -eq 0 ] && [ "$quiet" != --quiet ]; then echo "No bridge messages."; fi
    ;;

  wait)
    self="${1:?wait requires self endpoint}"
    field="${2:?wait requires JSON field}"
    expected="${3:?wait requires expected value}"
    timeout="${4:-180}"
    incoming="$(in_dir_for "$self")"
    deadline=$((SECONDS + timeout))
    while [ "$SECONDS" -lt "$deadline" ]; do
      if [ -d "$incoming" ]; then
        while IFS= read -r file; do
          [ "$(json_field "$file" "$field")" = "$expected" ] || continue
          validate_packet "$file"
          echo "$file"
          exit 0
        done < <(find "$incoming" -maxdepth 1 -type f -name '*.json' -print | sort)
      fi
      sleep 2
    done
    echo "agmsg bridge: timeout waiting for $field=$expected" >&2
    exit 30
    ;;

  archive)
    self="${1:?archive requires self endpoint}"
    packet="${2:?archive requires packet path}"
    result="${3:-done}"
    case "$result" in done|failed) ;; *) die "archive state must be done or failed" ;; esac
    validate_packet "$packet"
    incoming="$(in_dir_for "$self")"
    case "$(cd "$(dirname "$packet")" && pwd)/$(basename "$packet")" in
      "$incoming"/*) ;;
      *) die "packet is outside the active incoming mailbox: $packet" ;;
    esac
    dest="$(archive_dir_for "$self" "$result")"
    mkdir -p "$dest"
    mv "$packet" "$dest/$(basename "$packet")"
    echo "status=$result realm=personal path=$dest/$(basename "$packet")"
    ;;

  *) die "unknown action: $ACTION" ;;
esac
