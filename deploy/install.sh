#!/usr/bin/env bash
# Pi Dashboard — installation sur Raspberry Pi OS with Desktop 64-bit.
#
# Ce script utilise l'environnement graphique existant (labwc/Wayfire/LXDE) :
# il n'installe ni Xorg, ni Openbox, ni LightDM, ni un second bureau. Il crée
# le service backend, son utilisateur système et l'autostart du kiosque pour
# l'utilisateur du bureau.

set -Eeuo pipefail
IFS=$'\n\t'

APP_NAME="Pi Dashboard"
APP_DIR="/opt/pi-dashboard"
CONFIG_DIR="/etc/pi-dashboard"
CONFIG_FILE="$CONFIG_DIR/config.json"
STATE_DIR="/var/lib/pi-dashboard"
SERVICE_USER="pi-dashboard"
SERVICE_FILE="/etc/systemd/system/pi-dashboard.service"
UPDATE_SERVICE_FILE="/etc/systemd/system/pi-dashboard-update.service"
UPDATE_TIMER_FILE="/etc/systemd/system/pi-dashboard-update.timer"
UPDATE_CONFIG_FILE="$CONFIG_DIR/update.json"
UPDATE_COMMAND="/usr/local/bin/pi-dashboard-update"
KIOSK_COMMAND="/usr/local/bin/pi-dashboard-kiosk"
SLEEP_MARKER="$CONFIG_DIR/sleep-mask-units"
MARK_BEGIN="# BEGIN pi-dashboard-kiosk"
MARK_END="# END pi-dashboard-kiosk"

# Sera remplacé par le dépôt GitHub réel lors de la publication. Une valeur
# vide désactive proprement l'auto-update au lieu d'inventer un dépôt.
DEFAULT_UPDATE_REPOSITORY="skyfoxmcdev/Pi-Dashboard"

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KIOSK_USER_OPTION=""
KIOSK_AUTOSTART="auto"
ENABLE_AUTOLOGIN=0
SKIP_KIOSK=0
DRY_RUN=0
CONFIG_SOURCE=""
CONFIG_EXPLICIT=0
UPDATE_REPOSITORY="$DEFAULT_UPDATE_REPOSITORY"
AUTO_UPDATE_OPTION=""

trap 'printf "\n\033[31mInstallation interrompue (ligne %s).\033[0m\n" "$LINENO" >&2' ERR

log() {
  printf '\033[36m[Pi Dashboard]\033[0m %s\n' "$*"
}

warn() {
  printf '\033[33m[Attention]\033[0m %s\n' "$*" >&2
}

die() {
  printf '\033[31m[Erreur]\033[0m %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage : sudo bash deploy/install.sh [options]

Options :
  --kiosk-user UTILISATEUR   utilisateur du bureau qui lance le kiosque
  --kiosk-autostart MODE     auto | labwc | xdg | none  (défaut : auto)
  --enable-autologin         active l'auto-login graphique via raspi-config
  --skip-kiosk               installe uniquement le backend, sans kiosque
  --config FICHIER           utilise ce config.json (ex. config/config.json)
  --update-repo PROPRIETAIRE/DEPOT
                             dépôt GitHub des releases automatiques
  --no-auto-update           installe le service sans activer la minuterie
  --dry-run                  vérifie et affiche le plan sans rien modifier
  -h, --help                 affiche cette aide

Après l'installation, renseignez location.latitude et location.longitude dans
/etc/pi-dashboard/config.json puis : sudo systemctl restart pi-dashboard

Mise à jour automatique : sudo pi-dashboard-update check
EOF
}

while (($# > 0)); do
  case "$1" in
    --kiosk-user)
      [[ $# -ge 2 ]] || die "--kiosk-user attend un nom d'utilisateur."
      KIOSK_USER_OPTION="$2"
      shift 2
      ;;
    --kiosk-autostart)
      [[ $# -ge 2 ]] || die "--kiosk-autostart attend un mode."
      KIOSK_AUTOSTART="$2"
      shift 2
      ;;
    --enable-autologin)
      ENABLE_AUTOLOGIN=1
      shift
      ;;
    --skip-kiosk)
      SKIP_KIOSK=1
      shift
      ;;
    --config)
      [[ $# -ge 2 ]] || die "--config attend un fichier JSON."
      CONFIG_SOURCE="$2"
      CONFIG_EXPLICIT=1
      shift 2
      ;;
    --update-repo)
      [[ $# -ge 2 ]] || die "--update-repo attend proprietaire/depot."
      UPDATE_REPOSITORY="$2"
      shift 2
      ;;
    --no-auto-update)
      AUTO_UPDATE_OPTION="0"
      shift
      ;;
    --auto-update)
      AUTO_UPDATE_OPTION="1"
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "option inconnue : $1 (--help pour l'aide)."
      ;;
  esac
done

case "$KIOSK_AUTOSTART" in
  auto|labwc|xdg|none) ;;
  *) die "--kiosk-autostart doit valoir auto, labwc, xdg ou none." ;;
esac

if [[ -n "$UPDATE_REPOSITORY" ]] \
  && [[ ! "$UPDATE_REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  die "--update-repo doit avoir la forme proprietaire/depot."
fi

if [[ -n "$CONFIG_SOURCE" ]]; then
  CONFIG_SOURCE="$(realpath -- "$CONFIG_SOURCE")" \
    || die "fichier de configuration introuvable : $CONFIG_SOURCE"
  [[ -f "$CONFIG_SOURCE" ]] || die "fichier de configuration invalide : $CONFIG_SOURCE"
fi

if ((DRY_RUN == 0)) && ((EUID != 0)); then
  die "ce script doit être exécuté avec sudo : sudo bash deploy/install.sh"
fi

# ------------------------------------------------------------------ checks OS
[[ -r /etc/os-release ]] || die "système Linux Debian/Raspberry Pi OS requis."
# shellcheck disable=SC1091
. /etc/os-release
OS_ID="${ID:-inconnu}"
CODENAME="${VERSION_CODENAME:-inconnu}"
OS_PRETTY="${PRETTY_NAME:-$OS_ID $CODENAME}"
log "Système : $OS_PRETTY"

case "$OS_ID" in
  debian|raspbian) ;;
  *) warn "distribution non reconnue (Debian/Raspberry Pi OS attendu)." ;;
esac
case "$CODENAME" in
  bookworm|trixie) ;;
  *) warn "version $CODENAME non validée ; Bookworm et Trixie sont les cibles documentées." ;;
esac

ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|arm64) ;;
  *)
    die "architecture $ARCH détectée. Le projet cible Raspberry Pi OS 64-bit (aarch64)."
    ;;
esac

command -v systemctl >/dev/null 2>&1 || die "systemd est requis."
command -v python3 >/dev/null 2>&1 || die "python3 est requis."
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' \
  || die "Python 3.9 ou supérieur est requis."

[[ -f "$SOURCE_DIR/backend/main.py" ]] || die "sources introuvables dans $SOURCE_DIR."
[[ -f "$SOURCE_DIR/frontend/index.html" ]] || die "interface introuvable dans $SOURCE_DIR."
[[ -f "$SOURCE_DIR/config/config.example.json" ]] || die "config/config.example.json introuvable."
[[ -f "$SOURCE_DIR/deploy/update/pi-dashboard-update" ]] \
  || die "commande de mise à jour introuvable dans $SOURCE_DIR."

# Priorité à la configuration personnelle locale (ignorée par Git), puis à
# l'exemple. --config permet d'importer un fichier depuis une autre machine.
if [[ -z "$CONFIG_SOURCE" ]]; then
  if [[ -f "$SOURCE_DIR/config/config.json" ]]; then
    CONFIG_SOURCE="$SOURCE_DIR/config/config.json"
  else
    CONFIG_SOURCE="$SOURCE_DIR/config/config.example.json"
  fi
fi
CONFIG_IS_EXAMPLE=0
if [[ "$CONFIG_SOURCE" == "$SOURCE_DIR/config/config.example.json" ]]; then
  CONFIG_IS_EXAMPLE=1
fi

if ((SKIP_KIOSK == 0)); then
  if ! command -v labwc >/dev/null 2>&1 \
    && ! command -v wayfire >/dev/null 2>&1 \
    && ! command -v lxsession >/dev/null 2>&1 \
    && ! command -v startlxde-pi >/dev/null 2>&1; then
    die "Raspberry Pi OS with Desktop requis : labwc, Wayfire ou LXDE introuvable.
Aucun environnement graphique ne sera installé par ce script. Utilisez une
image Raspberry Pi OS with Desktop 64-bit, ou --skip-kiosk pour le backend seul."
  fi
else
  log "Mode backend seul : le kiosque ne sera pas configuré."
fi

DEFAULT_TARGET="$(systemctl get-default 2>/dev/null || true)"
if ((SKIP_KIOSK == 0)) && [[ "$DEFAULT_TARGET" != "graphical.target" ]]; then
  warn "le démarrage par défaut est « ${DEFAULT_TARGET:-inconnu} », pas graphical.target."
  warn "Activez le bureau (raspi-config → System Options → Boot) avant de compter sur le kiosque."
fi

# ----------------------------------------------------------- desktop account
resolve_kiosk_user() {
  local candidate=""
  if [[ -n "$KIOSK_USER_OPTION" ]]; then
    candidate="$KIOSK_USER_OPTION"
  elif [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    candidate="$SUDO_USER"
  elif getent passwd pi >/dev/null 2>&1; then
    candidate="pi"
  else
    candidate="$(getent passwd 1000 | cut -d: -f1 || true)"
  fi
  [[ -n "$candidate" ]] || return 1
  getent passwd "$candidate" >/dev/null 2>&1 || return 1
  [[ "$(id -u "$candidate")" -ne 0 ]] || return 1
  printf '%s\n' "$candidate"
}

KIOSK_USER=""
KIOSK_HOME=""
KIOSK_GROUP=""
if ((SKIP_KIOSK == 0)); then
  KIOSK_USER="$(resolve_kiosk_user || true)"
  [[ -n "$KIOSK_USER" ]] || die "utilisateur du bureau introuvable. Précisez --kiosk-user."
  KIOSK_HOME="$(getent passwd "$KIOSK_USER" | cut -d: -f6)"
  KIOSK_GROUP="$(id -gn "$KIOSK_USER")"
  [[ -d "$KIOSK_HOME" ]] || die "répertoire personnel de $KIOSK_USER introuvable : $KIOSK_HOME"
  log "Utilisateur du kiosque : $KIOSK_USER ($KIOSK_HOME)"
fi

detect_autostart_mode() {
  if ((SKIP_KIOSK == 1)); then
    printf 'none\n'
    return
  fi
  if [[ "$KIOSK_AUTOSTART" != "auto" ]]; then
    printf '%s\n' "$KIOSK_AUTOSTART"
    return
  fi
  if command -v labwc >/dev/null 2>&1; then
    printf 'labwc\n'
  else
    if command -v wayfire >/dev/null 2>&1; then
      warn "session Wayfire détectée : XDG autostart est utilisé (support historique, à vérifier)."
    fi
    printf 'xdg\n'
  fi
}
AUTOSTART_MODE="$(detect_autostart_mode)"
if ((SKIP_KIOSK == 0)); then
  log "Mode d'autostart du kiosque : $AUTOSTART_MODE"
fi

# --------------------------------------------------------------- package check
has_chromium() {
  command -v chromium >/dev/null 2>&1 || command -v chromium-browser >/dev/null 2>&1
}

APT_UPDATED=0
ensure_chromium() {
  if has_chromium; then
    return
  fi
  if ((DRY_RUN == 1)); then
    log "[dry-run] installerait le paquet chromium (sans environnement graphique supplémentaire)."
    return
  fi
  log "Chromium absent : installation du paquet chromium uniquement."
  if ((APT_UPDATED == 0)); then
    apt-get update
    APT_UPDATED=1
  fi
  DEBIAN_FRONTEND=noninteractive apt-get install -y chromium \
    || die "échec de l'installation de chromium."
}

ensure_ca_certificates() {
  if dpkg -s ca-certificates >/dev/null 2>&1; then
    return
  fi
  if ((DRY_RUN == 1)); then
    log "[dry-run] installerait ca-certificates."
    return
  fi
  log "Installation de ca-certificates (requis pour HTTPS)."
  if ((APT_UPDATED == 0)); then
    apt-get update
    APT_UPDATED=1
  fi
  DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates \
    || warn "ca-certificates n'a pas pu être installé ; la météo HTTPS peut échouer."
}

if ((SKIP_KIOSK == 0)); then
  ensure_chromium
fi
ensure_ca_certificates

if ((DRY_RUN == 1)); then
  log "[dry-run] aucune modification ne sera appliquée."
  log "[dry-run] créerait le service $SERVICE_FILE et l'utilisateur $SERVICE_USER."
  log "[dry-run] copierait le projet dans $APP_DIR et la configuration dans $CONFIG_FILE."
  if [[ -n "$UPDATE_REPOSITORY" ]]; then
    log "[dry-run] installerait la minuterie de mise à jour pour $UPDATE_REPOSITORY."
  else
    log "[dry-run] laisserait l'auto-update désactivé (aucun dépôt configuré)."
  fi
  if ((SKIP_KIOSK == 0)); then
    log "[dry-run] configurerait l'autostart $AUTOSTART_MODE pour $KIOSK_USER."
  fi
  exit 0
fi

# --------------------------------------------------------------- system user
if ! getent group "$SERVICE_USER" >/dev/null 2>&1; then
  log "Création du groupe système $SERVICE_USER."
  groupadd --system "$SERVICE_USER"
fi
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  log "Création de l'utilisateur système $SERVICE_USER."
  useradd --system --gid "$SERVICE_USER" --home-dir "$STATE_DIR" \
    --shell /usr/sbin/nologin --no-create-home "$SERVICE_USER"
fi
if getent group netdev >/dev/null 2>&1; then
  usermod -aG netdev "$SERVICE_USER" 2>/dev/null || true
fi

install -d -m 0755 "$APP_DIR" "$CONFIG_DIR"
install -d -m 0755 /etc/systemd/system
install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" "$STATE_DIR"
install -d -m 0755 /usr/local/bin

# ------------------------------------------------------------------- copy app
# Si l'installateur est relancé depuis /opt/pi-dashboard, source et destination
# sont le même dossier : supprimer puis recopier détruirait l'application.
if [[ "$SOURCE_DIR" == "$APP_DIR" ]] || [[ -d "$APP_DIR" && "$SOURCE_DIR" -ef "$APP_DIR" ]]; then
  log "Réinstallation sur place : copie du code ignorée (source = $APP_DIR)."
else
  log "Copie de l'application dans $APP_DIR."
  rm -rf "$APP_DIR/backend" "$APP_DIR/frontend" "$APP_DIR/deploy" "$APP_DIR/tests"
  cp -a "$SOURCE_DIR/backend" "$APP_DIR/"
  cp -a "$SOURCE_DIR/frontend" "$APP_DIR/"
  cp -a "$SOURCE_DIR/deploy" "$APP_DIR/"
  cp -a "$SOURCE_DIR/tests" "$APP_DIR/"
  # Ne jamais copier config/config.json dans /opt : la configuration
  # personnelle reste uniquement dans /etc/pi-dashboard/config.json.
  install -d -m 0755 "$APP_DIR/config"
  install -m 0644 "$SOURCE_DIR/config/config.example.json" \
    "$APP_DIR/config/config.example.json"
  install -m 0644 "$SOURCE_DIR/README.md" "$APP_DIR/README.md"
  install -m 0644 "$SOURCE_DIR/LICENSE" "$APP_DIR/LICENSE"
fi
find "$APP_DIR" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
chmod -R a+rX "$APP_DIR"
chmod 0755 "$APP_DIR/deploy/install.sh" \
  "$APP_DIR/deploy/uninstall.sh" \
  "$APP_DIR/deploy/kiosk/launch-kiosk.sh" \
  "$APP_DIR/deploy/kiosk/pi-dashboard-kiosk" \
  "$APP_DIR/deploy/update/pi-dashboard-update"

# -------------------------------------------------------------------- config
if [[ ! -f "$CONFIG_FILE" ]]; then
  log "Création de la configuration : $CONFIG_FILE"
  install -m 0644 "$CONFIG_SOURCE" "$CONFIG_FILE"
elif ((CONFIG_EXPLICIT == 1)) && ((CONFIG_IS_EXAMPLE == 0)); then
  backup="$CONFIG_FILE.bak.$(date +%Y%m%d-%H%M%S)"
  log "Configuration fournie : sauvegarde puis remplacement de $CONFIG_FILE"
  cp -a "$CONFIG_FILE" "$backup"
  install -m 0644 "$CONFIG_SOURCE" "$CONFIG_FILE"
else
  log "Configuration existante conservée : $CONFIG_FILE"
fi
chown root:root "$CONFIG_FILE" 2>/dev/null || true

log "Validation de la configuration."
if ! (cd "$APP_DIR" && python3 -m backend.main --config "$CONFIG_FILE" --check-config); then
  die "la configuration $CONFIG_FILE est invalide. Corrigez-la avant de relancer l'installation."
fi
if python3 - "$CONFIG_FILE" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    location = json.load(handle).get("location", {})
raise SystemExit(0 if location.get("latitude") is None else 1)
PY
then
  warn "Coordonnées météo non renseignées : l'interface affichera « météo à configurer »."
fi

# -------------------------------------------------------------------- service
log "Installation du service systemd."
install -m 0644 "$SOURCE_DIR/deploy/systemd/pi-dashboard.service" "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable pi-dashboard.service >/dev/null
if ! systemctl restart pi-dashboard.service; then
  systemctl status pi-dashboard.service --no-pager -l || true
  die "le service pi-dashboard n'a pas démarré. Consultez : journalctl -u pi-dashboard -n 50"
fi

for _attempt in 1 2 3 4 5 6 7 8 9 10; do
  systemctl is-active --quiet pi-dashboard.service && break
  sleep 1
done
if ! systemctl is-active --quiet pi-dashboard.service; then
  journalctl -u pi-dashboard.service -n 40 --no-pager || true
  die "le service pi-dashboard est inactif après démarrage."
fi
APP_PORT="$(python3 - "$CONFIG_FILE" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle).get("server", {}).get("port", 8080))
PY
)"
log "Backend actif sur http://127.0.0.1:${APP_PORT}."

# --------------------------------------------------------------- auto update
log "Installation de la mise à jour automatique GitHub."
install -m 0644 "$SOURCE_DIR/deploy/systemd/pi-dashboard-update.service" \
  "$UPDATE_SERVICE_FILE"
install -m 0644 "$SOURCE_DIR/deploy/systemd/pi-dashboard-update.timer" \
  "$UPDATE_TIMER_FILE"
install -m 0755 "$SOURCE_DIR/deploy/update/pi-dashboard-update" \
  "$UPDATE_COMMAND"

UPDATE_ENABLED="$(python3 - "$UPDATE_CONFIG_FILE" "$UPDATE_REPOSITORY" \
  "$AUTO_UPDATE_OPTION" <<'PY'
import json
import os
import re
import sys

path, repository_arg, mode = sys.argv[1:4]
repository = repository_arg.strip()
existing = {}
if os.path.isfile(path):
    try:
        with open(path, encoding="utf-8") as handle:
            existing = json.load(handle)
    except (OSError, ValueError):
        existing = {}
if not repository:
    repository = str(existing.get("repository", "")).strip()
if repository and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
    raise SystemExit("dépôt GitHub invalide : " + repository)
enabled = bool(existing.get("enabled", True))
if mode == "0":
    enabled = False
elif mode == "1":
    enabled = True
if not repository:
    enabled = False
payload = {
    "enabled": enabled,
    "repository": repository,
    "channel": "release",
    "asset_prefix": "pi-dashboard",
    "checksum_asset": "SHA256SUMS",
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
print("1" if enabled else "0")
PY
)"
chown root:root "$UPDATE_CONFIG_FILE" 2>/dev/null || true
chmod 0644 "$UPDATE_CONFIG_FILE" 2>/dev/null || true
if [[ -z "$UPDATE_REPOSITORY" ]]; then
  UPDATE_REPOSITORY="$(python3 - "$UPDATE_CONFIG_FILE" <<'PY'
import json
import sys
try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        print(str(json.load(handle).get("repository", "")))
except Exception:
    print("")
PY
)"
fi
systemctl daemon-reload

if [[ "$UPDATE_ENABLED" == "1" ]]; then
  if systemctl enable --now pi-dashboard-update.timer >/dev/null 2>&1; then
    log "Mise à jour automatique activée (vérification quotidienne à 04:15)."
  else
    warn "la minuterie de mise à jour n'a pas pu être activée."
  fi
else
  systemctl disable --now pi-dashboard-update.timer >/dev/null 2>&1 || true
  if [[ -z "$UPDATE_REPOSITORY" ]]; then
    warn "aucun dépôt GitHub configuré : auto-update désactivé."
    warn "Relancez avec --update-repo proprietaire/depot pour l'activer."
  else
    warn "auto-update désactivé à la demande."
  fi
fi

# ------------------------------------------------------------ sleep / blanking
# Le blanking visuel de la session (swayidle/wlopm ou xset) est neutralisé par
# le lanceur kiosque. La mise en veille système est désactivée ici.
log "Désactivation de la mise en veille système (suspend/hibernate)."
touch "$SLEEP_MARKER"
chmod 0644 "$SLEEP_MARKER"
for unit in sleep.target suspend.target hibernate.target hybrid-sleep.target; do
  state="$(systemctl is-enabled "$unit" 2>/dev/null || true)"
  if [[ "$state" == "masked" ]]; then
    continue
  fi
  if systemctl mask "$unit" >/dev/null 2>&1; then
    if ! grep -qxF "$unit" "$SLEEP_MARKER"; then
      printf '%s\n' "$unit" >> "$SLEEP_MARKER"
    fi
    log "  $unit masqué."
  else
    warn "impossible de masquer $unit."
  fi
done

# --------------------------------------------------------------------- kiosk
remove_managed_labwc_block() {
  local file="$KIOSK_HOME/.config/labwc/autostart"
  [[ -f "$file" ]] || return 0
  if grep -qF "$MARK_BEGIN" "$file"; then
    cp -a "$file" "$file.bak.$(date +%Y%m%d-%H%M%S)"
    sed -i "/^# BEGIN pi-dashboard-kiosk$/,/^# END pi-dashboard-kiosk$/d" "$file"
  fi
}

remove_xdg_autostart() {
  rm -f "$KIOSK_HOME/.config/autostart/pi-dashboard-kiosk.desktop"
}

install_labwc_autostart() {
  local dir="$KIOSK_HOME/.config/labwc"
  local file="$dir/autostart"
  install -d -m 0755 -o "$KIOSK_USER" -g "$KIOSK_GROUP" \
    "$KIOSK_HOME/.config" "$dir"
  if [[ ! -f "$file" ]]; then
    install -m 0644 -o "$KIOSK_USER" -g "$KIOSK_GROUP" /dev/null "$file"
  else
    cp -a "$file" "$file.bak.$(date +%Y%m%d-%H%M%S)"
  fi
  sed -i "/^# BEGIN pi-dashboard-kiosk$/,/^# END pi-dashboard-kiosk$/d" "$file"
  {
    printf '\n%s\n' "$MARK_BEGIN"
    printf '%s\n' '# Bloc géré par deploy/install.sh — ne pas modifier à la main.'
    printf '%s\n' '/opt/pi-dashboard/deploy/kiosk/launch-kiosk.sh >/dev/null 2>&1 &'
    printf '%s\n' "$MARK_END"
  } >> "$file"
  chown "$KIOSK_USER:$KIOSK_GROUP" "$file"
  log "Autostart labwc : $file"
}

install_xdg_autostart() {
  local dir="$KIOSK_HOME/.config/autostart"
  install -d -m 0755 -o "$KIOSK_USER" -g "$KIOSK_GROUP" \
    "$KIOSK_HOME/.config" "$dir"
  install -m 0644 -o "$KIOSK_USER" -g "$KIOSK_GROUP" \
    "$SOURCE_DIR/deploy/kiosk/pi-dashboard-kiosk.desktop" \
    "$dir/pi-dashboard-kiosk.desktop"
  log "Autostart XDG : $dir/pi-dashboard-kiosk.desktop"
}

if ((SKIP_KIOSK == 0)); then
  ln -sfn "$APP_DIR/deploy/kiosk/pi-dashboard-kiosk" "$KIOSK_COMMAND"
  chmod 0755 "$KIOSK_COMMAND"

  remove_managed_labwc_block
  remove_xdg_autostart
  case "$AUTOSTART_MODE" in
    labwc)
      install_labwc_autostart
      ;;
    xdg)
      install_xdg_autostart
      ;;
    none)
      warn "autostart désactivé : le kiosque devra être lancé avec $KIOSK_COMMAND start."
      ;;
  esac

  # -------------------------------------------------------------- autologin
  AUTOLOGIN_USER="$(sed -n 's/^autologin-user=//p' /etc/lightdm/lightdm.conf \
  /etc/lightdm/lightdm.conf.d/*.conf 2>/dev/null | tail -n 1 || true)"
  if ((ENABLE_AUTOLOGIN == 1)); then
    if command -v raspi-config >/dev/null 2>&1; then
      log "Activation de l'auto-login graphique pour $KIOSK_USER."
      if SUDO_USER="$KIOSK_USER" raspi-config nonint do_boot_behaviour B4; then
        log "Auto-login activé."
      else
        warn "raspi-config n'a pas pu activer l'auto-login. Utilisez : sudo raspi-config nonint do_boot_behaviour B4"
      fi
    else
      warn "raspi-config introuvable ; activez l'auto-login depuis les préférences du bureau."
    fi
  elif [[ "$AUTOLOGIN_USER" != "$KIOSK_USER" ]]; then
    warn "l'auto-login graphique pour $KIOSK_USER n'est pas détecté."
    warn "Pour un démarrage kiosque automatique : sudo raspi-config nonint do_boot_behaviour B4"
  fi
else
  warn "Aucun autostart kiosque installé (--skip-kiosk)."
fi

# -------------------------------------------------------------------- summary
printf '\033[32mPi Dashboard est installé.\033[0m\n\n'
cat <<EOF
  Application      : $APP_DIR
  Configuration    : $CONFIG_FILE
  Données/cache    : $STATE_DIR
  Service          : systemctl status pi-dashboard
  Journal          : journalctl -u pi-dashboard -f
  Interface locale : http://127.0.0.1:${APP_PORT}
  Auto-update      : $([[ "$UPDATE_ENABLED" == "1" ]] && echo "activée (${UPDATE_REPOSITORY})" || echo "désactivée")

Prochaines étapes :
  1. Vérifiez les coordonnées dans $CONFIG_FILE.
  2. Lancez : sudo systemctl restart pi-dashboard
EOF

if ((SKIP_KIOSK == 0)); then
  cat <<EOF
  3. Redémarrez le Raspberry Pi (ou déconnectez/reconnectez la session
     graphique) pour que l'autostart du bureau soit pris en compte.
  4. Vérifiez le kiosque : pi-dashboard-kiosk status

Maintenance du kiosque (sans sudo, avec l'utilisateur $KIOSK_USER) :
  pi-dashboard-kiosk stop      ferme Chromium et laisse le bureau accessible
  pi-dashboard-kiosk start     relance le kiosque (terminal Desktop requis)
  pi-dashboard-kiosk restart   recharge Chromium s'il tourne (SSH possible)
  pi-dashboard-kiosk disable   désactive l'autostart pour les prochains boot
  pi-dashboard-kiosk enable    réactive l'autostart
  Depuis le kiosque : Ctrl+Alt+F2, connexion, puis « stop » ; reconnexion
  de session ou redémarrage pour relancer le kiosque.
EOF
else
  cat <<EOF
  Le kiosque n'a pas été installé (--skip-kiosk).
EOF
fi

cat <<EOF

Mise à jour :
  sudo pi-dashboard-update status
  sudo pi-dashboard-update check
  sudo pi-dashboard-update run       # télécharge et installe maintenant

Tests : cd $APP_DIR && python3 -m unittest discover -s tests -v
Désinstallation : sudo bash $APP_DIR/deploy/uninstall.sh

EOF
