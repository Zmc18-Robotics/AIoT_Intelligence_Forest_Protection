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
  const distVal = (typeof data.distance_cm === "number") ? data.distance_cm : 100;
  if (distVal >= 1.0 && distVal <= 400) {
    valDistance.textContent = distVal.toFixed(1);
  } else {
    valDistance.textContent = "--";
  }

  // Update Proximity Meter Bar (0 to 30cm scale)
  const clampedDist = Math.min(Math.max(distVal, 0), 30);
  const percentage = (clampedDist / 30) * 100;
  if (proximityBarFill) {
    proximityBarFill.style.width = `${percentage}%`;
  }

  // 1-8 cm Intruder Alert check
  if (distVal >= 1.0 && distVal <= 8.0) {
    obstacleWarning.textContent = `🚨 PERINGATAN: OBJEK MASUK (${distVal.toFixed(1)} cm)`;
    obstacleWarning.className = "status-alert";
    if (proximityBarFill) proximityBarFill.classList.add("proximity-bar-alert");
  } else if (distVal > 8.0) {
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

// Reset warning ultrasonik saat area kembali aman (> 12 cm)
socket.on("obstacle_clear", (data) => {
  if (obstacleWarning) {
    obstacleWarning.textContent = "STATUS: AREA AMAN (CLEAR)";
    obstacleWarning.className = "status-clean";
  }
  if (proximityBarFill) {
    proximityBarFill.classList.remove("proximity-bar-alert");
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
  if (status.esp32_cam_connected !== undefined) {
    if (status.esp32_cam_connected) {
      camStatus.innerHTML = '<i class="fa-solid fa-camera"></i> <span>ESP32-CAM: Online</span>';
      camStatus.className = "badge badge-connected";
    } else {
      camStatus.innerHTML = '<i class="fa-solid fa-camera"></i> <span>ESP32-CAM: Offline</span>';
      camStatus.className = "badge badge-disconnected";
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
    <td><span class="action-tag">TERCATAT</span></td>
  `;
  eventTableBody.insertBefore(tr, eventTableBody.firstChild);

  // Perbarui angka total log
  const filterCountTxt = document.getElementById("filter-count-txt");
  if (filterCountTxt) {
    const cur = parseInt(filterCountTxt.textContent || "0", 10);
    filterCountTxt.textContent = cur + 1;
  }

  // Flash UI elements depending on incident
  if (event.type === "API_TERDETEKSI") {
    hwRgb.textContent = "RED (FIRE ALERT)";
    hwRgb.className = "hw-pill pill-red";
    hwBuzzer.textContent = "ALARM ACTIVE";
    hwBuzzer.className = "hw-pill pill-red";
  } else if (event.type === "OBJEK_ULTRASONIK") {
    hwRgb.textContent = "YELLOW (WARNING)";
    hwRgb.className = "hw-pill pill-yellow";
  } else if (event.type === "POHON_JATUH_ALAMI") {
    hwRgb.textContent = "GREEN (TREE FALL)";
    hwRgb.className = "hw-pill pill-green";
  } else if (event.type === "POHON_DITEBANG") {
    hwRgb.textContent = "ORANGE (LOGGING)";
    hwRgb.className = "hw-pill pill-orange";
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

// --- INSTANT MANUAL CONTROL ACTIONS (WEBSOCKET + REST FALLBACK) ---
let servoThrottleTimer = null;
let pendingServoUpdates = {};

function updateServo(tower, angle) {
  const angleInt = parseInt(angle, 10);
  if (tower === 1) tower1AngleTxt.textContent = angleInt;
  if (tower === 2) tower2AngleTxt.textContent = angleInt;

  pendingServoUpdates[tower] = angleInt;

  if (!servoThrottleTimer) {
    socket.emit("manual_control", { action: "SET_SERVO", tower: tower, angle: angleInt });
    fetch("/api/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "SET_SERVO", tower: tower, angle: angleInt })
    }).catch(() => {});

    servoThrottleTimer = setTimeout(() => {
      servoThrottleTimer = null;
      for (const t in pendingServoUpdates) {
        socket.emit("manual_control", { action: "SET_SERVO", tower: parseInt(t), angle: pendingServoUpdates[t] });
        fetch("/api/control", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "SET_SERVO", tower: parseInt(t), angle: pendingServoUpdates[t] })
        }).catch(() => {});
      }
      pendingServoUpdates = {};
    }, 40);
  }
}

function toggleRelay(relay, state) {
  if (relay === 1) {
    badgeRelay1.textContent = state ? "PUMP 1 ON" : "PUMP 1 OFF";
    badgeRelay1.className = state ? "status-tag tag-on" : "status-tag tag-off";
  } else if (relay === 2) {
    badgeRelay2.textContent = state ? "PUMP 2 ON" : "PUMP 2 OFF";
    badgeRelay2.className = state ? "status-tag tag-on" : "status-tag tag-off";
  }

  socket.emit("manual_control", { action: "TOGGLE_RELAY", relay: relay, status: state });
  fetch("/api/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "TOGGLE_RELAY", relay: relay, status: state })
  }).catch(() => {});
}

function testBuzzer() {
  socket.emit("manual_control", { action: "TEST_BUZZER" });
  fetch("/api/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "TEST_BUZZER" })
  }).catch(() => {});
}

function setRGB(color) {
  socket.emit("manual_control", { action: "SET_RGB", color: color });
  fetch("/api/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "SET_RGB", color: color })
  }).catch(() => {});
}

// Menerima update status aktuator dari server secara realtime
socket.on("actuator_status_update", (data) => {
  if (data.tower1_servo !== undefined && !pendingServoUpdates[1]) {
    tower1AngleTxt.textContent = data.tower1_servo;
    tower1Slider.value = data.tower1_servo;
  }
  if (data.tower2_servo !== undefined && !pendingServoUpdates[2]) {
    tower2AngleTxt.textContent = data.tower2_servo;
    tower2Slider.value = data.tower2_servo;
  }
  if (data.relay1 !== undefined) {
    badgeRelay1.textContent = data.relay1 ? "PUMP 1 ON" : "PUMP 1 OFF";
    badgeRelay1.className = data.relay1 ? "status-tag tag-on" : "status-tag tag-off";
  }
  if (data.relay2 !== undefined) {
    badgeRelay2.textContent = data.relay2 ? "PUMP 2 ON" : "PUMP 2 OFF";
    badgeRelay2.className = data.relay2 ? "status-tag tag-on" : "status-tag tag-off";
  }
  if (data.rgb_color !== undefined) {
    hwRgb.textContent = data.rgb_color;
  }
});

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

// --- KALIBRASI 4 TITIK AREA (AREA 1 & AREA 2) ---
let currentZonesData = null;

async function loadZones() {
  try {
    const res = await fetch("/api/zones");
    currentZonesData = await res.json();
    renderZoneInputs();
  } catch (err) {
    console.error("Gagal memuat titik area:", err);
  }
}

function renderZoneInputs() {
  if (!currentZonesData) return;
  const a1Container = document.getElementById("area1-inputs");
  const a2Container = document.getElementById("area2-inputs");
  if (!a1Container || !a2Container) return;

  function buildInputs(areaKey) {
    const pts = currentZonesData[areaKey]?.points || [];
    return pts.map((p, idx) => `
      <div class="zone-point-row">
        <span><strong>${p.name || `P${idx+1}`}</strong></span>
        <div class="zone-input-group">
          <span>X:</span>
          <input type="number" step="0.01" min="0" max="1" class="zone-input" id="${areaKey}-x-${idx}" value="${p.x}">
          <span>Y:</span>
          <input type="number" step="0.01" min="0" max="1" class="zone-input" id="${areaKey}-y-${idx}" value="${p.y}">
        </div>
      </div>
    `).join("");
  }

  a1Container.innerHTML = buildInputs("area1");
  a2Container.innerHTML = buildInputs("area2");
}

function openZoneModal() {
  const modal = document.getElementById("zone-modal");
  if (modal) modal.classList.add("active");
  loadZones();
}

function closeZoneModal() {
  const modal = document.getElementById("zone-modal");
  if (modal) modal.classList.remove("active");
}

async function saveZones() {
  if (!currentZonesData) return;
  
  ["area1", "area2"].forEach(areaKey => {
    currentZonesData[areaKey].points.forEach((p, idx) => {
      const inX = document.getElementById(`${areaKey}-x-${idx}`);
      const inY = document.getElementById(`${areaKey}-y-${idx}`);
      if (inX) p.x = Math.max(0, Math.min(1, parseFloat(inX.value) || 0));
      if (inY) p.y = Math.max(0, Math.min(1, parseFloat(inY.value) || 0));
    });
  });

  try {
    const res = await fetch("/api/zones", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentZonesData)
    });
    const result = await res.json();
    if (result.status === "success") {
      alert("✅ Titik penentu Area 1 & Area 2 berhasil disimpan!");
      closeZoneModal();
    } else {
      alert("Gagal menyimpan titik area: " + result.message);
    }
  } catch (err) {
    alert("Gagal menghubungi server untuk menyimpan area.");
  }
}

function resetZonesDefault() {
  if (!currentZonesData) return;
  currentZonesData.area1.points = [
    { name: "P1 (Kiri Atas)",   x: 0.05, y: 0.15 },
    { name: "P2 (Kanan Atas)",  x: 0.45, y: 0.15 },
    { name: "P3 (Kanan Bawah)", x: 0.45, y: 0.85 },
    { name: "P4 (Kiri Bawah)",  x: 0.05, y: 0.85 }
  ];
  currentZonesData.area2.points = [
    { name: "P1 (Kiri Atas)",   x: 0.55, y: 0.15 },
    { name: "P2 (Kanan Atas)",  x: 0.95, y: 0.15 },
    { name: "P3 (Kanan Bawah)", x: 0.95, y: 0.85 },
    { name: "P4 (Kiri Bawah)",  x: 0.55, y: 0.85 }
  ];
  renderZoneInputs();
}

socket.on("zones_updated", (zones) => {
  currentZonesData = zones;
  renderZoneInputs();
});

// --- PENGATURAN IP JARINGAN (ESP32 MAIN & ESP32-CAM) ---
async function openNetworkModal() {
  const modal = document.getElementById("network-modal");
  if (modal) modal.classList.add("active");
  try {
    const res = await fetch("/api/network");
    const data = await res.json();
    const inEsp = document.getElementById("net-esp32-ip");
    const inCam = document.getElementById("net-cam-ip");
    if (inEsp) inEsp.value = data.esp32_main_ip || "192.168.1.100";
    if (inCam) inCam.value = data.esp32_cam_ip || "192.168.1.101";
  } catch (err) {
    console.error("Gagal membaca IP:", err);
  }
}

function closeNetworkModal() {
  const modal = document.getElementById("network-modal");
  if (modal) modal.classList.remove("active");
}

async function saveNetworkConfig() {
  const inEsp = document.getElementById("net-esp32-ip");
  const inCam = document.getElementById("net-cam-ip");
  if (!inEsp || !inCam) return;

  const espIp = inEsp.value.trim();
  const camIp = inCam.value.trim();

  try {
    const res = await fetch("/api/network", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        esp32_main_ip: espIp,
        esp32_cam_ip: camIp
      })
    });
    const result = await res.json();
    if (result.status === "success") {
      alert(`✅ IP Berhasil Diperbarui!\nESP32 Main : ${espIp}:8888\nESP32-CAM  : ${camIp}:80\nServer sedang menghubungkan ulang...`);
      closeNetworkModal();
    }
  } catch (err) {
    alert("Gagal menyimpan konfigurasi IP.");
  }
}

// --- LIVE DATA SCANNING & FILTERING ---
function filterEventsLive() {
  const searchInput = document.getElementById("log-search-input");
  const dateInput = document.getElementById("log-date-input");
  const typeSelect = document.getElementById("log-type-select");
  const countDisplay = document.getElementById("filter-count-txt");
  const statusDesc = document.getElementById("filter-status-desc");

  const searchKeyword = searchInput ? searchInput.value.trim().toLowerCase() : "";
  const selectedDate = dateInput ? dateInput.value.trim() : "";
  const selectedType = typeSelect ? typeSelect.value.trim().toUpperCase() : "ALL";

  const rows = eventTableBody.querySelectorAll("tr");
  let visibleCount = 0;

  rows.forEach(row => {
    if (row.id === "empty-row") return;

    const rowText = row.textContent.toLowerCase();
    const rowTypeBadge = row.querySelector(".badge");
    const rowType = rowTypeBadge ? rowTypeBadge.textContent.trim().toUpperCase() : "";
    const cells = row.querySelectorAll("td");
    const timestamp = cells.length > 1 ? cells[1].textContent.trim() : "";

    let matchSearch = !searchKeyword || rowText.includes(searchKeyword);
    let matchType = (selectedType === "ALL") || (rowType === selectedType);
    let matchDate = !selectedDate || timestamp.startsWith(selectedDate);

    if (matchSearch && matchType && matchDate) {
      row.style.display = "";
      visibleCount++;
    } else {
      row.style.display = "none";
    }
  });

  if (countDisplay) countDisplay.textContent = visibleCount;
  if (statusDesc) {
    if (searchKeyword || selectedDate || selectedType !== "ALL") {
      statusDesc.textContent = `Pindaian Aktif: ${visibleCount} hasil cocok`;
      statusDesc.style.color = "#38bdf8";
    } else {
      statusDesc.textContent = "Semua riwayat database lokal dimuat";
      statusDesc.style.color = "var(--color-cyan)";
    }
  }
}

function setDateFilterToday() {
  const dateInput = document.getElementById("log-date-input");
  if (dateInput) {
    const today = new Date().toISOString().split("T")[0];
    dateInput.value = today;
    filterEventsLive();
  }
}

function resetDateFilter() {
  const searchInput = document.getElementById("log-search-input");
  const dateInput = document.getElementById("log-date-input");
  const typeSelect = document.getElementById("log-type-select");
  if (searchInput) searchInput.value = "";
  if (dateInput) dateInput.value = "";
  if (typeSelect) typeSelect.value = "ALL";
  filterEventsLive();
}

async function loadAllEventsFromServer() {
  try {
    const res = await fetch("/api/database");
    const data = await res.json();
    const events = data.events || [];
    renderEventTable(events);
    filterEventsLive();
  } catch (err) {
    console.error("Gagal memuat database:", err);
  }
}

function renderEventTable(events) {
  eventTableBody.innerHTML = "";
  if (!events || events.length === 0) {
    eventTableBody.innerHTML = '<tr id="empty-row"><td colspan="6" class="text-center">Belum ada aktivitas insiden. Sistem memantau secara realtime...</td></tr>';
    return;
  }

  events.forEach(evt => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>#${evt.id}</td>
      <td>${evt.timestamp}</td>
      <td><span class="badge badge-${evt.type.toLowerCase()}">${evt.type}</span></td>
      <td>${evt.zone}</td>
      <td>${evt.description}</td>
      <td><span class="action-tag">TERCATAT</span></td>
    `;
    eventTableBody.appendChild(tr);
  });
}

function copyWifiLink() {
  const wifiEl = document.getElementById("wifi-url-display");
  const url = wifiEl ? wifiEl.textContent.trim() : window.location.origin;
  navigator.clipboard.writeText(url).then(() => {
    alert(`📋 Link Akses WiFi Disalin!\n${url}\n\nBuka link ini di browser HP atau perangkat apa pun yang terhubung ke WiFi yang sama.`);
  }).catch(() => {
    prompt("Salin link ini untuk dibuka di HP:", url);
  });
}

// Download CSV Langsung dengan Blob (Mencegah unduhan 0 KB di browser)
async function downloadCSVDirect(e) {
  if (e) e.preventDefault();
  try {
    const res = await fetch("/api/database/export_csv");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    if (!blob || blob.size === 0) {
      alert("⚠️ Peringatan: Berkas CSV kosong (0 KB). Pastikan data tersimpan di database.");
      return;
    }
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    const tsStr = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
    const filename = `forest_database_events_${tsStr}.csv`;

    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.style.display = "none";
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    }, 1500);
  } catch (err) {
    console.error("Gagal mendownload CSV via fetch blob:", err);
    window.location.href = "/api/database/export_csv";
  }
}


// =============================================================================
// ⚠️  HARDWARE DANGER ALERT — Sensor Api Hardware ESP32 (GPIO 35)
// =============================================================================
// Banner merah mencolok yang muncul jika api fisik menjangkau chip ESP32.
// Dikendalikan oleh WebSocket event "hardware_danger_alert" dari server.

const hwDangerBanner = document.getElementById("hardware-danger-banner");
const hwDangerMsg    = document.getElementById("hw-danger-msg");
const hwDangerDetail = document.getElementById("hw-danger-detail");
const hwDangerTs     = document.getElementById("hw-danger-ts");

let _hwDangerBeepInterval = null;

function _playDangerBeep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "square";
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    gain.gain.setValueAtTime(0.18, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + 0.3);
  } catch (e) {/* AudioContext opsional */ }
}

socket.on("hardware_danger_alert", (data) => {
  if (!hwDangerBanner) return;

  if (data.active) {
    // Tampilkan banner
    hwDangerBanner.style.display = "block";
    document.body.classList.add("hw-danger-active");

    if (data.message)  hwDangerMsg.textContent    = data.message;
    if (data.detail)   hwDangerDetail.textContent = data.detail;
    if (data.timestamp) hwDangerTs.textContent = `[${data.timestamp}]`;

    // Beep peringatan berulang setiap 5 detik
    _playDangerBeep();
    if (!_hwDangerBeepInterval) {
      _hwDangerBeepInterval = setInterval(_playDangerBeep, 5000);
    }

    console.error("[⚠️ HARDWARE DANGER] Api menjangkau ESP32!", data);
  } else {
    // Sembunyikan banner saat sensor kembali normal
    hwDangerBanner.style.display = "none";
    document.body.classList.remove("hw-danger-active");
    if (_hwDangerBeepInterval) {
      clearInterval(_hwDangerBeepInterval);
      _hwDangerBeepInterval = null;
    }
    console.info("[✅ HARDWARE SAFE] Sensor api hardware ESP32 kembali normal.");
  }
});

