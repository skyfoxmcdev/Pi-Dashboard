#!/usr/bin/env bash
# Pi Dashboard — désinstallation sur Raspberry Pi OS with Desktop.
# Par défaut, la configuration et le cache sont conservés. --purge les supprime.

set -Eeuo pipefail
IFS=$'\n\t'

APP_DIR="/opt/pi-dashboard"
CONFIG_DIR="/etc/pi-dashboard"
STATE_DIR="/var/lib/pi-dashboard"
SERVICE_USER="pi-dashboard"
SERVICE_FILE="/etc/systemd/system/pi-dashboard.service"
UPDATE_SERVICE_FILE="/etc/systemd/system/pi-dashboard-update.service"
UPDATE_TIMER_FILE="/etc/systemd/system/pi-dashboard-update.timer"
UPDATE_COMMAND="/usr/local/bin/pi-dashboard-update"
KIOSK_COMMAND="/usr/local/bin/pi-dashboard-kiosk"
SLEEP_MARKER="$CONFIG_DIR/sleep-mask-units"

PURGE=0
ASSUME_YES=0
KIOSK_USER_OPTION=""

log() { printf '\033[36m[Pi Dashboard]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[Attention]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[31m[Erreur]\033[0m %s\n' "$*" >&2; exit 1; }

while (($# > 0)); do
  case "$1" in
    --purge) PURGE=1; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    --kiosk-user) KIOSK_USER_OPTION="${2:-}"; [[ -n "$KIOSK_USER_OPTION" ]] || die "--kiosk-user attend un nom."; shift 2 ;;
    -h|--help)
      cat <<'EOF'
Usage : sudo bash deploy/uninstall.sh [options]

  --purge              supprime aussi la configuration et le cache météo
  --yes                ne demande pas de confirmation avec --purge
  --kiosk-user USER    utilisateur dont l'autostart doit être retiré
EOF
      exit 0
      ;;
    *) die "option inconnue : $1" ;;
  esac
done

((EUID == 0)) || die "exécutez avec sudo : sudo bash deploy/uninstall.sh"
[[ -r /etc/os-release ]] || warn "distribution non Debian ; poursuite prudente."

if ((PURGE == 1 && ASSUME_YES == 0)); then
  printf 'Supprimer définitivement %s et %s ? [o/N] ' "$CONFIG_DIR" "$STATE_DIR"
  read -r answer
  case "$answer" in
    o|O|oui|Oui|OUI|y|Y|yes|YES) ;;
    *) die "désinstallation annulée." ;;
  esac
fi

resolve_user() {
  local candidate=""
  if [[ -n "$KIOSK_USER_OPTION" ]]; then
    candidate="$KIOSK_USER_OPTION"
  elif [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
    candidate="$SUDO_USER"
  elif getent passwd pi >/dev/null 2>&1; then
    candidate="pi"
  else
    candidate="$(getent passwd 1000 | cut -d: -f1 || true)"
  fi
  if [[ -n "$candidate" ]] && getent passwd "$candidate" >/dev/null 2>&1; then
    printf '%s\n' "$candidate"
  fi
}

KIOSK_USER="$(resolve_user || true)"
KIOSK_HOME=""
KIOSK_GROUP=""
if [[ -n "$KIOSK_USER" ]]; then
  KIOSK_HOME="$(getent passwd "$KIOSK_USER" | cut -d: -f6)"
  KIOSK_GROUP="$(id -gn "$KIOSK_USER")"
fi

log "Arrêt de la minuterie de mise à jour automatique."
systemctl disable --now pi-dashboard-update.timer 2>/dev/null || true
systemctl stop pi-dashboard-update.service 2>/dev/null || true

log "Arrêt et désactivation du service."
systemctl stop pi-dashboard.service 2>/dev/null || true
systemctl disable pi-dashboard.service 2>/dev/null || true
rm -f "$SERVICE_FILE" "$UPDATE_SERVICE_FILE" "$UPDATE_TIMER_FILE" "$UPDATE_COMMAND"
systemctl daemon-reload

if [[ -n "$KIOSK_USER" ]] && command -v runuser >/dev/null 2>&1 && [[ -x "$KIOSK_COMMAND" ]]; then
  log "Arrêt du kiosque de $KIOSK_USER."
  runuser -u "$KIOSK_USER" -- env HOME="$KIOSK_HOME" \
    XDG_CONFIG_HOME="$KIOSK_HOME/.config" XDG_CACHE_HOME="$KIOSK_HOME/.cache" \
    "$KIOSK_COMMAND" stop >/dev/null 2>&1 || warn "le kiosque n'a pas pu être arrêté proprement."
fi

if [[ -n "$KIOSK_HOME" ]]; then
  LABWC_FILE="$KIOSK_HOME/.config/labwc/autostart"
  if [[ -f "$LABWC_FILE" ]] && grep -qF '# BEGIN pi-dashboard-kiosk' "$LABWC_FILE"; then
    log "Retrait du bloc d'autostart labwc."
    sed -i "/^# BEGIN pi-dashboard-kiosk$/,/^# END pi-dashboard-kiosk$/d" "$LABWC_FILE"
    chown "$KIOSK_USER:$KIOSK_GROUP" "$LABWC_FILE" 2>/dev/null || true
  fi
  rm -f "$KIOSK_HOME/.config/autostart/pi-dashboard-kiosk.desktop"
  rm -f "$KIOSK_HOME/.cache/pi-dashboard/chromium.pid" \
    "$KIOSK_HOME/.cache/pi-dashboard/kiosk.pid"
fi

rm -f "$KIOSK_COMMAND"

if [[ -f "$SLEEP_MARKER" ]]; then
  log "Rétablissement de la mise en veille système (unités masquées par l'installateur)."
  while IFS= read -r unit; do
    [[ -n "$unit" ]] || continue
    systemctl unmask "$unit" >/dev/null 2>&1 || warn "impossible de réactiver $unit."
  done < "$SLEEP_MARKER"
fi

log "Suppression de l'application $APP_DIR."
rm -rf "$APP_DIR"

if ((PURGE == 1)); then
  log "Suppression de la configuration et du cache."
  rm -rf "$CONFIG_DIR" "$STATE_DIR"
  if id -u "$SERVICE_USER" >/dev/null 2>&1; then
    userdel "$SERVICE_USER" 2>/dev/null || warn "impossible de supprimer l'utilisateur $SERVICE_USER."
  fi
else
  log "Configuration et cache conservés : $CONFIG_DIR, $STATE_DIR"
  log "Suppression manuelle possible : sudo rm -rf $CONFIG_DIR $STATE_DIR"
fi

cat <<EOF

Pi Dashboard a été retiré du système.
Chromium et l'environnement Raspberry Pi OS Desktop n'ont pas été modifiés.
Un redémarrage ou une reconnexion de session est conseillé pour confirmer
que le kiosque ne se relance pas.

EOF
