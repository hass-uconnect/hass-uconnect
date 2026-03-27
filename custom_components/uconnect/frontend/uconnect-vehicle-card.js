/* Uconnect Lovelace vehicle card
 * - Vehicle selector via backend websocket
 * - Visual style inspired by BMW CarData vehicle card
 * - Configurable sections
 */

const WS_TYPE = "uconnect/vehicle_cards";
const CARD_TAG = "uconnect-vehicle-card";
const CACHE_MS = 30_000;

const ensureCustomCardsArray = () => {
  window.customCards = window.customCards || [];
  return window.customCards;
};

const boolConfig = (cfg, key, fallback) => {
  const raw = cfg?.[key];
  return typeof raw === "boolean" ? raw : fallback;
};

const normalizeState = (stateObj) => {
  const raw = stateObj?.state;
  if (raw === undefined || raw === null) return "";
  if (raw === "unknown" || raw === "unavailable") return "";
  return String(raw).trim().toLowerCase();
};

const formatState = (stateObj) => {
  if (!stateObj) return "\u2014";
  const state = stateObj.state;
  if (state === "unknown" || state === "unavailable") return "\u2014";
  const unit = stateObj.attributes?.unit_of_measurement;
  return unit ? `${state} ${unit}` : `${state}`;
};

const toNumberOrZero = (stateObj) => {
  const state = normalizeState(stateObj);
  if (!state) return 0;
  const parsed = Number(state);
  return Number.isFinite(parsed) ? parsed : 0;
};

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

const isOnState = (stateObj) => {
  const state = normalizeState(stateObj);
  if (!state) return false;
  return state === "on" || state === "true" || state.includes("active");
};

const hasUsableState = (stateObj) => normalizeState(stateObj) !== "";

const firstDefined = (...values) => values.find((value) => value !== undefined && value !== null && value !== "");

const escapeHtml = (input) =>
  String(input ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");

const iconBadge = (icon, statusClass = "", entityId = "", title = "") => `
  <button class="indicator ${statusClass}" data-entity-id="${escapeHtml(entityId)}" title="${escapeHtml(title)}">
    <ha-icon icon="${icon}"></ha-icon>
  </button>
`;

const humanizeLocationState = (rawState) => {
  if (rawState === undefined || rawState === null) return "Location unavailable";
  const normalized = String(rawState).trim().toLowerCase();
  if (!normalized || normalized === "unknown" || normalized === "unavailable") return "Location unavailable";
  if (normalized === "not_home") return "Away";
  if (normalized === "home") return "Home";
  return String(rawState).replaceAll("_", " ");
};

const sanitizePlate = (raw) => {
  if (typeof raw !== "string") return "";
  return raw.trim().replace(/[^\p{L}\p{N}\s-]/gu, "").substring(0, 15).toUpperCase();
};

const INDICATOR_COUNT = 5;

class UconnectVehicleCard extends HTMLElement {
  setConfig(config) {
    const cfg = config || {};
    this._config = cfg.license_plate
      ? { ...cfg, license_plate: sanitizePlate(cfg.license_plate) }
      : cfg;
    this._initialized = false;
    this._vehicles = null;
    this._vehiclesFetchedAt = 0;
    this._fetchInFlight = null;
  }

  getCardSize() {
    const cfg = this._config || {};
    let size = 5;
    if (boolConfig(cfg, "show_image", true)) size += 2;
    if (boolConfig(cfg, "show_map", true)) size += 2;
    if (boolConfig(cfg, "show_buttons", true)) size += 2;
    return size;
  }

  static getConfigForm() {
    return {
      schema: [
        {
          name: "device_id",
          required: true,
          selector: { device: { integration: "uconnect" } },
        },
        { name: "license_plate", selector: { text: {} } },
        { name: "show_indicators", selector: { boolean: {} } },
        { name: "show_range", selector: { boolean: {} } },
        { name: "show_image", selector: { boolean: {} } },
        { name: "show_map", selector: { boolean: {} } },
        { name: "show_buttons", selector: { boolean: {} } },
      ],
      computeLabel: (schema) => {
        if (schema.name === "device_id") return "Vehicle";
        if (schema.name === "license_plate") return "License plate (shown instead of VIN)";
        if (schema.name === "show_indicators") return "Show indicator row";
        if (schema.name === "show_range") return "Show SOC and range bar";
        if (schema.name === "show_image") return "Show vehicle image";
        if (schema.name === "show_map") return "Show mini map";
        if (schema.name === "show_buttons") return "Show quick info buttons";
        return undefined;
      },
    };
  }

  static getStubConfig() {
    return {
      show_indicators: true,
      show_range: true,
      show_image: true,
      show_map: true,
      show_buttons: true,
    };
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;

    if (!this._initialized) {
      this._initialized = true;
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = `
        <style>
          :host { display: block; }
          ha-card {
            background: linear-gradient(
              180deg,
              color-mix(in srgb, var(--card-background-color) 90%, transparent),
              color-mix(in srgb, var(--card-background-color) 72%, transparent)
            );
            border: 0;
            box-shadow: none;
            backdrop-filter: blur(6px);
            -webkit-backdrop-filter: blur(6px);
          }
          .card-header {
            font-size: 22px;
            font-weight: 700;
            line-height: 1.15;
            color: var(--primary-text-color);
            margin: 0 0 12px;
          }
          .vin {
            margin-top: 2px;
            font-size: 12px;
            color: var(--secondary-text-color);
          }
          #main-wrapper {
            display: grid;
            gap: 12px;
          }
          .box {
            border: 0;
            border-radius: var(--ha-card-border-radius, 12px);
            background: color-mix(in srgb, var(--card-background-color) 62%, transparent);
            padding: 10px;
          }

          .indicators {
            display: grid;
            grid-template-columns: repeat(${INDICATOR_COUNT}, minmax(0, 1fr));
            gap: 8px;
          }
          .indicator {
            appearance: none;
            cursor: pointer;
            border-radius: 999px;
            display: flex;
            align-items: center;
            justify-content: center;
            border: 1px solid transparent;
            background: color-mix(in srgb, var(--secondary-background-color, #90909040) 58%, transparent);
            color: var(--secondary-text-color);
            width: 100%;
            height: 34px;
            padding: 0;
            transition: background 0.2s ease;
          }
          .indicator:hover {
            background: color-mix(in srgb, var(--secondary-background-color, #90909040) 78%, transparent);
          }
          .indicator.ok {
            color: var(--primary-color);
            border-color: transparent;
          }
          .indicator.alert {
            color: var(--error-color);
            border-color: transparent;
          }
          .indicator.placeholder {
            opacity: 0;
            pointer-events: none;
            cursor: default;
          }
          .indicator.charging {
            animation: chargingBadgePulse 1.4s ease-in-out infinite;
          }

          .range-box {
            display: grid;
            gap: 8px;
          }
          .range-top {
            display: flex;
            align-items: center;
            gap: 10px;
          }
          .bar-wrap {
            position: relative;
            border-radius: 8px;
            height: 18px;
            flex: 1 1 auto;
            background: color-mix(in srgb, var(--secondary-background-color, #90909040) 66%, transparent);
            overflow: hidden;
            cursor: pointer;
          }
          .bar-level {
            position: relative;
            height: 100%;
            background: var(--primary-color);
            transition: width 0.2s ease;
            overflow: hidden;
          }
          .bar-wrap.charging .bar-level {
            animation: chargingBarPulse 1.8s ease-in-out infinite;
          }
          .bar-wrap.charging .bar-level::after {
            content: "";
            position: absolute;
            inset: 0;
            background: linear-gradient(
              110deg,
              transparent 10%,
              color-mix(in srgb, var(--primary-color) 45%, white) 45%,
              transparent 80%
            );
            transform: translateX(-120%);
            animation: chargingSweep 2.3s linear infinite;
            pointer-events: none;
          }
          .energy-text {
            position: absolute;
            left: 8px;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-primary-color, #fff);
            font-size: 12px;
            font-weight: 600;
            text-shadow: 0 1px 2px rgb(0 0 0 / 35%);
          }
          .range-value {
            display: flex;
            align-items: center;
            gap: 8px;
            color: var(--primary-text-color);
            font-size: 14px;
            white-space: nowrap;
            cursor: pointer;
          }

          .image {
            width: 100%;
            border-radius: 10px;
            overflow: hidden;
            border: 0;
            background: transparent;
          }
          .image img {
            width: 100%;
            display: block;
            object-fit: cover;
            object-position: center;
            background: transparent;
            transform-origin: center center;
          }
          .image.charging img {
            animation: chargingImagePulse 2.2s ease-in-out infinite;
          }

          .map {
            border-radius: 10px;
            overflow: hidden;
            border: 0;
            background: color-mix(in srgb, var(--secondary-background-color, #90909040) 56%, transparent);
          }
          .map hui-map-card {
            display: block;
            width: 100%;
            height: 120px;
          }
          .map-mount {
            height: 120px;
            overflow: hidden;
          }
          .map-mount > * {
            height: 100%;
          }
          .map-fallback {
            height: 120px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--secondary-text-color);
            font-size: 13px;
          }

          .buttons-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
          }
          .btn-item {
            appearance: none;
            cursor: pointer;
            border: 0;
            border-radius: 10px;
            padding: 10px;
            display: flex;
            align-items: center;
            gap: 10px;
            min-width: 0;
            background: color-mix(in srgb, var(--secondary-background-color, #90909040) 52%, transparent);
            text-align: left;
            transition: background 0.2s ease;
          }
          .btn-item:hover {
            background: color-mix(in srgb, var(--secondary-background-color, #90909040) 74%, transparent);
          }
          .btn-item.alert .btn-icon {
            color: var(--error-color);
          }
          .btn-item.alert .btn-value {
            color: var(--error-color);
          }
          .btn-icon {
            width: 34px;
            height: 34px;
            border-radius: 999px;
            border: 0;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            color: var(--secondary-text-color);
            flex: 0 0 auto;
            background: color-mix(in srgb, var(--card-background-color) 50%, transparent);
          }
          .btn-text {
            min-width: 0;
          }
          .btn-title {
            font-size: 12px;
            color: var(--secondary-text-color);
          }
          .btn-value {
            font-size: 14px;
            color: var(--primary-text-color);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }

          @media (max-width: 520px) {
            .buttons-grid {
              grid-template-columns: 1fr;
            }
            .indicators {
              grid-template-columns: repeat(3, minmax(0, 1fr));
            }
          }

          @keyframes chargingBadgePulse {
            0% { filter: brightness(1); }
            50% { filter: brightness(1.45); }
            100% { filter: brightness(1); }
          }

          @keyframes chargingBarPulse {
            0% { filter: brightness(1); }
            50% { filter: brightness(1.18); }
            100% { filter: brightness(1); }
          }

          @keyframes chargingSweep {
            0% { transform: translateX(-120%); }
            100% { transform: translateX(120%); }
          }

          @keyframes chargingImagePulse {
            0% { filter: brightness(1) saturate(1); }
            50% { filter: brightness(1.08) saturate(1.1); }
            100% { filter: brightness(1) saturate(1); }
          }
        </style>
        <ha-card>
          <div class="card-content">
            <div class="card-header" id="name"></div>
            <div class="vin" id="vin"></div>
            <main id="main-wrapper">
              <div id="indicators"></div>
              <div id="images"></div>
              <div id="range_info"></div>
              <div id="mini_map"></div>
              <div id="buttons"></div>
            </main>
          </div>
        </ha-card>
      `;
      this._bindInteractions();
    }

    this._maybeFetchVehicles();
    this._render();
  }

  _maybeFetchVehicles() {
    const hass = this._hass;
    if (!hass || typeof hass.callWS !== "function") return;

    const now = Date.now();
    if (this._vehicles && now - this._vehiclesFetchedAt < CACHE_MS) return;
    if (this._fetchInFlight) return;

    this._fetchInFlight = hass
      .callWS({ type: WS_TYPE })
      .then((payload) => {
        this._vehicles = Array.isArray(payload?.vehicles) ? payload.vehicles : [];
        this._vehiclesFetchedAt = Date.now();
      })
      .catch(() => {})
      .finally(() => {
        this._fetchInFlight = null;
        this._render();
      });
  }

  _bindInteractions() {
    if (!this.shadowRoot || this._interactionsBound) return;
    this._interactionsBound = true;
    this.shadowRoot.addEventListener("click", (event) => {
      const node = event.target;
      if (!(node instanceof Element)) return;
      const target = node.closest("[data-entity-id]");
      if (!target) return;
      const entityId = target.getAttribute("data-entity-id");
      if (!entityId) return;
      this._openMoreInfo(entityId);
    });
  }

  _openMoreInfo(entityId) {
    if (!entityId) return;
    this.dispatchEvent(
      new CustomEvent("hass-more-info", {
        bubbles: true,
        composed: true,
        detail: { entityId },
      })
    );
  }

  async _createMapCard(hass, trackerEntityId) {
    try {
      if (!window.loadCardHelpers) return null;
      const helpers = await window.loadCardHelpers();
      if (!helpers?.createCardElement) return null;
      const mapCard = helpers.createCardElement({
        type: "map",
        entities: [trackerEntityId],
        default_zoom: 14,
        hours_to_show: 24,
        aspect_ratio: "16:6",
      });
      mapCard.hass = hass;
      return mapCard;
    } catch {
      return null;
    }
  }

  _renderMap(target, hass, trackerEntityId) {
    if (!target) return;

    if (!trackerEntityId) {
      this._cachedMapCard = null;
      this._cachedMapTracker = null;
      target.innerHTML = `
        <div class="map">
          <div class="map-fallback">No vehicle tracker entity available</div>
        </div>
      `;
      return;
    }

    if (!hass?.states?.[trackerEntityId]) {
      this._cachedMapCard = null;
      this._cachedMapTracker = null;
      target.innerHTML = `
        <div class="map">
          <div class="map-fallback">Tracker entity unavailable</div>
        </div>
      `;
      return;
    }

    if (this._cachedMapCard && this._cachedMapTracker === trackerEntityId) {
      this._cachedMapCard.hass = hass;
      return;
    }

    this._cachedMapCard = null;
    this._cachedMapTracker = null;

    const renderToken = (this._mapRenderToken || 0) + 1;
    this._mapRenderToken = renderToken;

    const wrapper = document.createElement("div");
    wrapper.className = "map";
    const mapMount = document.createElement("div");
    mapMount.className = "map-mount";
    mapMount.innerHTML = `<div class="map-fallback">Loading map\u2026</div>`;
    wrapper.appendChild(mapMount);
    target.replaceChildren(wrapper);

    this._createMapCard(hass, trackerEntityId).then((mapCard) => {
      if (!target.isConnected) return;
      if (this._mapRenderToken !== renderToken) return;
      if (!mapCard) {
        mapMount.innerHTML = `<div class="map-fallback">Unable to load map</div>`;
        return;
      }
      this._cachedMapCard = mapCard;
      this._cachedMapTracker = trackerEntityId;
      mapMount.replaceChildren(mapCard);
    });
  }

  _setHtml(el, html) {
    if (el && el.innerHTML !== html) el.innerHTML = html;
  }

  _render() {
    if (!this.shadowRoot) return;

    const hass = this._hass;
    const cfg = this._config || {};
    const deviceId = cfg.device_id;

    if (!deviceId) {
      this._renderMessage("Select a vehicle in the card editor.");
      return;
    }

    const vehicles = this._vehicles || [];
    const vehicle = vehicles.find((v) => v && v.device_id === deviceId);
    if (!vehicle) {
      this._renderMessage("Vehicle not found yet. Try again in a few seconds.");
      return;
    }

    const nameEl = this.shadowRoot.getElementById("name");
    const vinEl = this.shadowRoot.getElementById("vin");
    const indicatorsEl = this.shadowRoot.getElementById("indicators");
    const rangeEl = this.shadowRoot.getElementById("range_info");
    const imageEl = this.shadowRoot.getElementById("images");
    const mapEl = this.shadowRoot.getElementById("mini_map");
    const buttonsEl = this.shadowRoot.getElementById("buttons");

    const vin = vehicle.vin || "";
    const name = vehicle.name || vin || "Uconnect";
    const entities = vehicle.entities || {};

    const read = (key) => hass?.states?.[entities[key]];

    nameEl.textContent = name;
    vinEl.textContent = cfg.license_plate || vin;

    const showIndicators = boolConfig(cfg, "show_indicators", true);
    const showRange = boolConfig(cfg, "show_range", true);
    const showImage = boolConfig(cfg, "show_image", true);
    const showMap = boolConfig(cfg, "show_map", true);
    const showButtons = boolConfig(cfg, "show_buttons", true);

    // Uconnect binary sensors use postprocess inversion:
    //   off = locked/closed (secure), on = unlocked/open (not secure)
    const doorDriverLocked = hasUsableState(read("door_driver")) && !isOnState(read("door_driver"));
    const doorPassengerLocked = hasUsableState(read("door_passenger")) && !isOnState(read("door_passenger"));
    const doorRearLeftLocked = hasUsableState(read("door_rear_left")) && !isOnState(read("door_rear_left"));
    const doorRearRightLocked = hasUsableState(read("door_rear_right")) && !isOnState(read("door_rear_right"));
    const allDoorsLocked = doorDriverLocked && doorPassengerLocked && doorRearLeftLocked && doorRearRightLocked;
    const anyDoorEntity = entities.door_driver || entities.door_passenger || "";

    const windowDriverClosed = hasUsableState(read("window_driver")) && !isOnState(read("window_driver"));
    const windowPassengerClosed = hasUsableState(read("window_passenger")) && !isOnState(read("window_passenger"));
    const allWindowsClosed = windowDriverClosed && windowPassengerClosed;
    const openWindows = [read("window_driver"), read("window_passenger")]
      .filter((s) => hasUsableState(s) && isOnState(s)).length;
    const windowEntity = entities.window_driver || entities.window_passenger || "";

    const trunkLocked = hasUsableState(read("trunk")) && !isOnState(read("trunk"));
    const trunkEntity = entities.trunk || "";

    const chargingActive = isOnState(read("charging"));
    const pluggedIn = isOnState(read("plugged_in"));
    const chargingEntity = entities.charging || entities.plugged_in || "";

    const ignitionOn = isOnState(read("ignition")) || isOnState(read("ev_running"));
    const ignitionEntity = entities.ignition || entities.ev_running || "";

    const hasSoc = Boolean(entities.soc && hasUsableState(read("soc")));
    const hasFuel = Boolean(entities.fuel && hasUsableState(read("fuel")));
    const hasRange = Boolean(entities.range && hasUsableState(read("range")));
    const hasRangeTotal = Boolean(entities.range_total && hasUsableState(read("range_total")));

    const socValue = clamp(toNumberOrZero(read("soc")), 0, 100);
    const fuelValue = clamp(toNumberOrZero(read("fuel")), 0, 100);

    const primaryLevelValue = hasSoc ? socValue : hasFuel ? fuelValue : 0;
    const primaryLevelLabel = hasSoc ? `${socValue}%` : hasFuel ? `${fuelValue}%` : "\u2014";
    const primaryLevelEntity = hasSoc ? (entities.soc || "") : hasFuel ? (entities.fuel || "") : "";
    const primaryLevelHasBar = hasSoc || hasFuel;

    const rangeState = hasRange ? read("range") : hasRangeTotal ? read("range_total") : null;
    const rangeEntity = hasRange ? (entities.range || "") : hasRangeTotal ? (entities.range_total || "") : "";
    const rangeText = rangeState ? formatState(rangeState) : "\u2014";
    const rangeIcon = hasSoc ? "mdi:arrow-left-right" : "mdi:gas-station";

    // Indicators
    if (showIndicators) {
      const indicatorItems = [
        {
          icon: "mdi:car-door-lock",
          stateClass: allDoorsLocked ? "ok" : "alert",
          entity: anyDoorEntity,
          title: allDoorsLocked ? "Doors: Locked" : "Doors: Unlocked",
        },
        {
          icon: allWindowsClosed ? "mdi:car-windshield" : "mdi:car-windshield-outline",
          stateClass: allWindowsClosed ? "ok" : openWindows > 0 ? "alert" : "",
          entity: windowEntity,
          title: allWindowsClosed ? "Windows: Closed" : `Windows: ${openWindows} open`,
        },
        {
          icon: "mdi:lock",
          stateClass: trunkLocked ? "ok" : hasUsableState(read("trunk")) ? "alert" : "",
          entity: trunkEntity,
          title: trunkLocked ? "Trunk: Locked" : "Trunk: Unlocked",
        },
        {
          icon: "mdi:ev-station",
          stateClass: chargingActive ? "ok charging" : pluggedIn ? "ok" : "",
          entity: chargingEntity,
          title: chargingActive ? "Charging" : pluggedIn ? "Plugged in" : "Not plugged in",
        },
        {
          icon: "mdi:engine",
          stateClass: ignitionOn ? "ok" : "",
          entity: ignitionEntity,
          title: ignitionOn ? "Ignition: On" : "Ignition: Off",
        },
      ];

      this._setHtml(indicatorsEl, `
        <div class="box indicators">
          ${indicatorItems.map((item) => iconBadge(item.icon, item.stateClass, item.entity, item.title)).join("")}
        </div>
      `);
    } else {
      this._setHtml(indicatorsEl, "");
    }

    // Range / SOC bar
    if (showRange && (primaryLevelHasBar || rangeState)) {
      if (primaryLevelHasBar) {
        this._setHtml(rangeEl, `
          <div class="box range-box">
            <div class="range-top">
              <div class="bar-wrap ${chargingActive ? "charging" : ""}" data-entity-id="${escapeHtml(primaryLevelEntity)}" title="${escapeHtml(primaryLevelEntity)}">
                <div class="bar-level" style="width:${primaryLevelValue}%;"></div>
                <div class="energy-text">${primaryLevelLabel}</div>
              </div>
              <div class="range-value" data-entity-id="${escapeHtml(rangeEntity)}" title="${escapeHtml(rangeEntity)}">
                <ha-icon icon="${rangeIcon}"></ha-icon>
                <span>${escapeHtml(rangeText)}</span>
              </div>
            </div>
          </div>
        `);
      } else {
        this._setHtml(rangeEl, `
          <div class="box range-box">
            <div class="range-top">
              <div class="range-value" data-entity-id="${escapeHtml(rangeEntity)}" title="${escapeHtml(rangeEntity)}">
                <ha-icon icon="${rangeIcon}"></ha-icon>
                <span>${escapeHtml(rangeText)}</span>
              </div>
            </div>
          </div>
        `);
      }
    } else {
      this._setHtml(rangeEl, "");
    }

    // Vehicle image
    if (showImage && entities.image && hass?.states) {
      const imgState = hass.states[entities.image];
      const pic = imgState?.attributes?.entity_picture;
      this._setHtml(imageEl, pic
        ? `<div class="image ${chargingActive ? "charging" : ""}" data-entity-id="${escapeHtml(entities.image)}" title="${escapeHtml(entities.image)}"><img alt="${escapeHtml(vin)}" src="${escapeHtml(pic)}"></div>`
        : "");
    } else {
      this._setHtml(imageEl, "");
    }

    // Mini map
    if (showMap) {
      this._renderMap(mapEl, hass, entities.device_tracker);
    } else {
      this._setHtml(mapEl, "");
    }

    // Quick info buttons
    if (showButtons) {
      // Tire status: use pressure values if available, fall back to warning sensors
      const tireKeys = ["tire_fl", "tire_fr", "tire_rl", "tire_rr"];
      const tireWarnKeys = ["tire_fl_warn", "tire_fr_warn", "tire_rl_warn", "tire_rr_warn"];
      const tireLabels = { tire_fl: "FL", tire_fr: "FR", tire_rl: "RL", tire_rr: "RR",
        tire_fl_warn: "FL", tire_fr_warn: "FR", tire_rl_warn: "RL", tire_rr_warn: "RR" };
      const tireEntries = tireKeys
        .map((key) => {
          const obj = read(key);
          const value = toNumberOrZero(obj);
          const unit = obj?.attributes?.unit_of_measurement || "";
          return { key, value, unit };
        })
        .filter((t) => t.value > 0);
      const hasPressureData = tireEntries.length > 0;

      let tireAlert = false;
      let tireValue = "\u2014";
      let tireLabel = "Tires";
      let tireEntity = entities.tire_fl || entities.tire_fr
        || entities.tire_fl_warn || entities.tire_fr_warn || "";

      if (hasPressureData) {
        // Pressure sensors available: show average, alert on low tire
        const formatPressure = (v) => v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2);
        const tireAvg = tireEntries.reduce((a, b) => a + b.value, 0) / tireEntries.length;
        const lowTire = tireEntries.length >= 2
          ? tireEntries.find((t) => t.value < tireAvg * 0.8)
          : null;
        tireAlert = lowTire !== null && lowTire !== undefined;
        tireValue = tireAlert
          ? `${formatPressure(lowTire.value)} ${lowTire.unit}`.trim()
          : `${formatPressure(tireAvg)} ${tireEntries[0]?.unit || ""}`.trim();
        tireLabel = tireAlert ? `Tire ${tireLabels[lowTire.key]}` : "Tires";
        tireEntity = tireAlert ? (entities[lowTire.key] || "") : tireEntity;
      } else {
        // No pressure data: use warning binary sensors (on = problem)
        const warnEntries = tireWarnKeys
          .map((key) => ({ key, obj: read(key) }))
          .filter((t) => hasUsableState(t.obj));
        if (warnEntries.length > 0) {
          const failingTire = warnEntries.find((t) => isOnState(t.obj));
          if (failingTire) {
            tireAlert = true;
            tireLabel = `Tire ${tireLabels[failingTire.key]}`;
            tireValue = "Warning";
            tireEntity = entities[failingTire.key] || "";
          } else {
            tireValue = "OK";
            tireEntity = entities[warnEntries[0].key] || "";
          }
        }
      }

      const quickItems = [
        {
          icon: "mdi:map-marker",
          label: "Location",
          value: humanizeLocationState(read("device_tracker")?.state),
          entity: entities.device_tracker || "",
        },
        {
          icon: rangeIcon,
          label: hasSoc ? "Range" : "Fuel Range",
          value: rangeText,
          entity: rangeEntity,
        },
        {
          icon: "mdi:ev-station",
          label: "Charging",
          value: chargingActive ? "Charging" : pluggedIn ? "Plugged in" : "Not charging",
          entity: chargingEntity,
        },
        {
          icon: "mdi:car-tire-alert",
          label: tireLabel,
          value: tireValue,
          entity: tireEntity,
          alert: tireAlert,
        },
        {
          icon: "mdi:car-battery",
          label: "12V Battery",
          value: formatState(read("battery_voltage")),
          entity: entities.battery_voltage || "",
        },
        {
          icon: "mdi:counter",
          label: "Odometer",
          value: formatState(read("odometer")),
          entity: entities.odometer || "",
        },
      ].filter((item) => item && firstDefined(item.entity, item.value) !== "");

      this._setHtml(buttonsEl, `
        <div class="buttons-grid">
          ${quickItems
            .map(
              (item) => `
            <button class="btn-item${item.alert ? " alert" : ""}" data-entity-id="${escapeHtml(item.entity)}" title="${escapeHtml(item.entity)}">
              <div class="btn-icon"><ha-icon icon="${item.icon}"></ha-icon></div>
              <div class="btn-text">
                <div class="btn-title">${escapeHtml(item.label)}</div>
                <div class="btn-value">${escapeHtml(item.value)}</div>
              </div>
            </button>
          `
            )
            .join("")}
        </div>
      `);
    } else {
      this._setHtml(buttonsEl, "");
    }
  }

  _renderMessage(message) {
    if (!this.shadowRoot) return;

    const nameEl = this.shadowRoot.getElementById("name");
    const vinEl = this.shadowRoot.getElementById("vin");
    const indicatorsEl = this.shadowRoot.getElementById("indicators");
    const rangeEl = this.shadowRoot.getElementById("range_info");
    const imageEl = this.shadowRoot.getElementById("images");
    const mapEl = this.shadowRoot.getElementById("mini_map");
    const buttonsEl = this.shadowRoot.getElementById("buttons");

    nameEl.textContent = "Uconnect";
    vinEl.textContent = message;
    this._setHtml(indicatorsEl, "");
    this._setHtml(rangeEl, "");
    this._setHtml(imageEl, "");
    this._setHtml(mapEl, "");
    this._setHtml(buttonsEl, "");
  }
}

if (!customElements.get(CARD_TAG)) {
  customElements.define(CARD_TAG, UconnectVehicleCard);
}

const cards = ensureCustomCardsArray();
if (!cards.some((c) => c && c.type === CARD_TAG)) {
  cards.push({
    type: CARD_TAG,
    name: "Uconnect Vehicle",
    description: "Vehicle card with indicators, SOC/range, image, map and quick info",
    preview: true,
  });
}
