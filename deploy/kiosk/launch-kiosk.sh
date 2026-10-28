#!/usr/bin/env bash
# Pi Dashboard — lanceur kiosque pour Raspberry Pi OS Desktop.
#
# Lancé par la session graphique (labwc autostart ou XDG autostart), jamais par
# root. Il attend le backend, masque le blanking de l'écran, ouvre Chromium en
# plein écran et le relance après un plantage. Un verrou flock empêche deux
# instances si plusieurs mécanismes d'autostart sont présents.

set -u
set -o pipefail

APP_DIR="/opt/pi-dashboard"
CONFIG_PATH="${PI_DASHBOARD_CONFIG:-/etc/pi-dashboard/config.json}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}/pi-dashboard"
CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}/pi-dashboard"
LOG_FILE="$CACHE_HOME/kiosk.log"
LOCK_FILE="$CACHE_HOME/kiosk.lock"
LAUNCHER_PID_FILE="$CACHE_HOME/kiosk.pid"
CHROMIUM_PID_FILE="$CACHE_HOME/chromium.pid"
STOP_FILE="$CONFIG_HOME/stop-request"
DISABLED_FILE="$CONFIG_HOME/disabled"

if [ "$(id -u)" -eq 0 ]; then
  echo "Le lanceur kiosque ne doit pas être exécuté en root." >&2
  exit 1
fi

umask 077
mkdir -p "$CONFIG_HOME" "$CACHE_HOME" "$CACHE_HOME/chromium"

# Keep the log small on a microSD card.
if [ -f "$LOG_FILE" ] && [ "$(wc -c < "$LOG_FILE" 2>/dev/null || echo 0)" -gt 1048576 ]; then
  mv -f "$LOG_FILE" "$LOG_FILE.1"
fi
exec >>"$LOG_FILE" 2>&1
echo "[$(date -Is)] lancement du kiosque Pi Dashboard (session ${XDG_SESSION_TYPE:-inconnue})"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[$(date -Is)] une instance kiosque est déjà active, sortie."
  exit 0
fi

if [ -e "$DISABLED_FILE" ]; then
  echo "[$(date -Is)] kiosque désactivé par pi-dashboard-kiosk disable."
  exit 0
fi

# A stop request only concerns the previous loop; a fresh login starts the kiosk.
rm -f "$STOP_FILE" "$CHROMIUM_PID_FILE"
printf '%s\n' "$$" > "$LAUNCHER_PID_FILE"

CHILD=""
CHROMIUM_BIN=""

log() {
  echo "[$(date -Is)] $*"
}

cleanup() {
  if [ -n "${CHILD:-}" ] && kill -0 "$CHILD" 2>/dev/null; then
    kill "$CHILD" 2>/dev/null || true
    wait "$CHILD" 2>/dev/null || true
  fi
  rm -f "$CHROMIUM_PID_FILE" "$LAUNCHER_PID_FILE"
}

trap cleanup EXIT
trap 'log "signal d’arrêt reçu"; cleanup; exit 0' INT TERM HUP

# Read the configured port without requiring jq.
PORT="$(python3 - "$CONFIG_PATH" 2>/dev/null <<'PY'
import json
import sys
try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        port = json.load(handle).get("server", {}).get("port", 8080)
    print(int(port))
except Exception:
    print(8080)
PY
)"
case "$PORT" in
  ''|*[!0-9]*) PORT=8080 ;;
esac
URL="http://127.0.0.1:${PORT}/"
HEALTH_URL="${URL}health"

backend_ready() {
  python3 - "$HEALTH_URL" >/dev/null 2>&1 <<'PY'
import sys
import urllib.request

try:
    with urllib.request.urlopen(sys.argv[1], timeout=2) as response:
        raise SystemExit(0 if response.status == 200 else 1)
except Exception:
    raise SystemExit(1)
PY
}

# Raspberry Pi OS Trixie/labwc blanks the display with swayidle + wlopm.
# On X11, xset disables the X screensaver and DPMS. The cursor is hidden by the
# dashboard page itself, which works on both Wayland and X11.
disable_blanking() {
  case "${XDG_SESSION_TYPE:-}" in
    x11|X11)
      if command -v xset >/dev/null 2>&1; then
        xset s off -dpms >/dev/null 2>&1 || true
        xset s noblank >/dev/null 2>&1 || true
      fi
      ;;
  esac

  local pid cmd
  while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
    if [[ "$cmd" == *swayidle* && "$cmd" == *wlopm* ]]; then
      log "désactivation du blanking swayidle (pid $pid)."
      kill "$pid" 2>/dev/null || true
    fi
  done < <(pgrep -x swayidle 2>/dev/null || true)
}

disable_blanking
# Catch an idle daemon started slightly later by another autostart entry.
(
  exec 9>&-
  sleep 4
  disable_blanking
) >/dev/null 2>&1 &

CHROMIUM_BIN="${PI_DASHBOARD_CHROMIUM_BIN:-}"
if [ -z "$CHROMIUM_BIN" ]; then
  CHROMIUM_BIN="$(command -v chromium || command -v chromium-browser || true)"
fi
if [ -z "$CHROMIUM_BIN" ] || [ ! -x "$CHROMIUM_BIN" ]; then
  log "Chromium introuvable. Installez le paquet chromium."
  exit 1
fi

log "attente du backend sur $HEALTH_URL"
WAIT_NOTICE=0
while ! backend_ready; do
  if [ -e "$DISABLED_FILE" ] || [ -e "$STOP_FILE" ]; then
    log "arrêt demandé pendant l’attente du backend."
    exit 0
  fi
  if [ "$WAIT_NOTICE" -eq 0 ]; then
    log "backend indisponible, nouvelle tentative toutes les 3 s."
    WAIT_NOTICE=1
  fi
  sleep 3
done
log "backend prêt."

PROFILE_DIR="$CACHE_HOME/chromium"
CHROMIUM_FLAGS=(
  --kiosk
  --noerrdialogs
  --disable-infobars
  --disable-session-crashed-bubble
  --no-first-run
  --no-default-browser-check
  --disable-background-networking
  --disable-component-update
  --disable-sync
  --disable-features=Translate,TranslateUI,MediaRouter,OptimizationHints
  --metrics-recording-only
  --password-store=basic
  --check-for-update-interval=31536000
  --window-position=0,0
  --window-size=1920,1080
  "--user-data-dir=$PROFILE_DIR"
  --disk-cache-size=33554432
)

# The target is a 1 GiB Pi 3B+. Chromium's low-end mode trims memory and
# decoration work; it can be removed here if a future release renders poorly.
MEM_TOTAL_KB="$(awk '/^MemTotal:/{print $2}' /proc/meminfo 2>/dev/null || echo 0)"
if [ "${MEM_TOTAL_KB:-0}" -lt 1500000 ]; then
  CHROMIUM_FLAGS+=(--enable-low-end-device-mode --renderer-process-limit=2)
  log "profil mémoire réduit activé (RAM totale ${MEM_TOTAL_KB} kB)."
fi

BACKOFF=5
while true; do
  if [ -e "$DISABLED_FILE" ] || [ -e "$STOP_FILE" ]; then
    log "arrêt du kiosque demandé."
    break
  fi

  START_EPOCH="$(date +%s)"
  log "démarrage de Chromium : $CHROMIUM_BIN"
  "$CHROMIUM_BIN" "${CHROMIUM_FLAGS[@]}" "$URL" 9>&- &
  CHILD=$!
  printf '%s\n' "$CHILD" > "$CHROMIUM_PID_FILE"
  wait "$CHILD"
  STATUS=$?
  CHILD=""
  rm -f "$CHROMIUM_PID_FILE"

  if [ -e "$DISABLED_FILE" ] || [ -e "$STOP_FILE" ]; then
    log "Chromium arrêté (code $STATUS), kiosque stoppé."
    break
  fi

  DURATION=$(( $(date +%s) - START_EPOCH ))
  if [ "$DURATION" -lt 10 ]; then
    BACKOFF=$(( BACKOFF * 2 ))
    if [ "$BACKOFF" -gt 60 ]; then
      BACKOFF=60
    fi
  else
    BACKOFF=5
  fi
  log "Chromium terminé (code $STATUS après ${DURATION}s), relance dans ${BACKOFF}s."
  sleep "$BACKOFF" || break
done

log "boucle kiosque terminée."
exit 0
