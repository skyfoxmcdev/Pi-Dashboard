/* Pi Dashboard — vanilla client.
   One clock interval and one recursive status timer; values are always
   written with textContent so network-provided strings cannot inject markup. */

(() => {
  "use strict";

  if (window.__piDashboardBooted) {
    return;
  }
  window.__piDashboardBooted = true;

  const ICONS = {
    pin:
      '<path d="M12 21s7-5.2 7-12a7 7 0 0 0-14 0c0 6.8 7 12 7 12Z"/><circle cx="12" cy="9" r="2.4"/>',
    wifi:
      '<path d="M3.5 8.7a13 13 0 0 1 17 0"/><path d="M6.6 11.8a8.5 8.5 0 0 1 10.8 0"/><path d="M9.6 14.8a4 4 0 0 1 4.8 0"/><circle cx="12" cy="18" r="1" fill="currentColor" stroke="none"/>',
    globe:
      '<circle cx="12" cy="12" r="9"/><path d="M3.2 12h17.6"/><path d="M12 3c2.4 2.5 3.7 5.5 3.7 9s-1.3 6.5-3.7 9c-2.4-2.5-3.7-5.5-3.7-9S9.6 5.5 12 3Z"/>',
    pulse: '<path d="M3 12h3.5l2.2-5 4 10 2.3-5H21"/>',
    moon: '<path d="M20 14.2A8.4 8.4 0 0 1 9.8 4a8.5 8.5 0 1 0 10.2 10.2Z"/>',
    sunrise:
      '<path d="M12 3v4"/><path d="M5.6 9.6 7.1 11"/><path d="M18.4 9.6 16.9 11"/><path d="M3 17h3.8"/><path d="M17.2 17H21"/><path d="M7.2 17a4.8 4.8 0 0 1 9.6 0"/><path d="M3 21h18"/>',
    sunset:
      '<path d="M12 7V3"/><path d="M9.5 5.5 12 8l2.5-2.5"/><path d="M5.6 10.6 7.1 12"/><path d="M18.4 10.6 16.9 12"/><path d="M3 17h3.8"/><path d="M17.2 17H21"/><path d="M7.2 17a4.8 4.8 0 0 1 9.6 0"/><path d="M3 21h18"/>',
    droplet:
      '<path d="M12 3s5.8 6.1 5.8 10.3A5.8 5.8 0 0 1 6.2 13.3C6.2 9.1 12 3 12 3Z"/>',
    wind:
      '<path d="M3 8h10.5a3 3 0 1 0-3-3"/><path d="M3 12h15.2a2.8 2.8 0 1 1-2.8 2.8"/><path d="M3 16h7"/>',
    rain:
      '<path d="M7 15.5a4 4 0 0 1 .5-8A5.5 5.5 0 0 1 18 9.6a3.4 3.4 0 0 1-1 6.4H7Z"/><path d="M8.5 18.5v1.2"/><path d="M12 18.5v1.2"/><path d="M15.5 18.5v1.2"/>',
    thermometer:
      '<path d="M10 13.4V5.2a2 2 0 1 1 4 0v8.2a4 4 0 1 1-4 0Z"/><circle cx="12" cy="17.2" r="1" fill="currentColor" stroke="none"/>',
    cpu:
      '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/><path d="M9 2.8v3.2M15 2.8v3.2M9 18v3.2M15 18v3.2M2.8 9H6M2.8 15H6M18 9h3.2M18 15h3.2"/>',
    memory:
      '<rect x="3" y="7" width="18" height="9" rx="2"/><path d="M7 4v3M12 4v3M17 4v3M7 17v3M12 17v3M17 17v3"/><path d="M7 10.5v2M12 10.5v2M17 10.5v2"/>',
    clock:
      '<circle cx="12" cy="12" r="9"/><path d="M12 7v5.3l3.2 1.9"/>',
    refresh:
      '<path d="M20 12a8 8 0 1 1-2.2-5.5"/><path d="M20 3.5V8h-4.5"/>',
    "clear-day":
      '<circle cx="12" cy="12" r="4.1" fill="currentColor" fill-opacity=".1"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M18.7 5.3l-1.6 1.6M6.9 17.1l-1.6 1.6"/>',
    "clear-night":
      '<path d="M20 14.1A8.2 8.2 0 0 1 9.9 4a8.4 8.4 0 1 0 10.1 10.1Z" fill="currentColor" fill-opacity=".08"/><path d="M17.5 4.5v2M16.5 5.5h2"/>',
    "partly-day":
      '<circle cx="9" cy="8.7" r="2.9" fill="currentColor" fill-opacity=".08"/><path d="M9 3.2v1.9M3.7 8.7h1.9M5.3 5l1.3 1.3M12.7 5l-1.3 1.3M7.7 18.6a3.3 3.3 0 0 1 .4-6.6 4.8 4.8 0 0 1 9.1 1.1 2.9 2.9 0 0 1-.6 5.5H7.7Z"/>',
    "partly-night":
      '<path d="M14.7 8.2A5.7 5.7 0 0 1 8 2.6a5.8 5.8 0 1 0 6.7 5.6Z"/><path d="M7.7 18.6a3.3 3.3 0 0 1 .4-6.6 4.8 4.8 0 0 1 9.1 1.1 2.9 2.9 0 0 1-.6 5.5H7.7Z"/>',
    cloudy:
      '<path d="M6.6 18.5a4.1 4.1 0 0 1 .5-8.2 5.8 5.8 0 0 1 11 1.3 3.5 3.5 0 0 1-.8 6.9H6.6Z"/>',
    fog:
      '<path d="M6.8 14.6a3.9 3.9 0 0 1 .5-7.8 5.5 5.5 0 0 1 10.4 1.2 3.3 3.3 0 0 1-.8 6.6H6.8Z"/><path d="M4.5 18h11M7.5 21.2h12"/>',
    drizzle:
      '<path d="M6.8 14.8a3.9 3.9 0 0 1 .5-7.8 5.5 5.5 0 0 1 10.4 1.2 3.3 3.3 0 0 1-.8 6.6H6.8Z"/><path d="M9 18v1M13 18v1M17 18v1"/>',
    rain:
      '<path d="M6.8 14.8a3.9 3.9 0 0 1 .5-7.8 5.5 5.5 0 0 1 10.4 1.2 3.3 3.3 0 0 1-.8 6.6H6.8Z"/><path d="M8.5 17.7 7.6 20M12.5 17.7l-.9 2.3M16.5 17.7l-.9 2.3"/>',
    snow:
      '<path d="M6.8 14.8a3.9 3.9 0 0 1 .5-7.8 5.5 5.5 0 0 1 10.4 1.2 3.3 3.3 0 0 1-.8 6.6H6.8Z"/><path d="M8.5 19.5h.01M12 21h.01M15.5 19.5h.01"/>',
    thunder:
      '<path d="M6.8 14.8a3.9 3.9 0 0 1 .5-7.8 5.5 5.5 0 0 1 10.4 1.2 3.3 3.3 0 0 1-.8 6.6H6.8Z"/><path d="m13.4 15-2.5 4h2.4l-1.1 3.3 3.8-4.7h-2.5l1.2-2.6Z" fill="currentColor" fill-opacity=".16"/>',
    sleet:
      '<path d="M6.8 14.8a3.9 3.9 0 0 1 .5-7.8 5.5 5.5 0 0 1 10.4 1.2 3.3 3.3 0 0 1-.8 6.6H6.8Z"/><path d="M9 18v1.2M15 18v1.2M12 19.7h.01M12 21.4h.01"/>',
    unknown:
      '<path d="M6.6 16.8a4 4 0 0 1 .5-8 5.6 5.6 0 0 1 10.6 1.2 3.4 3.4 0 0 1-.8 6.8H6.6Z"/><path d="M12 13.5v-.6a1.6 1.6 0 1 1 2.6 1.3c-.8.6-1.3 1-1.3 2"/><circle cx="13.3" cy="18.8" r=".8" fill="currentColor" stroke="none"/>',
  };

  const byId = (id) => document.getElementById(id);
  const state = {
    status: null,
    night: null,
    timeZone: null,
    pollSeconds: 10,
    failures: 0,
    timer: null,
    clockTimer: null,
    inFlight: false,
    controller: null,
    formatters: null,
    appVersion: null,
    reloadScheduled: false,
    stopped: false,
  };

  function svgIcon(name) {
    const body = ICONS[name] || ICONS.unknown;
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.45" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${body}</svg>`;
  }

  function setIcon(id, name) {
    const node = byId(id);
    if (node) {
      node.innerHTML = svgIcon(name);
    }
  }

  function setText(id, value) {
    const node = byId(id);
    if (node) {
      node.textContent = value === null || value === undefined ? "—" : String(value);
    }
  }

  const number0 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
  const number1 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });

  function isNumber(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function clampPercent(value) {
    return Math.max(0, Math.min(100, isNumber(value) ? value : 0));
  }

  function formatTemperatureShort(value, unit) {
    if (!isNumber(value)) {
      return "—";
    }
    const number = number0.format(value);
    return unit ? `${number}${unit}` : number;
  }

  function formatTime(isoLike) {
    if (typeof isoLike !== "string") {
      return "—";
    }
    const match = isoLike.match(/T(\d{2}):(\d{2})/);
    return match ? `${match[1]}:${match[2]}` : "—";
  }

  function formatHour(isoLike) {
    if (typeof isoLike !== "string") {
      return "—";
    }
    const match = isoLike.match(/T(\d{2}):/);
    return match ? `${Number(match[1])}h` : "—";
  }

  function formatClockDate(isoLike) {
    if (typeof isoLike !== "string") {
      return "—";
    }
    const date = new Date(isoLike);
    if (Number.isNaN(date.getTime())) {
      return "—";
    }
    try {
      const formatter = new Intl.DateTimeFormat("fr-FR", {
        timeZone: state.timeZone || undefined,
        hour: "2-digit",
        minute: "2-digit",
      });
      return formatter.format(date);
    } catch {
      return "—";
    }
  }

  function formatDayLength(sunrise, sunset) {
    if (typeof sunrise !== "string" || typeof sunset !== "string") {
      return "—";
    }
    const start = sunrise.match(/T(\d{2}):(\d{2})/);
    const end = sunset.match(/T(\d{2}):(\d{2})/);
    if (!start || !end) {
      return "—";
    }
    const startMinutes = Number(start[1]) * 60 + Number(start[2]);
    const endMinutes = Number(end[1]) * 60 + Number(end[2]);
    const minutes = endMinutes - startMinutes;
    if (minutes <= 0) {
      return "—";
    }
    return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")}`;
  }

  function formatBytes(bytes) {
    if (!isNumber(bytes)) {
      return "—";
    }
    const gib = 1024 ** 3;
    const mib = 1024 ** 2;
    if (bytes >= gib) {
      return `${number1.format(bytes / gib)} Go`;
    }
    return `${number0.format(bytes / mib)} Mo`;
  }

  function formatUptime(seconds) {
    if (!isNumber(seconds) || seconds < 0) {
      return "—";
    }
    if (seconds < 60) {
      return "< 1 min";
    }
    const totalMinutes = Math.floor(seconds / 60);
    if (totalMinutes < 60) {
      return `${totalMinutes} min`;
    }
    const totalHours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    if (totalHours < 24) {
      return `${totalHours} h ${String(minutes).padStart(2, "0")}`;
    }
    const days = Math.floor(totalHours / 24);
    const hours = totalHours % 24;
    return `${days} j ${hours} h`;
  }

  function weekdayLabel(dateString, index) {
    if (index === 0) {
      return "Auj.";
    }
    if (typeof dateString !== "string") {
      return "—";
    }
    const date = new Date(`${dateString}T12:00:00Z`);
    if (Number.isNaN(date.getTime())) {
      return "—";
    }
    try {
      const label = new Intl.DateTimeFormat("fr-FR", {
        weekday: "short",
        timeZone: "UTC",
      }).format(date);
      return label.replace(".", "");
    } catch {
      return "—";
    }
  }

  function resolveTimeZone(value) {
    if (typeof value === "string" && value.trim()) {
      try {
        new Intl.DateTimeFormat("fr-FR", { timeZone: value });
        return value;
      } catch {
        /* Fall through to the browser timezone. */
      }
    }
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
    } catch {
      return null;
    }
  }

  function buildFormatters() {
    const timeZone = state.timeZone || undefined;
    const options = { timeZone };
    try {
      return {
        time: new Intl.DateTimeFormat("fr-FR", {
          ...options,
          hour: "2-digit",
          minute: "2-digit",
          hourCycle: "h23",
        }),
        seconds: new Intl.DateTimeFormat("fr-FR", {
          ...options,
          second: "2-digit",
        }),
        weekday: new Intl.DateTimeFormat("fr-FR", {
          ...options,
          weekday: "long",
        }),
        date: new Intl.DateTimeFormat("fr-FR", {
          ...options,
          day: "numeric",
          month: "long",
          year: "numeric",
        }),
        stamp: new Intl.DateTimeFormat("fr-FR", {
          ...options,
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hourCycle: "h23",
        }),
      };
    } catch {
      state.timeZone = null;
      return {
        time: new Intl.DateTimeFormat("fr-FR", {
          hour: "2-digit",
          minute: "2-digit",
          hourCycle: "h23",
        }),
        seconds: new Intl.DateTimeFormat("fr-FR", { second: "2-digit" }),
        weekday: new Intl.DateTimeFormat("fr-FR", { weekday: "long" }),
        date: new Intl.DateTimeFormat("fr-FR", {
          day: "numeric",
          month: "long",
          year: "numeric",
        }),
        stamp: new Intl.DateTimeFormat("fr-FR", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hourCycle: "h23",
        }),
      };
    }
  }

  function zonedMinutes() {
    try {
      const parts = new Intl.DateTimeFormat("fr-FR", {
        timeZone: state.timeZone || undefined,
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).formatToParts(new Date());
      const hour = Number(parts.find((part) => part.type === "hour")?.value || 0);
      const minute = Number(parts.find((part) => part.type === "minute")?.value || 0);
      return hour * 60 + minute;
    } catch {
      const now = new Date();
      return now.getHours() * 60 + now.getMinutes();
    }
  }

  function parseClock(value) {
    if (typeof value !== "string") {
      return null;
    }
    const match = value.match(/^(\d{2}):(\d{2})$/);
    return match ? Number(match[1]) * 60 + Number(match[2]) : null;
  }

  function computeNightActive() {
    const night = state.night;
    if (!night || night.enabled === false) {
      return false;
    }
    const start = parseClock(night.start);
    const end = parseClock(night.end);
    if (start === null || end === null || start === end) {
      return Boolean(night.active);
    }
    const current = zonedMinutes();
    return start < end
      ? current >= start && current < end
      : current >= start || current < end;
  }

  function applyNightMode() {
    const active = computeNightActive();
    document.documentElement.classList.toggle("night", active);
    const chip = byId("night-chip");
    if (chip) {
      chip.hidden = !active;
    }
  }

  function updateClock() {
    if (!state.formatters) {
      return;
    }
    const now = new Date();
    const timeNode = byId("clock-time");
    const secondsNode = byId("clock-seconds");
    const dayNode = byId("day-label");
    const dateNode = byId("date-label");
    const tzNode = byId("timezone-label");
    if (timeNode) {
      timeNode.textContent = state.formatters.time.format(now);
    }
    if (secondsNode) {
      secondsNode.textContent = state.formatters.seconds.format(now);
    }
    if (dayNode) {
      dayNode.textContent = state.formatters.weekday.format(now);
    }
    if (dateNode) {
      dateNode.textContent = state.formatters.date.format(now);
    }
    if (tzNode) {
      tzNode.textContent = state.timeZone || "Fuseau local";
    }
    applyNightMode();
  }

  function setChip(id, valueId, label, chipState) {
    const chip = byId(id);
    if (chip) {
      chip.dataset.state = chipState;
    }
    setText(valueId, label);
  }

  function renderWeather(weather) {
    const card = byId("weather-card");
    const empty = byId("weather-empty");
    const badge = byId("weather-badge");
    const units = weather.units || {
      temperature: "°C",
      wind_speed: "km/h",
      precipitation: "mm",
    };
    const current = weather.current;

    setText("temperature-unit", units.temperature);
    setText("sunrise-time", formatTime(weather.sun && weather.sun.sunrise));
    setText("sunset-time", formatTime(weather.sun && weather.sun.sunset));
    setText("day-length", formatDayLength(weather.sun && weather.sun.sunrise, weather.sun && weather.sun.sunset));
    setIcon("sunrise-icon", "sunrise");
    setIcon("sunset-icon", "sunset");

    if (!current) {
      if (card) {
        card.classList.add("is-empty");
      }
      if (empty) {
        empty.hidden = false;
        if (weather.state === "unconfigured") {
          empty.textContent =
            "Météo à configurer : renseignez location.latitude et location.longitude dans /etc/pi-dashboard/config.json, puis redémarrez le service.";
        } else if (weather.state === "loading") {
          empty.textContent = "Première récupération des prévisions météo…";
        } else {
          empty.textContent = `Météo indisponible. ${weather.error || "Une nouvelle tentative sera faite automatiquement."}`;
        }
      }
      setText(
        "condition",
        weather.state === "unconfigured"
          ? "En attente de configuration"
          : weather.state === "loading"
            ? "Chargement de la météo"
            : "Météo indisponible",
      );
      if (badge) {
        badge.hidden = true;
      }
      setText(
        "weather-updated",
        weather.state === "unconfigured"
          ? "Coordonnées météo à renseigner"
          : weather.state === "loading"
            ? "Connexion à Open-Meteo…"
            : "Aucune donnée disponible",
      );
      return;
    }

    if (card) {
      card.classList.remove("is-empty");
    }
    if (empty) {
      empty.hidden = true;
    }

    const unitsTemp = units.temperature || "°C";
    setText("condition", current.condition || "Conditions actuelles");
    setText("temperature", isNumber(current.temperature) ? number0.format(current.temperature) : "—");
    setText("temperature-unit", unitsTemp);
    setText(
      "apparent-temperature",
      isNumber(current.apparent_temperature)
        ? `${number0.format(current.apparent_temperature)} ${unitsTemp}`
        : "—",
    );
    setText(
      "humidity",
      isNumber(current.humidity_percent) ? `${number0.format(current.humidity_percent)} %` : "—",
    );
    setText(
      "wind",
      isNumber(current.wind_speed) ? `${number0.format(current.wind_speed)} ${units.wind_speed || ""}`.trim() : "—",
    );
    setText("wind-direction", current.wind_direction ? `· ${current.wind_direction}` : "");
    setText(
      "precipitation",
      isNumber(current.precipitation)
        ? `${number1.format(current.precipitation)} ${units.precipitation || "mm"}`
        : "—",
    );

    const iconKey = current.icon || "unknown";
    const weatherIcon = byId("weather-icon");
    if (weatherIcon) {
      weatherIcon.dataset.icon = iconKey;
      weatherIcon.innerHTML = svgIcon(iconKey);
    }

    if (badge) {
      badge.hidden = weather.state !== "stale";
      badge.textContent =
        weather.online === false ? "Hors ligne · cache" : "Données en cache";
    }
    const updatedPrefix = weather.state === "stale" ? "Cache actualisé à" : "Actualisé à";
    setText(
      "weather-updated",
      weather.updated_at ? `${updatedPrefix} ${formatClockDate(weather.updated_at)}` : "—",
    );
    setIcon("refresh-icon", "refresh");
  }

  function renderHourly(weather) {
    const list = byId("hourly-list");
    const note = byId("hourly-note");
    if (!list) {
      return;
    }
    const hours = Array.isArray(weather.hourly) ? weather.hourly.slice(0, 8) : [];
    list.textContent = "";
    if (hours.length === 0) {
      const placeholder = document.createElement("p");
      placeholder.className = "placeholder";
      placeholder.textContent = "Prévisions horaires indisponibles.";
      list.append(placeholder);
      if (note) {
        note.textContent = "—";
      }
      return;
    }
    if (note) {
      note.textContent = `${hours.length} prochaines heures`;
    }
    const units = weather.units || {};
    for (const entry of hours) {
      const item = document.createElement("div");
      item.className = "hour";
      item.setAttribute("role", "listitem");
      if (entry.condition) {
        item.title = entry.condition;
      }

      const time = document.createElement("span");
      time.className = "hour__time";
      time.textContent = formatHour(entry.time);

      const icon = document.createElement("span");
      icon.className = "hour__icon";
      icon.dataset.icon = entry.icon || "unknown";
      icon.innerHTML = svgIcon(entry.icon || "unknown");

      const temp = document.createElement("strong");
      temp.className = "hour__temp";
      temp.textContent = formatTemperatureShort(entry.temperature, units.temperature);

      const rain = document.createElement("span");
      rain.className = "hour__rain";
      if (isNumber(entry.precipitation_probability) && entry.precipitation_probability > 0) {
        rain.textContent = `${number0.format(entry.precipitation_probability)} %`;
      } else {
        rain.textContent = "—";
        rain.classList.add("hour__rain--empty");
      }

      item.append(time, icon, temp, rain);
      list.append(item);
    }
  }

  function renderDaily(weather) {
    const list = byId("daily-list");
    if (!list) {
      return;
    }
    const days = Array.isArray(weather.daily) ? weather.daily.slice(0, 5) : [];
    list.textContent = "";
    if (days.length === 0) {
      const placeholder = document.createElement("p");
      placeholder.className = "placeholder";
      placeholder.textContent = "Prévisions quotidiennes indisponibles.";
      list.append(placeholder);
      return;
    }
    const units = weather.units || {};
    days.forEach((entry, index) => {
      const row = document.createElement("div");
      row.className = "day-row";
      if (entry.condition) {
        row.title = entry.condition;
      }

      const day = document.createElement("span");
      day.className = "day-row__day";
      day.textContent = weekdayLabel(entry.date, index);

      const icon = document.createElement("span");
      icon.className = "day-row__icon";
      icon.dataset.icon = entry.icon || "unknown";
      icon.innerHTML = svgIcon(entry.icon || "unknown");

      const condition = document.createElement("span");
      condition.className = "day-row__condition";
      condition.textContent = entry.condition || "—";

      const temps = document.createElement("span");
      temps.className = "day-row__temps";
      const max = document.createElement("span");
      max.className = "day-row__max";
      max.textContent = formatTemperatureShort(entry.temperature_max, units.temperature);
      const min = document.createElement("span");
      min.className = "day-row__min";
      min.textContent = formatTemperatureShort(entry.temperature_min, units.temperature);
      temps.append(max, min);

      row.append(day, icon, condition, temps);
      list.append(row);
    });
  }

  function setMeter(value, barId, progressId) {
    const percent = clampPercent(value);
    const bar = byId(barId);
    const progress = byId(progressId);
    if (bar) {
      bar.style.width = `${percent}%`;
    }
    if (progress) {
      progress.setAttribute("aria-valuenow", String(Math.round(percent)));
    }
  }

  function renderSystem(system) {
    const cpu = system.cpu_percent;
    const memory = system.memory;
    const temp = system.cpu_temperature_c;
    const health = system.health || { level: "unknown", label: "Indisponible", reasons: [] };

    setText("cpu-value", isNumber(cpu) ? `${number0.format(cpu)} %` : "—");
    setMeter(cpu, "cpu-bar", "cpu-progress");

    if (memory) {
      setText("memory-value", `${number0.format(memory.percent)} %`);
      setText(
        "memory-detail",
        `${formatBytes(memory.used_bytes)} / ${formatBytes(memory.total_bytes)}`,
      );
      setMeter(memory.percent, "memory-bar", "memory-progress");
    } else {
      setText("memory-value", "—");
      setText("memory-detail", "Mémoire indisponible");
      setMeter(0, "memory-bar", "memory-progress");
    }

    setText(
      "cpu-temperature",
      isNumber(temp) ? `${number1.format(temp)} °C` : "—",
    );
    setText("uptime", formatUptime(system.uptime_seconds));
    setText("health-label", health.label || "Indisponible");
    setText(
      "health-detail",
      Array.isArray(health.reasons) && health.reasons.length
        ? health.reasons.join(" · ")
        : system.available === false
          ? "Métriques système indisponibles sur cette plateforme."
          : "Aucune alerte : charge, mémoire et température dans les seuils.",
    );
    const label = byId("health-label");
    if (label) {
      label.dataset.level = health.level || "unknown";
    }
    const shortLabels = {
      ok: "Sain",
      warn: "À surveiller",
      critical: "Critique",
      unknown: "—",
    };
    setChip(
      "health-chip",
      "health-chip-label",
      shortLabels[health.level] || health.label || "—",
      health.level || "unknown",
    );
    setIcon("cpu-icon", "cpu");
    setIcon("memory-icon", "memory");
    setIcon("thermometer-icon", "thermometer");
    setIcon("uptime-icon", "clock");
  }

  function signalLevel(signal) {
    if (!isNumber(signal)) {
      return 0;
    }
    if (signal >= 75) {
      return 4;
    }
    if (signal >= 50) {
      return 3;
    }
    if (signal >= 25) {
      return 2;
    }
    if (signal > 0) {
      return 1;
    }
    return 0;
  }

  function renderNetwork(network, weather) {
    const wifi = network.wifi || {};
    const pill = byId("wifi-state");
    const ssid = wifi.ssid;
    const signal = wifi.signal_percent;

    if (!wifi.available) {
      setText("wifi-state", "Non détecté");
      if (pill) {
        pill.dataset.level = "unknown";
      }
      setText("ssid", "Aucun Wi-Fi détecté");
      setText("signal-value", "—");
      setChip("wifi-chip", "wifi-chip-label", "Non détecté", "off");
    } else if (wifi.connected) {
      setText("wifi-state", "Connecté");
      if (pill) {
        pill.dataset.level = "ok";
      }
      setText("ssid", ssid || "Réseau masqué");
      setText("signal-value", isNumber(signal) ? `${number0.format(signal)} %` : "—");
      setChip("wifi-chip", "wifi-chip-label", "Connecté", "ok");
    } else {
      setText("wifi-state", "Déconnecté");
      if (pill) {
        pill.dataset.level = "warn";
      }
      setText("ssid", ssid || "—");
      setText("signal-value", isNumber(signal) ? `${number0.format(signal)} %` : "—");
      setChip("wifi-chip", "wifi-chip-label", "Déconnecté", "warn");
    }

    const bars = byId("signal-bars");
    if (bars) {
      bars.dataset.level = String(wifi.connected ? signalLevel(signal) : 0);
    }
    setText("ip-address", network.ip_address || "—");
    setText("network-interface", wifi.interface || "—");
    setText(
      "network-checked",
      network.checked_at ? formatClockDate(network.checked_at) : "—",
    );

    if (weather.online === true) {
      setChip("internet-chip", "internet-chip-label", "En ligne", "ok");
    } else if (weather.online === false) {
      setChip("internet-chip", "internet-chip-label", "Hors ligne", "critical");
    } else {
      setChip("internet-chip", "internet-chip-label", "Inconnu", "unknown");
    }
    setIcon("network-wifi-icon", "wifi");
    setIcon("wifi-chip-icon", "wifi");
    setIcon("internet-chip-icon", "globe");
    setIcon("health-chip-icon", "pulse");
    setIcon("night-chip-icon", "moon");
    setIcon("location-icon", "pin");
    setIcon("humidity-icon", "droplet");
    setIcon("wind-icon", "wind");
    setIcon("rain-icon", "rain");
  }

  function render(data) {
    state.status = data;
    state.night = data.night || null;
    state.pollSeconds = Math.max(5, Math.min(120, Number(data.ui && data.ui.poll_seconds) || 10));

    const resolvedTimeZone = resolveTimeZone(data.timezone);
    if (resolvedTimeZone !== state.timeZone) {
      state.timeZone = resolvedTimeZone;
      state.formatters = buildFormatters();
    }

    setText("location-name", data.location && data.location.name ? data.location.name : "Lieu non configuré");
    const incomingVersion = data.app && typeof data.app.version === "string" ? data.app.version : null;
    if (incomingVersion) {
      if (!state.appVersion) {
        state.appVersion = incomingVersion;
      } else if (state.appVersion !== incomingVersion && !state.reloadScheduled) {
        state.reloadScheduled = true;
        setService("ok", "Mise à jour appliquée — rechargement…");
        window.setTimeout(() => window.location.reload(), 1200);
      }
    }
    const versionNode = byId("app-version");
    if (versionNode) {
      versionNode.textContent = data.app && data.app.version ? `v${data.app.version}` : "v—";
    }

    renderWeather(data.weather || {});
    renderHourly(data.weather || {});
    renderDaily(data.weather || {});
    renderSystem(data.system || {});
    renderNetwork(data.network || {}, data.weather || {});
    updateClock();

    const stamp = state.formatters ? state.formatters.stamp.format(new Date()) : "—";
    setText("last-update", stamp);

    setService("ok", "Service actif");
  }

  function setService(serviceState, label) {
    const node = byId("service-state");
    if (node) {
      node.dataset.state = serviceState;
    }
    setText("service-label", label);
    const last = byId("last-update");
    if (last) {
      last.setAttribute("aria-live", "off");
    }
  }

  function schedule(delayMs) {
    if (state.stopped) {
      return;
    }
    if (state.timer) {
      window.clearTimeout(state.timer);
    }
    state.timer = window.setTimeout(loadStatus, Math.max(2000, delayMs));
  }

  async function loadStatus() {
    if (state.stopped || state.inFlight) {
      return;
    }
    state.inFlight = true;
    const controller = new AbortController();
    state.controller = controller;
    const timeout = window.setTimeout(() => controller.abort(), 7000);

    try {
      const response = await fetch("/api/status", {
        cache: "no-store",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();
      if (!data || typeof data !== "object" || !data.weather || !data.system) {
        throw new Error("Réponse de statut invalide");
      }
      state.failures = 0;
      render(data);
      schedule(state.pollSeconds * 1000);
    } catch {
      state.failures += 1;
      setService("error", "Service local injoignable");
      setChip("internet-chip", "internet-chip-label", "Incertain", "unknown");
      schedule(Math.min(30000, 5000 * state.failures));
    } finally {
      window.clearTimeout(timeout);
      state.inFlight = false;
      state.controller = null;
    }
  }

  function bindCursorHiding() {
    let cursorTimer = null;
    const hide = () => document.documentElement.classList.add("is-cursor-hidden");
    const show = () => {
      document.documentElement.classList.remove("is-cursor-hidden");
      if (cursorTimer) {
        window.clearTimeout(cursorTimer);
      }
      cursorTimer = window.setTimeout(hide, 3000);
    };
    for (const eventName of ["pointermove", "pointerdown", "wheel", "keydown"]) {
      window.addEventListener(eventName, show, { passive: true });
    }
    show();
  }

  function start() {
    setIcon("location-icon", "pin");
    setIcon("wifi-chip-icon", "wifi");
    setIcon("internet-chip-icon", "globe");
    setIcon("health-chip-icon", "pulse");
    setIcon("night-chip-icon", "moon");
    setIcon("sunrise-icon", "sunrise");
    setIcon("sunset-icon", "sunset");
    setIcon("humidity-icon", "droplet");
    setIcon("wind-icon", "wind");
    setIcon("rain-icon", "rain");
    setIcon("refresh-icon", "refresh");
    setIcon("cpu-icon", "cpu");
    setIcon("memory-icon", "memory");
    setIcon("thermometer-icon", "thermometer");
    setIcon("uptime-icon", "clock");
    setIcon("network-wifi-icon", "wifi");

    state.timeZone = resolveTimeZone(null);
    state.formatters = buildFormatters();
    updateClock();
    bindCursorHiding();

    state.clockTimer = window.setInterval(updateClock, 1000);
    loadStatus();

    window.addEventListener("pagehide", () => {
      state.stopped = true;
      if (state.timer) {
        window.clearTimeout(state.timer);
      }
      if (state.clockTimer) {
        window.clearInterval(state.clockTimer);
      }
      if (state.controller) {
        state.controller.abort();
      }
    });

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && state.failures > 0) {
        schedule(0);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
