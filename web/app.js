const state = {
  status: null,
  vertices: [],
  home: null,
  placingHome: false,
  launchable: false,
  hadPreview: false,
  busy: false,
};

const map = L.map("map", { doubleClickZoom: false, zoomControl: true });
const tiles = L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
  subdomains: "abcd",
  maxZoom: 20,
}).addTo(map);

let tileErrors = 0;
tiles.on("tileerror", () => {
  tileErrors += 1;
  if (tileErrors === 1) {
    setBanner("Map tiles did not load. Drawing still works on the blank map.", "bad");
  }
});

const polygonLayer = L.polygon([], {
  color: "#d6ec62",
  weight: 2,
  fillColor: "#d6ec62",
  fillOpacity: 0.12,
}).addTo(map);

const pathLayer = L.polyline([], {
  color: "#f0a202",
  weight: 3,
  smoothFactor: 0,
}).addTo(map);

const vertexLayer = L.layerGroup().addTo(map);
const homeMarker = L.circleMarker([0, 0], {
  radius: 7,
  color: "#9be7c4",
  fillColor: "#9be7c4",
  fillOpacity: 0.95,
  weight: 2,
});

const report = document.getElementById("report");
const launchButton = document.getElementById("launch");
const placeButton = document.getElementById("place-home");

function setPill(text) {
  document.getElementById("vehicle-pill").textContent = text;
}

function setBanner(text, tone) {
  const empty = document.getElementById("empty");
  if (empty) empty.remove();
  let banner = document.getElementById("banner");
  if (!banner) {
    banner = document.createElement("p");
    banner.id = "banner";
    banner.className = "banner";
    report.prepend(banner);
  }
  banner.className = `banner ${tone || ""}`.trim();
  banner.textContent = text;
}

function numberValue(id) {
  const value = Number(document.getElementById(id).value);
  if (!Number.isFinite(value)) {
    throw new Error("Enter a number in every field.");
  }
  return value;
}

function surveyBody() {
  if (state.vertices.length < 3) {
    throw new Error("Drop at least three corners.");
  }
  if (!state.home) {
    throw new Error("Place home inside the field.");
  }
  return {
    polygon: state.vertices.map((point) => ({ lat: point.lat, lon: point.lng })),
    home: { lat: state.home.lat, lon: state.home.lng },
    spacing_m: numberValue("spacing"),
    altitude_m: numberValue("altitude"),
    speed_m_s: numberValue("speed"),
    angle_deg: numberValue("angle"),
    margin_m: numberValue("margin"),
    battery_percent: numberValue("battery"),
  };
}

function drawPolygon() {
  const count = state.vertices.length;
  document.getElementById("corner-count").textContent =
    count === 0 ? "No corners yet. Click the map to drop them." : `${count} corner${count === 1 ? "" : "s"}.`;
  vertexLayer.clearLayers();
  state.vertices.forEach((point) => {
    L.circleMarker(point, {
      radius: 4,
      color: "#d6ec62",
      fillColor: "#d6ec62",
      fillOpacity: 1,
      weight: 1,
    }).addTo(vertexLayer);
  });
  polygonLayer.setLatLngs(count >= 3 ? state.vertices : []);
  if (state.home) {
    homeMarker.setLatLng(state.home).addTo(map);
    document.getElementById("home-readout").textContent =
      `Home ${state.home.lat.toFixed(6)}, ${state.home.lng.toFixed(6)}`;
  } else {
    map.removeLayer(homeMarker);
    document.getElementById("home-readout").textContent = "Home not placed.";
  }
}

function drawPath(waypoints) {
  pathLayer.setLatLngs(waypoints.map((point) => [point.lat, point.lon]));
  if (waypoints.length) {
    const bounds = L.latLngBounds(waypoints.map((point) => [point.lat, point.lon]));
    if (state.vertices.length) bounds.extend(state.vertices);
    map.fitBounds(bounds, { padding: [24, 24] });
  }
}

function markStale() {
  state.launchable = false;
  launchButton.disabled = true;
  if (state.hadPreview) {
    document.getElementById("stale").hidden = false;
  }
}

function errorText(body) {
  if (body && body.reason) return body.reason;
  if (body && typeof body.detail === "string") return body.detail;
  if (body && Array.isArray(body.detail)) {
    return body.detail.map((item) => item.msg || "Invalid value").join(" ");
  }
  return "The planner rejected that request.";
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(errorText(body));
  return body;
}

function factList(rows) {
  const list = document.createElement("dl");
  rows.forEach(([label, value]) => {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = value;
    list.append(dt, dd);
  });
  return list;
}

function formatMeters(value) {
  if (value == null || Number.isNaN(value)) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(2)} km`;
  return `${Math.round(value)} m`;
}

function formatDuration(seconds) {
  if (seconds == null) return "—";
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes === 0) return `${rest} s at the set speed`;
  return `${minutes} min ${rest} s at the set speed`;
}

function formatWh(value) {
  return `${Number(value).toFixed(1)} Wh`;
}

function renderPreview(body) {
  report.replaceChildren();
  const launchable = Boolean(body.launchable);
  setBanner(body.reason || (launchable ? "Path is ready." : "Path is blocked."), launchable ? "good" : "bad");
  const energy = body.energy || {};
  const fence = body.geofence || {};
  const rows = [
    ["Waypoints", String(body.waypoint_count ?? 0)],
    ["Path", formatMeters(body.distance_m)],
    ["Time", formatDuration(body.time_at_set_speed_s)],
    ["Fence", fence.ok ? "Inside" : "Blocked"],
  ];
  if (energy.placeholder) {
    rows.push(
      ["Battery", `${Math.round(energy.remaining_percent)}%`],
      ["Available", formatWh(energy.available_wh)],
      ["Survey", formatWh(energy.mission_wh)],
      ["Return", formatWh(energy.rth_wh)],
      ["Reserve", formatWh(energy.reserve_wh)],
      ["Required", formatWh(energy.required_wh)],
      ["Model", "Placeholder, not a measured vehicle"],
    );
  }
  report.append(factList(rows));
  const violations = (fence.violations || []).slice(0, 6);
  if (violations.length) {
    const list = document.createElement("ul");
    list.className = "violations";
    violations.forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item.detail;
      list.append(li);
    });
    report.append(list);
  }
  state.launchable = launchable;
  state.hadPreview = true;
  launchButton.disabled = !launchable;
  document.getElementById("stale").hidden = true;
  if (body.waypoints) drawPath(body.waypoints);
}

async function preview() {
  const body = await postJson("/api/preview", surveyBody());
  renderPreview(body);
}

async function launch() {
  const body = await postJson("/api/launch", surveyBody());
  const started = Boolean(body.started);
  setBanner(body.reason || (started ? "Mission started." : "Launch was refused."), started ? "good" : "bad");
  if (body.vehicle === "fake" && started) {
    const extra = document.createElement("p");
    extra.className = "note";
    extra.textContent = "Fake vehicle: the mission was recorded in this process and was not sent to a radio.";
    report.append(extra);
  }
  if (body.waypoints && body.waypoints.length) drawPath(body.waypoints);
  state.launchable = false;
  launchButton.disabled = true;
}

async function checkReserve() {
  const body = await postJson("/api/rth-check", {
    battery_percent: numberValue("battery"),
  });
  const rtl = body.action === "rtl";
  setBanner(body.reason, rtl ? "bad" : "good");
}

function setBusy(busy) {
  state.busy = busy;
  ["preview", "launch", "rth", "sample", "undo", "clear", "place-home"].forEach((id) => {
    const button = document.getElementById(id);
    if (id === "launch") {
      button.disabled = busy || !state.launchable;
    } else {
      button.disabled = busy;
    }
  });
}

async function run(action) {
  if (state.busy) return;
  setBusy(true);
  try {
    await action();
  } catch (error) {
    setBanner(error.message || "Request failed.", "bad");
    state.launchable = false;
    launchButton.disabled = true;
  } finally {
    setBusy(false);
  }
}

map.on("click", (event) => {
  if (state.placingHome) {
    state.home = event.latlng;
    state.placingHome = false;
    placeButton.classList.remove("is-on");
    document.body.classList.remove("is-placing");
    placeButton.textContent = "Place home";
  } else {
    state.vertices.push(event.latlng);
  }
  drawPolygon();
  markStale();
});

document.getElementById("undo").addEventListener("click", () => {
  state.vertices.pop();
  drawPolygon();
  markStale();
});

document.getElementById("clear").addEventListener("click", () => {
  state.vertices = [];
  state.home = null;
  state.hadPreview = false;
  state.launchable = false;
  pathLayer.setLatLngs([]);
  drawPolygon();
  launchButton.disabled = true;
  document.getElementById("stale").hidden = true;
  report.replaceChildren();
  const empty = document.createElement("p");
  empty.id = "empty";
  empty.className = "empty";
  empty.textContent = "Draw at least three corners and place home inside the field.";
  report.append(empty);
});

document.getElementById("place-home").addEventListener("click", () => {
  state.placingHome = !state.placingHome;
  placeButton.classList.toggle("is-on", state.placingHome);
  document.body.classList.toggle("is-placing", state.placingHome);
  placeButton.textContent = state.placingHome ? "Click the map" : "Place home";
});

document.getElementById("sample").addEventListener("click", () => {
  run(async () => {
    if (!state.status) throw new Error("Sample field is unavailable until status loads.");
    const field = state.status.sample_field;
    state.vertices = field.polygon.map((point) => L.latLng(point.lat, point.lon));
    state.home = L.latLng(field.home.lat, field.home.lon);
    state.placingHome = false;
    placeButton.classList.remove("is-on");
    document.body.classList.remove("is-placing");
    placeButton.textContent = "Place home";
    drawPolygon();
    await preview();
  });
});

document.getElementById("preview").addEventListener("click", () => run(preview));
document.getElementById("launch").addEventListener("click", () => run(launch));
document.getElementById("rth").addEventListener("click", () => run(checkReserve));

["spacing", "altitude", "speed", "angle", "margin", "battery"].forEach((id) => {
  document.getElementById(id).addEventListener("input", markStale);
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Backspace" || event.target.closest("input, textarea")) return;
  event.preventDefault();
  state.vertices.pop();
  drawPolygon();
  markStale();
});

async function boot() {
  map.setView([47.397742, 8.545594], 16);
  try {
    const response = await fetch("/api/status");
    if (!response.ok) throw new Error("status failed");
    state.status = await response.json();
  } catch (error) {
    setPill("Status unavailable");
    document.getElementById("model-note").textContent = "Could not load the planner status.";
    return;
  }
  const home = state.status.sample_field.home;
  map.setView([home.lat, home.lon], 17);
  document.getElementById("model-note").textContent = state.status.energy_model.note;
  if (state.status.vehicle === "fake") {
    setPill("Fake vehicle");
  } else {
    setPill("MAVSDK");
  }
  map.invalidateSize();
}

drawPolygon();
boot();
