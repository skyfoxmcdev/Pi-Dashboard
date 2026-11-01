# Pi Dashboard

Tableau de bord d'ambiance **Dark Ambient** pour **Raspberry Pi 3B+** avec
**Raspberry Pi OS with Desktop 64-bit**, écran HDMI **1920×1080** et Chromium en
mode kiosque.

Le projet est volontairement léger : backend **Python 3**, API HTTP locale,
collecte météo en arrière-plan avec cache disque, emploi du temps **PRONOTE**
via `pronotepy`, métriques Linux et frontend **HTML/CSS/JavaScript natif** sans
framework ni CDN. L'interface utilise l'environnement graphique déjà fourni par
Raspberry Pi OS Desktop ; l'installateur n'installe ni Xorg, ni Openbox, ni
LightDM, ni un second bureau. Les mises à jour sont **automatiques** : un
service systemd vérifie chaque jour la dernière **release GitHub** et installe
l'archive après contrôle SHA-256, tests et validation de `/health`, avec
sauvegarde et rollback. Une minuterie distincte éteint la sortie HDMI selon les
plages horaires configurées.

> **État de livraison** : dépôt portable complet + installateur + auto-update.
> Aucune image système `.img` prête à flasher n'est fournie, et aucun test n'a
> été exécuté sur un Raspberry Pi physique (voir
> [Validation matérielle](#validation-matérielle)). La cible principale est
> Raspberry Pi OS Trixie Desktop (session labwc). Le support Bookworm/X11 est
> prévu par l'autostart XDG et `xset`.

Dépôt : <https://github.com/skyfoxmcdev/Pi-Dashboard>  
Dernière release : <https://github.com/skyfoxmcdev/Pi-Dashboard/releases/tag/v1.2.0>

---

## Sommaire

1. [Fonctionnalités](#fonctionnalités)
2. [Compatibilité et choix techniques](#compatibilité-et-choix-techniques)
3. [Arborescence](#arborescence)
4. [Installation sur le Raspberry Pi](#installation-sur-le-raspberry-pi)
5. [Configuration](#configuration)
6. [Services et commandes](#services-et-commandes)
7. [Kiosque, veille et maintenance](#kiosque-veille-et-maintenance)
8. [Planification de l'écran](#planification-de-lécran)
9. [Mode nuit](#mode-nuit)
10. [Emploi du temps PRONOTE](#emploi-du-temps-pronote)
11. [Fonctionnement hors ligne](#fonctionnement-hors-ligne)
12. [API locale](#api-locale)
13. [Tests exécutés](#tests-exécutés)
14. [Mise à jour](#mise-à-jour)
15. [Désinstallation](#désinstallation)
16. [Problèmes fréquents](#problèmes-fréquents)
17. [Limites connues](#limites-connues)
18. [Validation matérielle](#validation-matérielle)
19. [Code portable, installation et image système](#code-portable-installation-et-image-système)
20. [Licences et attributions](#licences-et-attributions)

---

## Fonctionnalités

- Horloge locale avec typographie imposante, jour et date en français.
- Météo actuelle : température, ressenti, humidité, vent et direction,
  précipitations, condition WMO traduite en français.
- Huit prochaines heures : heure, icône, température, probabilité de pluie.
- Cinq prochains jours : condition, icône, températures minimale et maximale.
- Lever, coucher du soleil et durée du jour.
- Wi-Fi et état Internet visibles dans la barre supérieure ; l'adresse IP et
  les métriques détaillées restent disponibles dans `/api/status`.
- CPU, mémoire, température du processeur, uptime et charge collectés pour
  l'indicateur de santé de la barre supérieure.
- Emploi du temps **PRONOTE** de la journée, ou du prochain jour de cours
  lorsque la dernière heure est passée : matière, horaire, salle, professeur,
  groupe, cours annulé et contrôle.
- Académie configurable (`pronote.academy`) et connexion ENT ou directe.
- Planification hebdomadaire de la sortie HDMI : plages de nuit et pauses de
  journée, service systemd indépendant du kiosque.
- Bulle de traduction Chromium désactivée par politique d'entreprise.
- Mode nuit visuel automatique, plages configurables traversant minuit.
- Interface Dark Ambient responsive, composition native 1920×1080, sans
  défilement vertical à cette résolution.
- Aucun rechargement complet de page : horloge locale à 1 Hz, statut interrogé
  toutes les 10 secondes par défaut.
- Curseur masqué par la page après 3 secondes d'inactivité sur le kiosque.
- Lancement automatique dans la session Desktop, relance de Chromium après un
  plantage, sortie de kiosque par commande pour la maintenance.
- Fonctionnement hors ligne avec cache météo, états d'erreur sans crash.
- Mise à jour automatique depuis les releases GitHub : contrôle quotidien,
  vérification SHA-256, tests avant installation, redémarrage et rollback en
  cas d'échec. La configuration personnelle n'est jamais remplacée.

---

## Compatibilité et choix techniques

### Système cible

| Élément | Choix |
|---|---|
| Matériel | Raspberry Pi 3 Model B+, 1 Go de RAM |
| OS | Raspberry Pi OS **with Desktop 64-bit** (Bookworm ou Trixie) |
| Session principale | Raspberry Pi OS Desktop Trixie : **Wayland/labwc** |
| Session historique | Bookworm/X11/LXDE via autostart XDG ; Wayfire non garanti |
| Navigateur | `chromium`, binaire `/usr/bin/chromium` |
| Backend | Python 3.10+ (3.11 Bookworm, 3.13 Trixie), bibliothèque standard + `pronotepy` |
| Dépendances Python | venv `/var/lib/pi-dashboard/venv`, installé par `install.sh` |
| Service | `systemd`, utilisateur système `pi-dashboard` |
| Écran | HDMI 1920×1080, mise en page prioritaire à cette résolution |

L'installateur refuse une architecture non 64-bit et vérifie la présence d'un
environnement Desktop (`labwc`, Wayfire ou LXDE). Il **n'installe pas** de
serveur X, de gestionnaire de fenêtres ou de gestionnaire de connexion
supplémentaire : la pile graphique vient de l'image Raspberry Pi OS Desktop.
Seul le paquet `chromium` est installé s'il manque, ainsi que
`ca-certificates` si nécessaire.

### Pourquoi `http.server` ?

Le backend est un serveur local à un seul client de confiance, sur
`127.0.0.1`. `ThreadingHTTPServer` de la bibliothèque standard suffit :
aucune dépendance, démarrage immédiat, quelques dizaines de Mo de RSS au lieu
d'un serveur applicatif complet. Ses limites sont assumées : pas de TLS, pas de
répartition de charge, pas d'authentification, pas de compression dynamique.
Le serveur refuse de se lier ailleurs que sur la boucle locale.

### Pourquoi pas de framework frontend ?

HTML, CSS et JavaScript natif réduisent la mémoire, le temps de démarrage et
les dépendances sur une carte microSD. Les icônes sont des SVG inline, la
police Inter est embarquée localement (OFL, 48 Ko), et aucun appel réseau n'est
fait par le navigateur en dehors de `/api/status`. Aucun CDN n'est requis.

### Choix de collecte

- La météo est récupérée par un **thread backend** toutes les 15 minutes par
  défaut ; le frontend ne contacte jamais Open-Meteo.
- PRONOTE est interrogé par un **thread backend** séparé, avec un cache de
  15 minutes par défaut ; un échec conserve le dernier emploi du temps.
- Les métriques `/proc` et `/sys` sont mises en cache 2 secondes.
- La planification HDMI est évaluée chaque minute par un service oneshot
  `pi-dashboard-display.service`, sans requête réseau.
- Le Wi-Fi et l'IP sont mis en cache 15 secondes pour éviter de lancer des
  commandes à chaque sondage.
- Aucune commande n'utilise `shell=True`. Les commandes réseau sont des listes
  d'arguments statiques avec un délai maximal.
- Le cache météo est écrit de manière atomique dans
  `/var/lib/pi-dashboard/weather-cache.json`.

### Performance

- Un seul processus Python pour le backend, plus Chromium et la session
  Desktop.
- Pas d'animation continue coûteuse ; seules quelques apparitions CSS au
  chargement, désactivées en mode nuit et avec `prefers-reduced-motion`.
- Pas de blur plein écran ni de `backdrop-filter`, coûteux sur GPU ARM.
- Chronologie locale sans requête serveur ; une seule requête de statut à la
  fois par onglet.
- Chromium reçoit `--enable-low-end-device-mode` et une limite de processus de
  rendu uniquement si la RAM totale est inférieure à 1,5 Go.

Aucun chiffre de FPS ou de RSS sur Pi 3B+ n'est promis : ces mesures doivent
être faites sur le matériel réel.

---

## Arborescence

```
pi-dashboard/
├── backend/
│   ├── __init__.py          # version et nom de l'application
│   ├── config.py            # chargement, validation, fuseau, valeurs par défaut
│   ├── dashboard.py         # assemblage du contrat /api/status
│   ├── display.py           # application HDMI de la planification écran
│   ├── http_server.py       # serveur local, routes, fichiers statiques, en-têtes
│   ├── main.py              # CLI, signaux, cycle de vie
│   ├── network.py           # Wi-Fi, SSID, signal, IP
│   ├── night.py             # plage nocturne et traversée de minuit
│   ├── screen_schedule.py   # calcul des plages écran hebdomadaires
│   ├── system_metrics.py    # CPU, RAM, température, uptime, santé
│   ├── timetable.py         # PRONOTE, académies, cache, jour affiché
│   ├── updater.py           # releases GitHub, SHA-256, tests, rollback
│   ├── weather.py           # Open-Meteo, cache, thread de rafraîchissement
│   └── weather_codes.py     # WMO → français/icônes, directions du vent
├── frontend/
│   ├── index.html
│   └── assets/
│       ├── css/style.css
│       ├── fonts/InterVariable.woff2
│       ├── fonts/OFL.txt
│       ├── img/favicon.svg
│       └── js/app.js
├── config/
│   ├── config.example.json  # modèle public
│   └── config.json          # local, ignoré par Git (coordonnées et PRONOTE)
├── deploy/
│   ├── install.sh
│   ├── uninstall.sh
│   ├── chromium/policies.json
│   ├── display/pi-dashboard-display
│   ├── systemd/
│   │   ├── pi-dashboard.service
│   │   ├── pi-dashboard-display.service
│   │   ├── pi-dashboard-display.timer
│   │   ├── pi-dashboard-update.service
│   │   └── pi-dashboard-update.timer
│   ├── update/
│   │   ├── pi-dashboard-update
│   │   └── update.example.json
│   └── kiosk/
│       ├── launch-kiosk.sh
│       ├── pi-dashboard-kiosk
│       └── pi-dashboard-kiosk.desktop
├── .github/workflows/release.yml
├── requirements.txt         # pronotepy, installé dans le venv
├── tests/
│   ├── fixtures/open_meteo.json
│   ├── helpers.py
│   └── test_*.py
├── LICENSE
└── README.md
```

---

## Installation sur le Raspberry Pi

### Prérequis

1. Flash de **Raspberry Pi OS with Desktop 64-bit** avec Raspberry Pi Imager.
2. Premier démarrage, connexion Wi-Fi et mise à jour du système.
3. Le bureau doit démarrer normalement (session labwc sur Trixie).
4. Un accès SSH ou un clavier/écran pour la maintenance est recommandé.

```bash
sudo apt update
sudo apt full-upgrade
sudo reboot
```

### Copier le projet

Depuis le dépôt GitHub public :

```bash
git clone https://github.com/skyfoxmcdev/Pi-Dashboard.git
cd pi-dashboard
```

Puis copiez le dossier sur le Pi :

```bash
scp -r pi-dashboard pi@raspberrypi.local:/home/pi/
ssh pi@raspberrypi.local
cd ~/pi-dashboard
```

Ou copiez le dossier par clé USB. Les scripts doivent conserver leurs chemins
relatifs. Le dossier peut se trouver n'importe où : l'installateur le copie
dans `/opt/pi-dashboard`. Le fichier personnel `config/config.json` n'est pas
dans Git ; copiez-le séparément avec `--config` (voir ci-dessous).

### Lancer l'installateur

```bash
cd ~/pi-dashboard
sudo bash deploy/install.sh --kiosk-user pi \
  --update-repo skyfoxmcdev/Pi-Dashboard
```

Si l'utilisateur du bureau n'est pas `pi`, remplacez la valeur. L'installateur
réalise ces opérations :

- vérifie Debian/Raspberry Pi OS, l'architecture `aarch64`, la session Desktop ;
- installe uniquement `chromium` s'il manque (aucun second bureau) ;
- crée l'utilisateur système `pi-dashboard` ;
- copie l'application dans `/opt/pi-dashboard` ;
- crée le venv `/var/lib/pi-dashboard/venv` et y installe `pronotepy` et ses
  dépendances ;
- crée `/etc/pi-dashboard/config.json` à partir de `config/config.json` s'il
  existe, sinon de l'exemple, sans écraser une configuration existante ;
- protège la configuration en `0640 root:pi-dashboard` (elle peut contenir le
  mot de passe PRONOTE) et ajoute l'utilisateur du kiosque au groupe de lecture ;
- valide la configuration avec le backend ;
- installe, active et démarre `pi-dashboard.service` ;
- installe `pi-dashboard-update` et sa minuterie quotidienne ;
- installe `pi-dashboard-display` et sa minuterie de planification écran ;
- désactive la bulle de traduction Chromium par politique ;
- masque les cibles systemd de mise en veille ;
- configure l'autostart du kiosque pour l'utilisateur Desktop
  (`~/.config/labwc/autostart` en labwc, autostart XDG sinon) ;
- peut activer l'auto-login avec `--enable-autologin`, sinon affiche la
  commande à exécuter.

Options utiles :

```bash
sudo bash deploy/install.sh --dry-run          # contrôle sans modification
sudo bash deploy/install.sh --enable-autologin  # auto-login Desktop
sudo bash deploy/install.sh --skip-kiosk        # backend seul
sudo bash deploy/install.sh --kiosk-autostart xdg
sudo bash deploy/install.sh --config config/config.json
sudo bash deploy/install.sh --update-repo skyfoxmcdev/Pi-Dashboard
sudo bash deploy/install.sh --no-auto-update
```

Options complètes : `sudo bash deploy/install.sh --help`.

> L'auto-update nécessite un dépôt **public** et des **releases** publiées. Le
> workflow `.github/workflows/release.yml` crée l'archive et `SHA256SUMS`
> lorsqu'un tag `vX.Y.Z` est poussé. Le dépôt privé demanderait un jeton sur le
> Pi, ce que ce projet ne configure pas.

> **Auto-login** : pour que Chromium apparaisse sans clavier après une coupure
> de courant, activez l'auto-login Desktop :
>
> ```bash
> sudo raspi-config nonint do_boot_behaviour B4
> ```
>
> L'installateur détecte déjà un auto-login existant. Un auto-login manquant
> n'empêche pas l'installation, mais le kiosque attendra une connexion.

### Configurer le lieu

Les coordonnées ne sont **jamais** déduites d'une IP. Le fichier local
`config/config.json` est prévu pour votre installation personnelle et il est
**exclu de Git** (`config/config.json` dans `.gitignore`) afin de ne pas
publier votre localisation. Le modèle public reste
`config/config.example.json`, avec `latitude` et `longitude` à `null` :
l'interface affiche alors « météo à configurer » et n'invente aucune valeur.

Pour installer la configuration locale sur le Pi, depuis la racine du projet :

```bash
scp config/config.json pi@raspberrypi.local:/tmp/pi-dashboard-config.json
ssh pi@raspberrypi.local
cd ~/pi-dashboard
sudo bash deploy/install.sh --config /tmp/pi-dashboard-config.json \
  --kiosk-user pi --update-repo skyfoxmcdev/Pi-Dashboard
```

Ou, après installation, modifier directement :

```bash
sudo nano /etc/pi-dashboard/config.json
```

Exemple :

```json
"location": {
  "name": "Bonnefamille",
  "latitude": 45.59956,
  "longitude": 5.12489,
  "timezone": "Europe/Paris"
}
```

Puis :

```bash
sudo systemctl restart pi-dashboard
curl -s http://127.0.0.1:8080/health
```

Redémarrez le Pi (ou déconnectez/reconnectez la session graphique) pour que
l'autostart du bureau se déclenche :

```bash
sudo reboot
```

### Configurer PRONOTE

La carte « Emploi du temps » utilise `pronotepy` et les identifiants PRONOTE de
l'élève. Le mot de passe reste uniquement dans
`/etc/pi-dashboard/config.json` (droits `0640`) et n'est jamais envoyé au
navigateur ni affiché par l'API.

1. Récupérez l'URL directe de votre PRONOTE, celle qui se termine par
   `eleve.html`, `parent.html` ou équivalent. Elle ne doit pas contenir de
   paramètres de requête.
2. Renseignez `pronote.url`, `pronote.username` et `pronote.password`.
3. Choisissez le mode de connexion :
   - `"login": "ent"` pour passer par l'ENT de l'académie. `pronote.academy`
     vaut par exemple `"Grenoble"` ; l'académie de Grenoble utilise l'ENT
     Auvergne-Rhône-Alpes (`ent_auvergnerhonealpe`).
   - `"login": "direct"` si votre établissement accepte l'identifiant PRONOTE
     directement, sans ENT.
4. Si l'académie n'est pas reconnue, indiquez la fonction `pronotepy.ent` dans
   `pronote.ent` (par exemple `"ent_auvergnerhonealpe"`).

```json
"pronote": {
  "enabled": true,
  "academy": "Grenoble",
  "ent": "",
  "login": "ent",
  "url": "https://VOTRE-ETABLISSEMENT.index-education.net/pronote/eleve.html",
  "username": "VOTRE_IDENTIFIANT",
  "password": "VOTRE_MOT_DE_PASSE",
  "refresh_seconds": 900,
  "days_ahead": 7
}
```

Puis :

```bash
sudo systemctl restart pi-dashboard
journalctl -u pi-dashboard -n 40 --no-pager
```

La carte affiche l'état `À configurer` tant que les trois champs sont vides ou
incomplets. En cas d'échec de connexion, le dernier emploi du temps connu reste
affiché avec le badge `Hors ligne` ; sans cache, l'erreur PRONOTE est affichée
sans faire tomber le reste du dashboard. Le rafraîchissement est de 15 minutes
par défaut.

> Les identifiants PRONOTE sont sensibles. Ne les mettez jamais dans
> `config/config.example.json`, dans un dépôt Git, dans une capture d'écran ou
> dans une conversation. Le fichier local `config/config.json` est ignoré par
> Git ; sur le Pi, il est lisible uniquement par root et le groupe
> `pi-dashboard`.

### Vérification rapide

```bash
systemctl status pi-dashboard --no-pager
curl -s http://127.0.0.1:8080/api/status | python3 -m json.tool | head -40
pi-dashboard-kiosk status
```

---

## Configuration

Fichier : `/etc/pi-dashboard/config.json` (JSON strict, commentaires
interdits). Une configuration invalide empêche le service de démarrer et le
message est écrit dans le journal.

### Valeurs disponibles

| Clé | Défaut | Contraintes / rôle |
|---|---|---|
| `server.host` | `"127.0.0.1"` | `127.0.0.1` ou `localhost` uniquement |
| `server.port` | `8080` | 1024–65535 |
| `location.name` | « Votre ville (à configurer) » | 1–80 caractères, affiché en haut |
| `location.latitude` | `null` | -90 à 90 ; avec la longitude ou les deux `null` |
| `location.longitude` | `null` | -180 à 180 |
| `location.timezone` | `"auto"` | `auto` ou nom IANA, ex. `Europe/Paris` |
| `weather.provider` | `"open-meteo"` | seul fournisseur supporté |
| `weather.refresh_seconds` | `900` | 300–86400 (5 min à 24 h) |
| `weather.request_timeout_seconds` | `8` | 3–30 s |
| `weather.cache_file` | `/var/lib/pi-dashboard/weather-cache.json` | chemin absolu recommandé, inscriptible par le service |
| `weather.temperature_unit` | `"celsius"` | `celsius` ou `fahrenheit` |
| `weather.wind_speed_unit` | `"kmh"` | `kmh`, `ms`, `mph`, `kn` |
| `weather.precipitation_unit` | `"mm"` | `mm` ou `inch` |
| `night_mode.enabled` | `true` | booléen |
| `night_mode.start` | `"22:00"` | `HH:MM`, 24 h |
| `night_mode.end` | `"07:00"` | `HH:MM` ; peut traverser minuit |
| `screen_schedule.enabled` | `true` | active la coupure HDMI planifiée |
| `screen_schedule.off_periods` | 4 plages | liste de plages `days`, `start`, `end` |
| `pronote.enabled` | `false` | active la carte PRONOTE |
| `pronote.academy` | `""` | académie, ex. `Grenoble` |
| `pronote.ent` | `""` | override d'une fonction `pronotepy.ent` |
| `pronote.login` | `"direct"` | `direct` ou `ent` |
| `pronote.url` | `""` | URL HTTPS de l'instance PRONOTE |
| `pronote.username` / `pronote.password` | `""` | identifiants PRONOTE, jamais exposés par l'API |
| `pronote.refresh_seconds` | `900` | 300–86400 s |
| `pronote.days_ahead` | `7` | 1–14 jours de recherche du prochain jour de cours |
| `system.refresh_seconds` | `2` | 1–60 s |
| `system.thresholds.cpu_warn_percent` | `80` | seuil d'alerte CPU |
| `system.thresholds.cpu_critical_percent` | `95` | seuil critique CPU |
| `system.thresholds.memory_warn_percent` | `80` | seuil d'alerte RAM |
| `system.thresholds.memory_critical_percent` | `95` | seuil critique RAM |
| `system.thresholds.temperature_warn_c` | `70` | seuil d'alerte température CPU |
| `system.thresholds.temperature_critical_c` | `80` | seuil critique température CPU |
| `ui.poll_seconds` | `10` | 5–120 s entre deux statuts |

Les unités sont transmises à Open-Meteo (`temperature_unit`,
`wind_speed_unit`, `precipitation_unit`) ; les libellés de l'interface suivent
automatiquement (`°C`/`°F`, `km/h`/`mph`/etc.).

Le cache par défaut se trouve dans le `StateDirectory` systemd, seul chemin
inscriptible du service durci. Si vous déplacez `weather.cache_file` ailleurs,
adaptez l'unité systemd (`StateDirectory`/`ReadWritePaths`) et les droits.

### Validation manuelle

```bash
cd /opt/pi-dashboard
/var/lib/pi-dashboard/venv/bin/python -m backend.main \
  --check-config --config /etc/pi-dashboard/config.json
```

La commande affiche les avertissements, notamment les coordonnées manquantes,
et ne démarre rien.

### Open-Meteo

- Fournisseur initial : `https://api.open-meteo.com/v1/forecast`.
- Aucune clé API n'est utilisée.
- L'offre gratuite est réservée à un usage **non commercial** ; elle impose des
  limites de requêtes (< 10 000/jour, < 5 000/heure, < 600/minute) et aucune
  garantie de disponibilité. Vérifiez les conditions actuelles :
  <https://open-meteo.com/en/terms>.
- Les données sont sous licence **CC BY 4.0** ; l'attribution
  « Météo : Open-Meteo · CC BY 4.0 » est affichée dans la barre inférieure,
  avec un lien vers open-meteo.com.
- Les prévisions sont demandées avec `timezone=auto`, 6 jours (5 affichés) et
  8 prochaines heures.

---

## Services et commandes

### Backend

```bash
systemctl status pi-dashboard
journalctl -u pi-dashboard -f
sudo systemctl restart pi-dashboard
sudo systemctl stop pi-dashboard
```

Le service :

- écoute sur `http://127.0.0.1:8080` par défaut ;
- tourne sous l'utilisateur système non privilégié `pi-dashboard` ;
- redémarre automatiquement après un échec (`Restart=on-failure`) ;
- est durci par systemd (`ProtectSystem=strict`, `ProtectHome=yes`,
  `NoNewPrivileges=yes`, capacités vides) ;
- écrit uniquement dans `/var/lib/pi-dashboard` ;
- refuse de démarrer en root.

Fichiers installés :

| Élément | Chemin |
|---|---|
| Application | `/opt/pi-dashboard` |
| Configuration | `/etc/pi-dashboard/config.json` (0640, identifiants PRONOTE) |
| Cache et état | `/var/lib/pi-dashboard` |
| Venv Python | `/var/lib/pi-dashboard/venv` |
| Unité backend | `/etc/systemd/system/pi-dashboard.service` |
| Unité planification écran | `/etc/systemd/system/pi-dashboard-display.service` |
| Minuterie planification écran | `/etc/systemd/system/pi-dashboard-display.timer` |
| Politique Chromium | `/etc/chromium/policies/managed/pi-dashboard.json` |
| Minuterie auto-update | `/etc/systemd/system/pi-dashboard-update.timer` |
| Configuration auto-update | `/etc/pi-dashboard/update.json` |
| Sauvegarde de rollback | `/var/lib/pi-dashboard/update-backup` |
| Commande kiosque | `/usr/local/bin/pi-dashboard-kiosk` |
| Commande écran | `/usr/local/bin/pi-dashboard-display` |
| Commande mise à jour | `/usr/local/bin/pi-dashboard-update` |

### Kiosque

Le kiosque n'est **pas** un service systemd : il est lancé par la session
graphique existante, ce qui est le mécanisme officiel de Raspberry Pi OS
Desktop. Un service systemd ne doit pas lancer Chromium dans une session
Wayland sans session utilisateur.

Sur Raspberry Pi OS Trixie (labwc), l'installateur ajoute un bloc géré à
`~/.config/labwc/autostart` :

```sh
# BEGIN pi-dashboard-kiosk
# Bloc géré par deploy/install.sh — ne pas modifier à la main.
/opt/pi-dashboard/deploy/kiosk/launch-kiosk.sh >/dev/null 2>&1 &
# END pi-dashboard-kiosk
```

Sur une session LXDE/X11 (Bookworm), il utilise à la place
`~/.config/autostart/pi-dashboard-kiosk.desktop` (XDG autostart).

Le lanceur :

- attend que `/health` réponde avant d'ouvrir Chromium ;
- lance `/usr/bin/chromium` en `--kiosk` avec un profil dédié dans
  `~/.cache/pi-dashboard/chromium` ;
- relance Chromium après un plantage, avec back-off si les échecs sont
  rapprochés ;
- empêche deux instances avec `flock` ;
- neutralise le blanking de la session : `xset s off -dpms` en X11, arrêt du
  processus Raspberry Pi `swayidle`+`wlopm` en labwc/Wayland ;
- ajoute `--lang=fr-FR`, `--accept-lang=fr-FR,fr`, `--disable-translate` et
  installe la politique `TranslateEnabled: false` pour supprimer la bulle de
  traduction en haut à droite ;
- conserve un journal dans `~/.cache/pi-dashboard/kiosk.log` (rotation à 1 Mo).

### Commandes de maintenance du kiosque

À exécuter **sans sudo**, avec l'utilisateur du bureau :

```bash
pi-dashboard-kiosk status
pi-dashboard-kiosk stop
pi-dashboard-kiosk start
pi-dashboard-kiosk restart
pi-dashboard-kiosk disable
pi-dashboard-kiosk enable
pi-dashboard-kiosk logs
```

- `stop` ferme Chromium et le lanceur : le bureau Desktop réapparaît.
  L'autostart reste actif pour le prochain démarrage.
- `disable` empêche aussi le lancement automatique aux prochains démarrages
  (drapeau persistant).
- `enable` réactive l'autostart ; `start` ouvre immédiatement le kiosque.
- `restart` recharge Chromium si le kiosque tourne déjà, y compris depuis SSH.
  S'il est complètement arrêté, `start` doit être lancé depuis un terminal de
  la session Desktop, car Chromium a besoin de `DISPLAY`/`WAYLAND_DISPLAY`.
- Depuis le kiosque, sans SSH : `Ctrl+Alt+F2`, connectez-vous sur le TTY, puis
  `pi-dashboard-kiosk stop`. Revenez au bureau avec `Ctrl+Alt+F7` (ou la touche
  de commutation de votre session).
- Si vous préférez, activez SSH et exécutez la même commande à distance.

Le cache Chromium et le journal peuvent être supprimés sans risque lorsque le
kiosque est arrêté :

```bash
rm -rf ~/.cache/pi-dashboard/chromium
```

### Veille et écran de veille

L'installateur masque les cibles systemd `sleep.target`, `suspend.target`,
`hibernate.target` et `hybrid-sleep.target`. Il conserve la liste des unités
qu'il a masquées dans `/etc/pi-dashboard/sleep-mask-units` ; le désinstalleur
les réactive.

Le blanking de l'écran est une politique de session graphique :

- **labwc/Trixie** : Raspberry Pi OS utilise `swayidle` + `wlopm`. Le lanceur
  arrête uniquement le processus `swayidle` dont la ligne de commande contient
  `wlopm`, et refait un contrôle 4 secondes après le démarrage de session.
- **X11** : le lanceur exécute `xset s off -dpms` et `xset s noblank`.
- **Wayfire** : support historique non garanti ; vérifiez les réglages
  `[idle]` de `~/.config/wayfire.ini` si l'écran s'éteint.

Le curseur est masqué par la page elle-même après 3 secondes sans mouvement de
pointeur ; il réapparaît au moindre mouvement. Cette méthode fonctionne en
Wayland comme en X11, sans outil `unclutter`.

Raspberry Pi OS peut par ailleurs avoir ses propres réglages d'économie
d'écran ou ceux du téléviseur/moniteur. Le project ne contrôle pas la
luminosité matérielle HDMI.

---

## Planification de l'écran

Cette fonction coupe la **sortie HDMI** (le « retour vidéo ») sans arrêter le
backend, Chromium ni la session Desktop. Le Raspberry Pi continue donc de
collecter la météo, PRONOTE et les métriques ; seul l'écran ne reçoit plus de
signal.

Configuration initiale demandée :

| Jour(s) | Coupure |
|---|---|
| lundi à vendredi | `21:40` → `06:45` le lendemain |
| lundi à vendredi | `07:20` → `18:00` le jour même |
| samedi | `22:00` → `11:00` le dimanche |
| dimanche | `21:40` → `06:40` le lundi |

Le lundi matin, la plage du dimanche se termine donc à `06:40`, puis l'écran
reste allumé jusqu'à la coupure de journée à `07:20`.

```json
"screen_schedule": {
  "enabled": true,
  "off_periods": [
    {
      "days": ["mon", "tue", "wed", "thu", "fri"],
      "start": "21:40",
      "end": "06:45"
    },
    {
      "days": ["mon", "tue", "wed", "thu", "fri"],
      "start": "07:20",
      "end": "18:00"
    },
    {"days": ["sat"], "start": "22:00", "end": "11:00"},
    {"days": ["sun"], "start": "21:40", "end": "06:40"}
  ]
}
```

Chaque plage appartient à son **jour de début** : une plage `sun 21:40 → 06:40`
couvre le dimanche soir et le lundi matin. Les jours acceptent `mon`, `tue`,
`wed`, `thu`, `fri`, `sat`, `sun` (ou les noms français/anglais complets).
`start` et `end` doivent être différents ; une plage qui traverse minuit est
normale.

Commandes :

```bash
sudo pi-dashboard-display --status   # état calculé et prochaine transition
sudo systemctl status pi-dashboard-display.timer
sudo systemctl list-timers pi-dashboard-display.timer
sudo journalctl -u pi-dashboard-display -n 40
```

Le service `pi-dashboard-display.service` s'exécute chaque minute et applique
l'état avec `vcgencmd display_power 0|1` (fallback `tvservice -o|-p`). La
commande est idempotente : si l'écran est déjà dans l'état voulu, rien n'est
envoyé. Pour désactiver la planification sans supprimer le service :

```json
"screen_schedule": {"enabled": false, "off_periods": []}
```

puis `sudo systemctl restart pi-dashboard-display.service`. Le mode nuit visuel
(`night_mode`) est indépendant : il assombrit l'interface, alors que
`screen_schedule` coupe réellement le signal HDMI.

## Mode nuit

- Configuration : `night_mode.enabled`, `night_mode.start`, `night_mode.end`.
- Valeurs initiales : `22:00` → `07:00`.
- Les plages qui traversent minuit sont prises en charge ; les tests couvrent
  les bornes, `00:00`, `06:59`, `07:00` et une plage en journée.
- Si `start == end`, la plage est considérée vide (aucun effet).
- Le calcul backend suit le fuseau du système (ou le fuseau IANA explicite) ;
  le frontend recalcule chaque seconde pour basculer sans attendre un sondage.
- Effets : fond plus sombre, halos atténués, accentuation réduite, animations
  désactivées, contraste du texte préservé.

Le mode nuit est **visuel uniquement**. Aucune luminosité matérielle HDMI n'est
pilotée ; une gestion de luminosité physique devrait être un mécanisme séparé,
optionnel et désactivé par défaut. Sur un téléviseur, utilisez ses propres
réglages d'image ou une prise/commande HDMI externe.

---

## Emploi du temps PRONOTE

- Bibliothèque : [`pronotepy`](https://github.com/bain3/pronotepy), client
  communautaire non officiel, installé dans le venv par `install.sh`.
- Académie : `pronote.academy` sélectionne l'ENT régional lorsque
  `pronote.login` vaut `ent`. La correspondance est interne ; `pronote.ent`
  permet de forcer une fonction `pronotepy.ent` précise.
- L'URL PRONOTE reste celle de l'établissement : l'académie ne suffit pas à
  deviner l'instance.
- Le service interroge PRONOTE dans un thread séparé (15 minutes par défaut),
  met les cours en cache et ne bloque jamais `/api/status`.
- Sélection : l'emploi du temps du jour est affiché tant que la dernière heure
  n'est pas terminée. Ensuite, le prochain jour **avec des cours** est choisi
  dans les `days_ahead` jours (le lundi après un vendredi soir, par exemple).
- Cours annulés : conservés et barrés, avec le badge `Annulé`. Les contrôles,
  sorties et retenues sont signalés lorsqu'ils sont fournis par PRONOTE.
- Panne ou identifiants invalides : le dernier emploi du temps est conservé
  avec le badge `Hors ligne`, sinon la carte indique l'erreur. Le reste du
  dashboard continue de fonctionner.
- Les identifiants ne sont jamais renvoyés par `/api/status` ; seuls
  `enabled`, `configured`, l'état, l'académie et les cours le sont.

Vérification :

```bash
curl -s http://127.0.0.1:8080/api/status | python3 -m json.tool | sed -n '/timetable/,/ui/p'
journalctl -u pi-dashboard -f | grep -i pronote
```

---

## Fonctionnement hors ligne

- Le backend et tous les assets sont locaux : le dashboard s'affiche sans
  Internet.
- Dernière météo réussie : conservée dans
  `/var/lib/pi-dashboard/weather-cache.json`, rechargée au redémarrage.
- Si une actualisation échoue, les données en cache restent affichées avec le
  badge « Hors ligne · cache » ou « Données en cache ».
- Sans aucun cache, la carte météo indique l'indisponibilité et l'erreur, sans
  inventer de valeurs.
- Les métriques système, le Wi-Fi et l'IP continuent de fonctionner.
- La météo est retentée avec un back-off de 60 s à 600 s.
- Le frontend réessaie `/api/status` avec un back-off de 5 s à 30 s ; il
  reprend automatiquement quand le backend revient.
- État Internet : déduit de la dernière requête Open-Meteo (succès/échec), sans
  ping supplémentaire. « Inconnu » tant qu'aucune requête n'a eu lieu.

---

## API locale

Le serveur n'écoute que sur la boucle locale. Il n'y a ni authentification ni
CORS : ne l'exposez pas sur le réseau.

### `GET /health`

```json
{
  "status": "ok",
  "service": "Pi Dashboard",
  "version": "1.2.0",
  "uptime_seconds": 42,
  "weather_state": "ok",
  "time": "2026-10-28T13:15:00+01:00"
}
```

### `GET /api/status`

Réponse JSON UTF-8, sans cache HTTP (`Cache-Control: no-store`). Blocs
principaux :

- `app` : nom, version, démarrage, uptime du service.
- `generated_at`, `timezone`.
- `location` : `name`, `configured`.
- `night` : `enabled`, `active`, `start`, `end`.
- `weather` : `state` (`ok`, `stale`, `unavailable`, `unconfigured`,
  `loading`), `units`, `current`, `hourly[8]`, `daily[5]`, `sun`,
  `updated_at`, `age_seconds`, `error`, `online`.
- `system` : CPU, mémoire (octets et pourcentage), température CPU, uptime,
  charge, `health` (`level`, `label`, `reasons`).
- `network` : `wifi` (`available`, `connected`, `ssid`, `signal_percent`,
  `interface`), `ip_address`, `checked_at`, `online`.
- `screen` : `schedule_enabled`, `off`, `next_change_at`,
  `next_change_off`.
- `timetable` : `enabled`, `configured`, `state` (`ready`, `stale`,
  `loading`, `unconfigured`, `error`, `disabled`), `error`, `updated_at`,
  `academy`, `day`, `relative` (`today`, `tomorrow`, `later`), `date`,
  `weekday`, `lessons[]` (`start`, `end`, `subject`, `teacher`, `room`,
  `group`, `canceled`, `status`, `test`, `outing`, `detention`).
  Aucun identifiant PRONOTE n'est exposé.
- `ui.poll_seconds`.

Exemple :

```bash
curl -s http://127.0.0.1:8080/api/status | python3 -m json.tool
```

Autres comportements : `HEAD` supporté, méthodes d'écriture rejetées en 405,
routes inconnues en 404, tentative de traversée de répertoire bloquée. Les
en-têtes incluent CSP, `X-Content-Type-Options`, `X-Frame-Options`,
`Referrer-Policy` et `Permissions-Policy`.

---

## Tests exécutés

### Tests automatisés

Depuis la racine du projet :

```bash
cd /opt/pi-dashboard
/var/lib/pi-dashboard/venv/bin/python -m unittest discover -s tests -v
```

La suite couvre : validation de configuration (dont `screen_schedule` et
`pronote`), plages nocturnes traversant minuit, planification écran avec les
horaires demandés, construction de l'URL Open-Meteo, normalisation des données,
cache disque, bascule sur cache périmé, erreurs réseau, parseurs `/proc` et
`/sys`, santé système, Wi-Fi/IP, endpoints HTTP, en-têtes de sécurité, fichiers
statiques, traversée de répertoire, HEAD/POST, cache PRONOTE, sélection du jour
ou du prochain jour de cours, cours annulés, états d'erreur et stabilité du
dernier emploi du temps, application HDMI idempotente simulée.

Résultat réel sur la machine de développement (Windows, Python 3.15, tests
sans réseau PRONOTE) :

```
Ran 109 tests in 2.3s
OK (skipped=1)
```

Le test ignoré vérifie un fuseau IANA explicite ; la machine Windows de
développement n'a pas la base `tzdata`, contrairement à Raspberry Pi OS. Les
109 tests ont été exécutés, 108 ont réussi. Aucun test n'a été exécuté sur le
Raspberry Pi cible. La suite couvre aussi le parseur de versions, les sommes
SHA-256, l'extraction d'archives hostiles, la validation d'une release et la
configuration de l'updater, ainsi que l'application d'une mise à jour et le
rollback sur des arborescences temporaires.

### Vérifications complémentaires effectuées

```bash
python3 -m compileall -q backend tests
node --check frontend/assets/js/app.js
bash -n deploy/install.sh deploy/uninstall.sh \
  deploy/kiosk/launch-kiosk.sh deploy/kiosk/pi-dashboard-kiosk \
  deploy/update/pi-dashboard-update \
  deploy/display/pi-dashboard-display
```

Un appel réel à Open-Meteo (Bonnefamille, 45.59956/5.12489) a été effectué
avec le backend. Le client PRONOTE est couvert par des tests avec un client
simulé (cours annulés, sélection du jour ou du prochain jour, cache et erreurs).
La connexion à l'instance de démonstration publique a été tentée, mais le
compte de démonstration a refusé la connexion lors de la dernière vérification :
la connexion réelle dépend de l'établissement et doit être validée sur le Pi
avec les identifiants de l'élève. L'API `/api/status` a été interrogée en HTTP
local et l'interface a été contrôlée dans Chromium à 1920×1080 : aucun
défilement vertical, carte emploi du temps rendue, aucune erreur console.

La release GitHub `v1.1.0` a aussi été testée de bout en bout avec le vrai
updater : téléchargement HTTPS, contrôle de `SHA256SUMS`, extraction et
validation de l'archive, exécution des tests de la release, sauvegarde d'une
installation simulée en 1.0.0, application de la 1.1.0 et conservation d'une
configuration personnelle factice. La release `v1.2.0` a été récupérée depuis
l'API GitHub par ce même updater : archive `pi-dashboard-1.2.0.tar.gz`,
`SHA256SUMS` vérifié, extraction, validation de version et 109 tests exécutés
sur l'archive publiée. Le redémarrage systemd et le `/health` réel n'ont pas été
exécutés sur cette machine Windows.

**Non vérifié** : installation réelle, paquets, Wayland/labwc, autologin,
blanking, Chromium kiosque, RAM/FPS et température sur Raspberry Pi 3B+. Voir
la checklist ci-dessous.

### Tests manuels utiles sur le Pi

```bash
curl -s http://127.0.0.1:8080/health
curl -s http://127.0.0.1:8080/api/status | python3 -m json.tool
journalctl -u pi-dashboard -n 80 --no-pager
pi-dashboard-kiosk status
```

---

## Mise à jour

### Mise à jour automatique

L'installateur installe `/usr/local/bin/pi-dashboard-update`, le service
`pi-dashboard-update.service` et la minuterie `pi-dashboard-update.timer`.
La minuterie se déclenche chaque jour vers **04:15** (délai aléatoire de 45 min)
et une vérification manquée est rattrapée au prochain démarrage
(`Persistent=true`).

Le dépôt GitHub est configuré dans `/etc/pi-dashboard/update.json` :

```json
{
  "enabled": true,
  "repository": "skyfoxmcdev/Pi-Dashboard",
  "channel": "release",
  "asset_prefix": "pi-dashboard",
  "checksum_asset": "SHA256SUMS"
}
```

À chaque exécution, l'updater :

1. interroge la **dernière release** GitHub du dépôt ;
2. compare son tag à la version installée et ne fait rien si elle est déjà à
   jour ;
3. télécharge l'archive et `SHA256SUMS` en HTTPS uniquement ;
4. refuse l'archive si l'empreinte SHA-256 ou la version ne correspondent pas ;
5. extrait l'archive sans lien symbolique ni chemin `..` ;
6. exécute les tests de la nouvelle version et valide la configuration ;
7. sauvegarde l'installation actuelle dans
   `/var/lib/pi-dashboard/update-backup` ;
8. prépare le venv Python et installe `requirements.txt` dans
   `/var/lib/pi-dashboard/venv` ;
9. remplace `backend`, `frontend`, `tests`, `deploy`, `requirements.txt`,
   `README.md` et `LICENSE`, sans toucher à `/etc/pi-dashboard/config.json` ;
10. installe les unités systemd et la politique Chromium fournies par la
    release, puis recharge systemd ;
11. redémarre `pi-dashboard.service` et attend un `/health` à la nouvelle
    version ;
12. en cas d'échec, restaure la sauvegarde, redémarre l'ancienne version et
    écrit l'erreur dans le journal.

Commandes :

```bash
sudo pi-dashboard-update status    # version, dépôt, minuterie, dernier résultat
sudo pi-dashboard-update check     # dernière release disponible, sans installer
sudo pi-dashboard-update run       # télécharge et installe maintenant
sudo pi-dashboard-update disable   # suspend l'auto-update
sudo pi-dashboard-update enable    # réactive l'auto-update
sudo pi-dashboard-update rollback  # restaure la version précédente et désactive l'auto-update
journalctl -u pi-dashboard-update -n 80 --no-pager
systemctl list-timers pi-dashboard-update.timer
```

`rollback` désactive volontairement l'auto-update pour éviter de réinstaller
immédiatement la version fautive ; `enable` la réactive après correction. Un
changement de version est détecté par le frontend, qui recharge Chromium sans
commande manuelle.

### Mise à jour depuis une installation 1.1.0

La 1.2.0 introduit le venv Python, la planification HDMI et la politique
Chromium. Sur une installation 1.1.0 existante :

```bash
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip
sudo pi-dashboard-update check
sudo pi-dashboard-update run
```

Si le service de mise à jour de la 1.1.0 n'avait pas les droits d'écrire dans
`/usr/local/bin` et `/etc/chromium`, l'updater installe quand même le code et
les unités principales mais signale ces deux copies. Réappliquez alors
l'intégration système depuis la nouvelle version, sans retélécharger :

```bash
sudo bash /opt/pi-dashboard/deploy/install.sh --kiosk-user pi \
  --update-repo skyfoxmcdev/Pi-Dashboard
sudo reboot
```

Cette réinstallation sur place ne recopie pas le code (source et destination
sont identiques), mais réinstalle le venv, les unités, la politique Chromium et
l'autostart. Elle conserve `/etc/pi-dashboard/config.json`.

### Publier une nouvelle version

Le dépôt doit être **public** pour que le Pi télécharge sans jeton. Le workflow
`.github/workflows/release.yml` se déclenche sur un tag `vX.Y.Z` :

```bash
# Après avoir incrémenté __version__ dans backend/__init__.py
git add -A
git commit -m "Version 1.2.0"
git tag v1.2.0
git push origin main
git push origin v1.2.0
```

GitHub Actions exécute les tests, construit `pi-dashboard-X.Y.Z.tar.gz`, publie
`SHA256SUMS` puis crée la release. Le Pi l'installera à sa prochaine
vérification. Une release sans tag `vX.Y.Z` n'est pas prise en compte ; le canal
`main` n'est pas déployé automatiquement, précisément pour ne pas livrer une
version non testée.

### Mise à jour manuelle de secours

L'installateur est idempotent et **préserve** `/etc/pi-dashboard/config.json`.
Lancé depuis un dossier source distinct, il remplace le code, les unités et le
bloc d'autostart géré par ses soins.

```bash
cd ~/pi-dashboard
# récupérez la nouvelle version (git pull, scp, archive…)
sudo bash deploy/install.sh --kiosk-user pi \
  --update-repo skyfoxmcdev/Pi-Dashboard
```

> Relancer l'installateur depuis `/opt/pi-dashboard` réapplique les unités, le
> venv et la politique Chromium sans recopier le code (source et destination
> sont identiques). Pour remplacer le code, extrayez la nouvelle version dans
> un autre dossier, puis lancez son `deploy/install.sh`.

Pour recharger le frontend dans Chromium sans attendre la détection de version :

```bash
pi-dashboard-kiosk restart
```

Cette commande recharge Chromium via le lanceur existant, même depuis SSH. Si
le lanceur est arrêté, utilisez un terminal du bureau ou redémarrez la session.

Si l'autostart a changé de mode (labwc ↔ XDG), l'installateur retire l'ancien
mécanisme avant d'installer le nouveau. Un redémarrage complet reste la
validation la plus simple.

Mettez à jour la configuration seulement si de nouvelles clés sont nécessaires ;
les clés absentes prennent les valeurs par défaut, les clés inconnues produisent
un avertissement sans empêcher le démarrage.

---

## Désinstallation

```bash
sudo bash /opt/pi-dashboard/deploy/uninstall.sh
```

Par défaut :

- arrête et supprime le service backend ;
- arrête et retire la minuterie d'auto-update et sa commande ;
- retire l'autostart et arrête le kiosque de l'utilisateur détecté ;
- retire `/opt/pi-dashboard`, la commande `pi-dashboard-kiosk` et
  `pi-dashboard-update` ;
- réactive les unités de veille masquées par l'installateur ;
- **conserve** `/etc/pi-dashboard` et `/var/lib/pi-dashboard` (configuration et
  cache météo).

Suppression complète, y compris la configuration, le cache et l'utilisateur
système :

```bash
sudo bash /opt/pi-dashboard/deploy/uninstall.sh --purge --yes
```

Chromium, Raspberry Pi OS Desktop et l'environnement graphique ne sont pas
modifiés. Le désinstalleur ne revient pas sur l'auto-login qu'un administrateur
a éventuellement activé avec `--enable-autologin` ou `raspi-config` ; désactivez-
le séparément si nécessaire. Un redémarrage ou une reconnexion de session
confirme que le kiosque ne se relance plus.

---

## Problèmes fréquents

### La météo affiche « à configurer »

Renseignez **les deux** coordonnées et redémarrez :

```bash
sudo nano /etc/pi-dashboard/config.json
sudo systemctl restart pi-dashboard
journalctl -u pi-dashboard -n 50
```

La page affiche l'état sans fabriquer de données tant que la configuration est
incomplète.

### La météo est indisponible ou en cache

- Vérifiez Internet : `ping -c 2 api.open-meteo.com` (ou `curl -I`).
- Vérifiez l'heure et le fuseau : `timedatectl`.
- Consultez le journal : `journalctl -u pi-dashboard -f`.
- Le cache est dans `/var/lib/pi-dashboard/weather-cache.json`.
- Si le cache appartient à root ou est illisible, corrigez :
  `sudo chown -R pi-dashboard:pi-dashboard /var/lib/pi-dashboard`.
- Open-Meteo peut limiter ou interrompre le service gratuit ; l'application
  conserve alors la dernière météo avec un badge.

### PRONOTE affiche « À configurer »

La carte reste en attente tant que `pronote.url`, `pronote.username` et
`pronote.password` ne sont pas tous renseignés. Vérifiez aussi que le service
a été redémarré après la modification :

```bash
sudo systemctl restart pi-dashboard
curl -s http://127.0.0.1:8080/api/status | python3 -m json.tool | sed -n '/timetable/,/ui/p'
```

### PRONOTE refuse la connexion

- Vérifiez l'URL directe de l'établissement : elle doit finir par `eleve.html`
  ou équivalent, sans paramètre `?login=true`.
- Essayez `"login": "direct"`, puis `"login": "ent"` si l'établissement impose
  l'ENT.
- Pour Grenoble, l'académie utilise l'ENT Auvergne-Rhône-Alpes. Si l'ENT change,
  indiquez la fonction exacte dans `pronote.ent`.
- Consultez le message de la carte et le journal :
  `journalctl -u pi-dashboard -f | grep -i pronote`.
- Si le compte exige une validation en deux étapes, la connexion
  identifiant/mot de passe peut être refusée ; le support QR/token de
  `pronotepy` n'est pas exposé dans cette configuration.
- Vérifiez que le venv est intact :
  `sudo /var/lib/pi-dashboard/venv/bin/python -c "import pronotepy; print(pronotepy.__version__)"`.

### La bulle de traduction Chromium persiste

La politique est installée dans
`/etc/chromium/policies/managed/pi-dashboard.json`. Vérifiez-la :

```bash
cat /etc/chromium/policies/managed/pi-dashboard.json
```

Le contenu doit être `{"TranslateEnabled": false}`. Redémarrez Chromium
(`pi-dashboard-kiosk restart`) ; un onglet déjà ouvert peut conserver la bulle
jusqu'au rechargement. Les drapeaux `--disable-translate`,
`--disable-features=Translate,TranslateUI`, `--lang=fr-FR` et
`--accept-lang=fr-FR,fr` sont aussi passés au lanceur.

### L'écran ne se coupe pas ou ne se rallume pas

```bash
sudo pi-dashboard-display --status
sudo systemctl status pi-dashboard-display.timer
sudo journalctl -u pi-dashboard-display -n 40
sudo vcgencmd display_power
```

- Si `vcgencmd` n'est pas disponible, le service tente `tvservice -o/-p`.
- Si le moniteur ignore la coupure HDMI, vérifiez son propre mode d'économie
  d'énergie et le câble.
- La planification ne coupe que le signal vidéo : le backend et Chromium
  continuent de tourner.
- Pour suspendre temporairement la planification, passez
  `screen_schedule.enabled` à `false` puis redémarrez le service.

### Le service ne démarre pas

```bash
systemctl status pi-dashboard --no-pager -l
journalctl -u pi-dashboard -n 80 --no-pager
cd /opt/pi-dashboard
/var/lib/pi-dashboard/venv/bin/python -m backend.main \
  --check-config --config /etc/pi-dashboard/config.json
```

Causes fréquentes : JSON invalide, coordonnées seules, port occupé, cache dans
un chemin non inscriptible, droits de `/etc/pi-dashboard/config.json`.
Le service refuse de tourner en root ; c'est normal.

### Le port 8080 est déjà utilisé

```bash
sudo ss -ltnp | grep 8080
```

Changez `server.port` dans la configuration, redémarrez le service et relancez
le kiosque (le lanceur lit le port dans le fichier). N'utilisez pas un port
privilégié (< 1024).

### Le kiosque ne se lance pas après le démarrage

```bash
cat ~/.config/labwc/autostart
# ou, en session LXDE/X11 :
cat ~/.config/autostart/pi-dashboard-kiosk.desktop
tail -n 80 ~/.cache/pi-dashboard/kiosk.log
pi-dashboard-kiosk status
```

Vérifiez :

- l'auto-login Desktop (`sudo raspi-config nonint do_boot_behaviour B4`) ;
- le démarrage graphique (`systemctl get-default` doit être
  `graphical.target`) ;
- la présence de Chromium (`command -v chromium`) ;
- que la configuration est valide et le backend actif ;
- que le mode autostart correspond à la session réelle (labwc ou XDG).

Une session Wayfire historique peut nécessiter un autostart XDG ou un réglage
manuel ; la cible principale est Trixie/labwc.

### Chromium se ferme ou le kiosque redémarre en boucle

Consultez `~/.cache/pi-dashboard/kiosk.log`. Vérifiez la mémoire disponible et
la température. Le lanceur réessaie après 5 s, avec un délai croissant si les
échecs sont rapprochés. Sur 1 Go, fermez les applications de bureau inutiles.
Les drapeaux mémoire ne sont appliqués que si `MemTotal` < 1,5 Go.

### L'écran s'éteint quand même


- Vérifiez que la session est bien labwc : `echo $XDG_SESSION_TYPE`.
- Dans la session, le lanceur doit avoir arrêté `swayidle` ; vérifiez
  `pgrep -a swayidle`.
- Vérifiez que le moniteur n'a pas son propre minuteur.
- En X11, le lanceur exécute `xset s off -dpms` ; vérifiez avec
  `xset q | grep -A 2 'Screen Saver'`.
- Les cibles de veille sont masquées ; vérifiez
  `systemctl is-enabled sleep.target suspend.target`.

### Le curseur ne disparaît pas

Le masquage est fait par la page après 3 secondes **au-dessus de la page
kiosque**. Si Chromium affiche un dialogue natif ou si le bureau est visible,
le curseur reste normal. C'est volontaire.

### Le Wi-Fi ou le SSID est absent

Le backend interroge NetworkManager (`nmcli`) puis `iwgetid` si disponible.
L'utilisateur `pi-dashboard` peut ne pas avoir les mêmes droits que le bureau.
Vérifiez :

```bash
nmcli device status
iwgetid -r
cat /proc/net/wireless
journalctl -u pi-dashboard -f
```

L'interface affiche « Non détecté » plutôt que de fabriquer un réseau.

### Le dashboard est inaccessible mais le bureau fonctionne

Le kiosque n'est peut-être pas lancé, ou le backend est arrêté. Depuis un TTY
ou SSH :

```bash
pi-dashboard-kiosk status
sudo systemctl restart pi-dashboard
# Si le kiosque tourne encore, rechargez Chromium :
pi-dashboard-kiosk restart
```

Si le lanceur est arrêté, `start` doit être lancé depuis un terminal de la
session Desktop (Chromium a besoin de l'environnement graphique). Sinon,
déconnectez/reconnectez la session ou redémarrez le Pi : l'autostart s'en
charge.

---

## Limites connues

- **Aucune validation matérielle** : le projet n'a pas été installé ni mesuré
  sur un Raspberry Pi 3B+ physique. Les performances réelles (FPS, RSS,
  température, stabilité Chromium) restent à vérifier.
- **1 Go de RAM avec Desktop** : Chromium et la session graphique sont les
  postes dominants. Le mode kiosque ne supprime pas le bureau ; il le recouvre.
  Le rendu à 60 FPS n'est pas garanti, seulement visé par des choix sobres.
- **Pas de contrôle de luminosité HDMI** : `screen_schedule` coupe ou
  rallume la sortie HDMI via `vcgencmd`, mais ne règle pas la luminosité. Le
  mode nuit reste visuel.
- **Wayland/labwc** : mécanisme de blanking arrêté au niveau du processus
  `swayidle`. Une version future de Raspberry Pi OS peut changer ce nom ou ce
  comportement ; la cible testée logiquement est Trixie.
- **Wayfire** : l'autostart XDG et le blanking ne sont pas garantis ; cible
  historique, non prioritaire. La session X11/LXDE et labwc sont les chemins
  documentés.
- **Wi-Fi** : SSID, qualité et interface dépendent du pilote, de
  NetworkManager et des droits. Les valeurs manquantes sont affichées comme
  indisponibles, jamais inventées.
- **Météo** : nécessite Internet ; l'offre gratuite Open-Meteo est non
  commerciale, limitée et sans garantie. Aucune géolocalisation automatique.
  Les données WMO sont traduites localement ; les prévisions restent celles du
  fournisseur.
- **API** : HTTP local sans TLS ni authentification, volontairement limité à
  `127.0.0.1`. Ne pas l'exposer au LAN.
- **Debian/Pi OS uniquement** : les métriques `/proc` et `/sys`, `systemd` et
  les commandes réseau sont spécifiques à Linux. Le backend démarre sur une
  autre plateforme mais affiche les métriques indisponibles.
- **Systemd durci** : le cache doit rester dans le `StateDirectory`
  (`/var/lib/pi-dashboard`). Un chemin personnalisé hors de ce répertoire
  nécessite d'adapter l'unité.
- **Auto-login** : non activé silencieusement sans l'option
  `--enable-autologin` ; sans lui, le kiosque attend une connexion Desktop.
- **Kiosque** : repose sur la session graphique et Chromium ; ce n'est pas un
  environnement kiosque verrouillé au niveau noyau. Un clavier physique peut
  permettre des combinaisons système.
- **Auto-update** : dépend de GitHub, d'une release taguée et d'un dépôt
  **public**. Le contrôle SHA-256 détecte une archive corrompue ou substituée
  sur le trajet, mais ne remplace pas une signature de confiance : un dépôt
  GitHub compromis reste une surface de risque. Le canal est volontairement
  limité aux releases, pas aux commits de `main`.
- **Auto-update et configuration** : l'updater ne remplace ni
  `/etc/pi-dashboard/config.json`, ni les secrets éventuels, ni les données du
  cache. Si une nouvelle version exige une nouvelle clé de configuration, elle
  doit être ajoutée manuellement dans `/etc/pi-dashboard/config.json`.
- **Unités systemd** : l'updater tente d'installer les unités et la politique
  Chromium de la release, puis recharge systemd. Si le service de mise à jour
  d'une ancienne installation est trop restreint pour écrire ces chemins, il
  signale l'échec partiel ; relancez alors `deploy/install.sh` une fois.
- **PRONOTE** : `pronotepy` est un client communautaire non officiel. Une
  évolution de PRONOTE ou de l'ENT peut casser la connexion ; le dashboard
  conserve alors le dernier emploi du temps et affiche l'erreur. Les comptes
  protégés par une validation en deux étapes peuvent nécessiter une connexion
  QR/token non couverte par cette configuration.
- **Académies** : la correspondance automatique couvre les académies courantes
  listées dans `backend/timetable.py`. Pour les autres, utilisez
  `pronote.login=direct` ou renseignez `pronote.ent` explicitement.
- **Coupure HDMI** : `vcgencmd display_power` dépend du firmware et de la
  configuration KMS de Raspberry Pi OS. Le fallback `tvservice` est prévu,
  mais le comportement réel doit être validé sur l'écran et le câble utilisés.
- **Rollback** : conserve une seule sauvegarde de la version précédente ; un
  second échec avant correction peut la remplacer. En cas de rollback,
  l'auto-update est désactivée pour éviter une boucle.
- **Image système** : non fournie.
- **Tests** : les 109 tests ont été exécutés hors Raspberry Pi ; un test de
  fuseau IANA a été ignoré sous Windows faute de base `tzdata`. L'installation
  réelle, le redémarrage systemd, les minuteries, la coupure HDMI et le
  rechargement du kiosque n'ont pas été exécutés sur le Pi.

---

## Validation matérielle

À exécuter sur le vrai Pi 3B+ après installation :

1. `cat /etc/os-release`, `uname -m` : Raspberry Pi OS Desktop 64-bit,
   `aarch64`, Bookworm ou Trixie.
2. `systemctl get-default` : `graphical.target`.
3. `systemctl status pi-dashboard` : actif, sans erreur, redémarrage propre.
4. `curl -s http://127.0.0.1:8080/health` : `status: ok`.
5. Configurer des coordonnées réelles, vérifier météo actuelle, 8 heures,
   5 jours, lever/coucher et attribution.
6. Redémarrer le Pi et confirmer l'auto-login (s'il a été activé), l'apparition
   de Chromium en plein écran 1920×1080 et l'absence de barres de défilement.
7. Attendre plus de 10 minutes : écran non blanchi, curseur masqué après
   3 secondes, aucun dialogue Chromium.
8. Vérifier `systemctl is-enabled sleep.target suspend.target hibernate.target
   hybrid-sleep.target` : `masked`.
9. Couper le Wi-Fi : le dashboard reste affiché, la météo passe en cache et
   l'indicateur Internet devient hors ligne ; rebrancher et vérifier la reprise.
10. Tuer Chromium (`kill <pid>` du profil kiosque) et vérifier sa relance.
11. `pi-dashboard-kiosk stop` : le bureau réapparaît ; `start` depuis un
    terminal du bureau : le kiosque revient (ou reconnectez la session).
12. Mesurer la charge et la mémoire : `top`, `free -h`, `vcgencmd measure_temp`,
    `vcgencmd get_throttled`.
13. Vérifier le SSID, le signal et l'IP avec NetworkManager réel.
14. Tester le mode nuit à une heure proche de `night_mode.start`, puis une
    plage traversant minuit.
15. Vérifier les journaux : `journalctl -u pi-dashboard -f`,
    `~/.cache/pi-dashboard/kiosk.log`, aucune erreur CSP dans la console
    Chromium (`Ctrl+Shift+J` si accessible).
16. Vérifier la carte PRONOTE avec les vrais identifiants : état `À jour`,
    matières, horaires, salles, professeurs, cours annulés et bascule vers le
    prochain jour après la dernière heure.
17. Vérifier la bulle de traduction : elle ne doit plus apparaître en haut à
    droite après redémarrage de Chromium.
18. Vérifier la planification écran : `sudo pi-dashboard-display --status`,
    puis attendre une borne (par exemple `07:20`) et confirmer la coupure HDMI
    et le rallumage à `18:00`. Vérifier
    `journalctl -u pi-dashboard-display -n 40`.
19. Vérifier l'auto-update : `sudo pi-dashboard-update status`, puis
    `sudo pi-dashboard-update check` ; après publication d'une release de test,
    `sudo pi-dashboard-update run`, vérifier la nouvelle version dans
    `/health`, le rechargement du kiosque et
    `journalctl -u pi-dashboard-update -n 80`.
20. Tester `sudo pi-dashboard-update rollback` sur une release de test, puis
    `sudo pi-dashboard-update enable` après correction.

---

## Code portable, installation et image système

- **Code portable** : ce dossier. Il contient le backend, le frontend, les
  tests et les scripts. Il ne modifie pas le système tant que l'installateur
  n'est pas exécuté. Les tests peuvent tourner sur une autre machine.
- **Dépôt GitHub** : les releases publiques servent de source à l'auto-update.
  Le workflow joint l'archive et `SHA256SUMS` à chaque tag `vX.Y.Z`.
- **Installation** : `deploy/install.sh` copie le code dans `/opt`, crée
  l'utilisateur et le service, configure l'autostart du Desktop, la
  configuration système et la minuterie de mise à jour. C'est ce que
  l'installateur réalise réellement.
- **Image système complète** : un fichier `.img` (ou `.img.xz`) prêt à flasher,
  incluant OS, paquets, configuration et données. **Aucune image n'est
  produite ni livrée ici.** Pour en fabriquer une, il faudrait flasher
  Raspberry Pi OS Desktop 64-bit, exécuter cet installateur, configurer les
  coordonnées et les secrets éventuels, puis créer une image avec un outil
  comme `rpi-image-gen` ou en copiant la carte. Ce projet ne prétend pas
  l'avoir fait.

---

## Licences et attributions

- Code du projet : licence MIT, voir [LICENSE](LICENSE).
- Police **Inter** : SIL Open Font License 1.1, fichier
  `frontend/assets/fonts/OFL.txt`, embarqué localement (48 Ko).
- Données météo : **Open-Meteo**, CC BY 4.0, attribution affichée dans
  l'interface : <https://open-meteo.com/>.
- Les icônes SVG sont dessinées pour ce projet et suivent la licence du code.
- Raspberry Pi et Raspberry Pi OS sont des marques de Raspberry Pi Ltd. Ce
  projet n'est pas affilié à Raspberry Pi Ltd ni à Open-Meteo.
