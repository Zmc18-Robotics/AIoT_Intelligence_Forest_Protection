// AIoT Intelligence Forest Protection Dashboard Client
const socket = io();

// UI Elements
const countJatuhAlami = document.getElementById("count-jatuh-alami");
const countDitebang = document.getElementById("count-ditebang");
const countApi = document.getElementById("count-api");
const countUltrasonik = document.getElementById("count-ultrasonik");

const valDistance = document.getElementById("val-distance");
const proximityBarFill = document.getElementById("proximity-bar-fill");
const obstacleWarning = document.getElementById("obstacle-warning");

const tower1Slider = document.getElementById("tower1-slider");
const tower2Slider = document.getElementById("tower2-slider");
const tower1AngleTxt = document.getElementById("tower1-angle-txt");
const tower2AngleTxt = document.getElementById("tower2-angle-txt");

const badgeRelay1 = document.getElementById("badge-relay1");
const badgeRelay2 = document.getElementById("badge-relay2");
const hwRgb = document.getElementById("hw-rgb");
const hwBuzzer = document.getElementById("hw-buzzer");
const hwFlame = document.getElementById("hw-flame");

const camStatus = document.getElementById("cam-status");
const espStatus = document.getElementById("esp-status");
const eventTableBody = document.getElementById("event-log-tbody");

// --- SOCKET EVENTS ---
socket.on("connect", () => {
  console.log("[SOCKET] Connected to Forest Protection Server");
});

socket.on("telemetry_update", (data) => {
  const currentDistance = data.distance_cm || 100;
  valDistance.textContent = currentDistance.toFixed(1);

  // Update Proximity Meter Bar (0 to 30cm scale)
  const clampedDist = Math.min(Math.max(currentDistance, 0), 30);
  const percentage = (clampedDist / 30) * 100;
  if (proximityBarFill) {
    proximityBarFill.style.width = `${percentage}%`;
  }

  // 1-8 cm Intruder Alert check
  if (currentDistance >= 1.0 && currentDistance <= 8.0) {
    obstacleWarning.textContent = `🚨 PERINGATAN: OBJEK MASUK (${currentDistance.toFixed(1)} cm)`;
    obstacleWarning.className = "status-alert";
    if (proximityBarFill) proximityBarFill.classList.add("proximity-bar-alert");
  } else {
    obstacleWarning.textContent = "STATUS: AREA AMAN (CLEAR)";
    obstacleWarning.className = "status-clean";
    if (proximityBarFill) proximityBarFill.classList.remove("proximity-bar-alert");
  }

  // Flame sensor HW status
  if (data.flame_sensor === 0) {
    hwFlame.textContent = "FLAME SENSOR TRIGGERED!";
    hwFlame.className = "hw-pill pill-red";
  } else {
    hwFlame.textContent = "NO FLAME";
    hwFlame.className = "hw-pill pill-green";
  }
});

socket.on("stats_update", (counters) => {
  if (counters.pohon_jatuh_alami !== undefined) countJatuhAlami.textContent = counters.pohon_jatuh_alami;
  if (counters.pohon_ditebang !== undefined) countDitebang.textContent = counters.pohon_ditebang;
  if (counters.insiden_api !== undefined) countApi.textContent = counters.insiden_api;
  if (counters.objek_masuk_ultrasonik !== undefined) countUltrasonik.textContent = counters.objek_masuk_ultrasonik;
});

socket.on("system_status_change", (status) => {
  if (status.esp32_main_connected !== undefined) {
    if (status.esp32_main_connected) {
      espStatus.innerHTML = '<i class="fa-solid fa-microchip"></i> <span>ESP32 Node: Connected</span>';
      espStatus.className = "badge badge-connected";
    } else {
      espStatus.innerHTML = '<i class="fa-solid fa-microchip"></i> <span>ESP32 Node: Disconnected</span>';
      espStatus.className = "badge badge-disconnected";
    }
  }
});

socket.on("new_incident", (event) => {
  // Prepend new row to table
  const emptyRow = document.getElementById("empty-row");
  if (emptyRow) emptyRow.remove();

  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td>#${event.id}</td>
    <td>${event.timestamp}</td>
    <td><span class="badge badge-${event.type.toLowerCase()}">${event.type}</span></td>
    <td>${event.zone}</td>
    <td>${event.description}</td>
    <td><span class="action-tag">LOGGED</span></td>
  `;
  eventTableBody.insertBefore(tr, eventTableBody.firstChild);

  // Flash UI elements depending on incident
  if (event.type === "API_TERDETEKSI") {
    hwRgb.textContent = "RED (FIRE ALERT)";
    hwRgb.className = "hw-pill pill-red";
    hwBuzzer.textContent = "ALARM ACTIVE";
    hwBuzzer.className = "hw-pill pill-red";
  } else if (event.type === "OBJEK_ULTRASONIK") {
    hwRgb.textContent = "YELLOW (WARNING)";
    hwRgb.className = "hw-pill pill-yellow";
  }
});

// Periodic sync with server state
setInterval(async () => {
  try {
    const res = await fetch("/api/telemetry");
    const data = await res.json();
    
    // Update servo sliders if not dragging
    tower1AngleTxt.textContent = data.tower1_servo;
    tower2AngleTxt.textContent = data.tower2_servo;

    if (data.relay1) {
      badgeRelay1.textContent = "PUMP 1 ON";
      badgeRelay1.className = "status-tag tag-on";
    } else {
      badgeRelay1.textContent = "PUMP 1 OFF";
      badgeRelay1.className = "status-tag tag-off";
    }

    if (data.relay2) {
      badgeRelay2.textContent = "PUMP 2 ON";
      badgeRelay2.className = "status-tag tag-on";
    } else {
      badgeRelay2.textContent = "PUMP 2 OFF";
      badgeRelay2.className = "status-tag tag-off";
    }

    if (data.esp32_cam_connected) {
      camStatus.innerHTML = '<i class="fa-solid fa-camera"></i> <span>ESP32-CAM: Online</span>';
      camStatus.className = "badge badge-connected";
    }
  } catch (err) {
    // console.log(err);
  }
}, 1500);

// --- MANUAL CONTROL ACTIONS ---
function updateServo(tower, angle) {
  if (tower === 1) tower1AngleTxt.textContent = angle;
  if (tower === 2) tower2AngleTxt.textContent = angle;

  fetch("/api/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "SET_SERVO", tower: tower, angle: parseInt(angle) })
  });
}

function toggleRelay(relay, state) {
  fetch("/api/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "TOGGLE_RELAY", relay: relay, status: state })
  });
}

function testBuzzer() {
  fetch("/api/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "TEST_BUZZER" })
  });
}

function setRGB(color) {
  fetch("/api/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "SET_RGB", color: color })
  });
}

function captureSnapshot() {
  fetch("/api/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "CAPTURE_SNAPSHOT" })
  })
  .then(res => res.json())
  .then(data => {
    if (data.status === "success") {
      alert(`📸 Snapshot berhasil disimpan ke: ${data.file}\nBuka labeling_tool.py untuk melabeli objek!`);
    } else {
      alert(`Gagal mengambil snapshot: ${data.message}`);
    }
  })
  .catch(err => alert("Gagal terhubung ke server."));
}

