"use strict";

var map = L.map("map").setView([48.2, 11.8], 10);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 19,
}).addTo(map);

var cellLayers = L.layerGroup().addTo(map);
var selectedCells = [];
var cellData = [];
var currentMaxCount = 0;
var currentGridM = 20;

// ---- Date helpers ----

function formatDateDE(isoStr) {
    if (!isoStr) return "-";
    var d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    var day = String(d.getDate()).padStart(2, "0");
    var month = String(d.getMonth() + 1).padStart(2, "0");
    var year = d.getFullYear();
    return day + "." + month + "." + year;
}

function initDateInputs() {
    var now = new Date();
    var year = now.getFullYear();
    document.getElementById("date-from").value = year + "-01-01";
    document.getElementById("date-to").value = year + "-12-31";
}

// ---- Status bar ----

function setStatus(msg, isError) {
    var bar = document.getElementById("status-bar");
    bar.textContent = msg;
    bar.classList.toggle("error", !!isError);
}

// ---- Users ----

async function loadUsers() {
    var container = document.getElementById("user-list");
    try {
        var resp = await fetch("/api/users");
        if (!resp.ok) throw new Error(await resp.text());
        var users = await resp.json();
        container.innerHTML = "";
        users.forEach(function (u) {
            var label = document.createElement("label");
            var cb = document.createElement("input");
            cb.type = "checkbox";
            cb.value = u.id;
            cb.checked = true;
            label.appendChild(cb);
            label.appendChild(document.createTextNode(" " + u.name));
            container.appendChild(label);
        });
    } catch (err) {
        container.innerHTML = '<span class="loading">Failed to load users</span>';
        setStatus("Error loading users: " + err.message, true);
    }
}

function getSelectedUserIds() {
    var checkboxes = document.querySelectorAll("#user-list input:checked");
    return Array.from(checkboxes).map(function (cb) { return cb.value; });
}

// ---- Color scale ----

function countToColor(count, maxCount) {
    if (maxCount <= 1) return "#22c55e";
    var ratio = (count - 1) / (maxCount - 1);
    var r, g, b;
    if (ratio < 0.5) {
        var t = ratio * 2;
        r = Math.round(34 + (249 - 34) * t);
        g = Math.round(197 + (115 - 197) * t);
        b = Math.round(94 + (22 - 94) * t);
    } else {
        var t2 = (ratio - 0.5) * 2;
        r = Math.round(249 + (220 - 249) * t2);
        g = Math.round(115 + (38 - 115) * t2);
        b = Math.round(22 + (38 - 22) * t2);
    }
    return "rgb(" + r + "," + g + "," + b + ")";
}

// ---- Grid cell to rectangle bounds ----

function cellToBounds(lat, lon, gridM) {
    // Half-cell offset in degrees
    var mPerLat = 111320;
    var mPerLon = 111320 * Math.cos(lat * Math.PI / 180);
    var dLat = gridM / mPerLat / 2;
    var dLon = gridM / mPerLon / 2;
    return [
        [lat - dLat, lon - dLon],
        [lat + dLat, lon + dLon]
    ];
}

// ---- Load segments ----

async function loadSegments() {
    var category = document.getElementById("category").value;
    var dateFrom = document.getElementById("date-from").value;
    var dateTo = document.getElementById("date-to").value;
    var userIds = getSelectedUserIds();

    var params = new URLSearchParams({ category: category });
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    if (userIds.length > 0) params.set("user_ids", userIds.join(","));

    setStatus("Loading segments...");
    document.getElementById("btn-load").disabled = true;

    try {
        var resp = await fetch("/api/segments?" + params.toString());
        if (!resp.ok) {
            var err = await resp.json();
            throw new Error(err.error || "Server error");
        }
        var data = await resp.json();
        renderCells(data);
        setStatus("Loaded " + data.cells.length + " cells");
    } catch (err) {
        setStatus("Error: " + err.message, true);
    } finally {
        document.getElementById("btn-load").disabled = false;
    }
}

function renderCells(data) {
    cellLayers.clearLayers();
    selectedCells = [];
    updateSelectionPanel();
    cellData = data.cells;
    currentGridM = data.grid_m || 20;

    if (!data.cells.length) return;

    var bounds = [];

    data.cells.forEach(function (cell, idx) {
        var rectBounds = cellToBounds(cell.lat, cell.lon, currentGridM);

        var rect = L.rectangle(rectBounds, {
            color: "#22c55e",
            fillColor: "#22c55e",
            fillOpacity: 0.6,
            weight: 1.5,
            opacity: 0.8,
            dashArray: "4 3",
        });

        rect._favIdx = idx;
        rect._favSelected = false;

        rect.on("mouseover", function () {
            showCellInfo(cell);
            if (!rect._favSelected) {
                rect.setStyle({ fillOpacity: 0.9, weight: 2.5 });
            }
        });

        rect.on("mouseout", function () {
            if (!rect._favSelected) {
                rect.setStyle({ fillOpacity: 0.6, weight: 1.5 });
            }
        });

        rect.on("click", function () {
            toggleCellSelection(rect, cell, idx);
        });

        cellLayers.addLayer(rect);
        bounds.push([cell.lat, cell.lon]);
    });

    if (bounds.length > 0) {
        map.fitBounds(bounds, { padding: [20, 20] });
    }

    // Initial coloring based on viewport
    recolorByViewport();
}

function recolorByViewport() {
    if (!cellData.length) return;

    var mapBounds = map.getBounds();

    // Find max count among cells visible in viewport
    var viewportMax = 0;
    cellLayers.eachLayer(function (layer) {
        var cell = cellData[layer._favIdx];
        if (mapBounds.contains([cell.lat, cell.lon])) {
            if (cell.count > viewportMax) viewportMax = cell.count;
        }
    });

    currentMaxCount = viewportMax || 1;

    // Recolor all cells (including off-screen, so they're correct when scrolled into view)
    cellLayers.eachLayer(function (layer) {
        if (layer._favSelected) return;
        var cell = cellData[layer._favIdx];
        var color = countToColor(cell.count, currentMaxCount);
        layer.setStyle({ color: color, fillColor: color });
    });
}

// ---- Hover info ----

async function showCellInfo(cell) {
    var panel = document.getElementById("segment-info");
    document.getElementById("info-count").textContent = cell.count;
    document.getElementById("info-last-date").textContent = "...";
    document.getElementById("info-last-name").textContent = "...";
    panel.classList.remove("hidden");

    try {
        var resp = await fetch("/api/segment_info?activity_ids=" + cell.activity_ids.join(","));
        if (!resp.ok) return;
        var info = await resp.json();
        document.getElementById("info-last-date").textContent = formatDateDE(info.last_date);
        document.getElementById("info-last-name").textContent = info.last_name || "-";
    } catch (_) {
        // silently ignore hover fetch errors
    }
}

// ---- Selection ----

function toggleCellSelection(rect, cell, idx) {
    rect._favSelected = !rect._favSelected;

    if (rect._favSelected) {
        rect.setStyle({ fillColor: "#3b82f6", color: "#3b82f6", fillOpacity: 0.8, weight: 2.5, dashArray: null });
        selectedCells.push({ idx: idx, cell: cell });
    } else {
        var color = countToColor(cell.count, currentMaxCount);
        rect.setStyle({
            fillColor: color,
            color: color,
            fillOpacity: 0.6,
            weight: 1.5,
            dashArray: "4 3",
        });
        selectedCells = selectedCells.filter(function (s) { return s.idx !== idx; });
    }
    updateSelectionPanel();
}

function updateSelectionPanel() {
    var panel = document.getElementById("selection-panel");
    var countEl = document.getElementById("selection-count");
    if (selectedCells.length > 0) {
        panel.classList.remove("hidden");
        countEl.textContent = selectedCells.length;
    } else {
        panel.classList.add("hidden");
    }
}

function clearSelection() {
    cellLayers.eachLayer(function (layer) {
        if (layer._favSelected) {
            layer._favSelected = false;
            var cell = cellData[layer._favIdx];
            var color = countToColor(cell.count, currentMaxCount);
            layer.setStyle({
                fillColor: color,
                color: color,
                fillOpacity: 0.6,
                weight: 1.5,
                dashArray: "4 3",
            });
        }
    });
    selectedCells = [];
    updateSelectionPanel();
}

// ---- GPX Export ----

async function exportGpx() {
    if (selectedCells.length === 0) return;

    var category = document.getElementById("category").value;
    var multiSegment = document.getElementById("multi-segment").checked;

    // Collect all unique activity_ids and cells from selected cells
    var allActivityIds = [];
    var allCellCoords = [];
    selectedCells.forEach(function (s) {
        s.cell.activity_ids.forEach(function (id) {
            if (allActivityIds.indexOf(id) === -1) allActivityIds.push(id);
        });
        allCellCoords.push(s.cell.cell);
    });

    var body = {
        category: category,
        multi_segment: multiSegment,
        segments: [{
            activity_ids: allActivityIds,
            cells: allCellCoords,
        }],
    };

    setStatus("Exporting GPX...");
    try {
        var resp = await fetch("/api/export_gpx", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (!resp.ok) {
            var err = await resp.json();
            throw new Error(err.error || "Export failed");
        }
        var blob = await resp.blob();
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = "favtracks_export.gpx";
        a.click();
        URL.revokeObjectURL(url);
        setStatus("GPX exported successfully");
    } catch (err) {
        setStatus("Export error: " + err.message, true);
    }
}

// ---- Recompute ----

async function recompute() {
    if (!confirm("This will recompute all segments from scratch. Continue?")) return;

    setStatus("Recomputing segments... this may take a while.");
    document.getElementById("btn-recompute").disabled = true;

    try {
        var resp = await fetch("/api/recompute", { method: "POST" });
        if (!resp.ok) {
            var err = await resp.json();
            throw new Error(err.error || "Recompute failed");
        }
        var summary = await resp.json();
        setStatus("Recompute done: " + summary.processed + " processed, " + summary.skipped + " skipped");
    } catch (err) {
        setStatus("Recompute error: " + err.message, true);
    } finally {
        document.getElementById("btn-recompute").disabled = false;
    }
}

// ---- Recolor on pan/zoom ----

map.on("moveend", recolorByViewport);

// ---- Init ----

document.getElementById("btn-load").addEventListener("click", loadSegments);
document.getElementById("btn-export").addEventListener("click", exportGpx);
document.getElementById("btn-clear-selection").addEventListener("click", clearSelection);
document.getElementById("btn-recompute").addEventListener("click", recompute);

initDateInputs();
loadUsers();
