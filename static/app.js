"use strict";

const map = L.map("map").setView([48.2, 11.8], 10);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 19,
}).addTo(map);

const segmentLayers = L.layerGroup().addTo(map);
let selectedSegments = [];
let segmentData = [];

// ---- Status bar ----

function setStatus(msg, isError) {
    const bar = document.getElementById("status-bar");
    bar.textContent = msg;
    bar.classList.toggle("error", !!isError);
}

// ---- Users ----

async function loadUsers() {
    const container = document.getElementById("user-list");
    try {
        const resp = await fetch("/api/users");
        if (!resp.ok) throw new Error(await resp.text());
        const users = await resp.json();
        container.innerHTML = "";
        users.forEach(function (u) {
            const label = document.createElement("label");
            const cb = document.createElement("input");
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
    const checkboxes = document.querySelectorAll("#user-list input:checked");
    return Array.from(checkboxes).map(function (cb) { return cb.value; });
}

// ---- Color scale ----

function countToColor(count, maxCount) {
    if (maxCount <= 1) return "#22c55e";
    const ratio = (count - 1) / (maxCount - 1);
    // green(0) -> orange(0.5) -> red(1)
    let r, g, b;
    if (ratio < 0.5) {
        const t = ratio * 2;
        r = Math.round(34 + (249 - 34) * t);
        g = Math.round(197 + (115 - 197) * t);
        b = Math.round(94 + (22 - 94) * t);
    } else {
        const t = (ratio - 0.5) * 2;
        r = Math.round(249 + (220 - 249) * t);
        g = Math.round(115 + (38 - 115) * t);
        b = Math.round(22 + (38 - 22) * t);
    }
    return "rgb(" + r + "," + g + "," + b + ")";
}

// ---- Load segments ----

async function loadSegments() {
    const category = document.getElementById("category").value;
    const dateFrom = document.getElementById("date-from").value;
    const dateTo = document.getElementById("date-to").value;
    const userIds = getSelectedUserIds();

    const params = new URLSearchParams({ category: category });
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    if (userIds.length > 0) params.set("user_ids", userIds.join(","));

    setStatus("Loading segments...");
    document.getElementById("btn-load").disabled = true;

    try {
        const resp = await fetch("/api/segments?" + params.toString());
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.error || "Server error");
        }
        const data = await resp.json();
        renderSegments(data, category);
        setStatus("Loaded " + data.segments.length + " segments");
    } catch (err) {
        setStatus("Error: " + err.message, true);
    } finally {
        document.getElementById("btn-load").disabled = false;
    }
}

function renderSegments(data, category) {
    segmentLayers.clearLayers();
    selectedSegments = [];
    updateSelectionPanel();
    segmentData = data.segments;

    if (!data.segments.length) return;

    const bounds = [];

    data.segments.forEach(function (seg, idx) {
        const latlngs = seg.coords.map(function (c) { return [c[0], c[1]]; });
        const color = countToColor(seg.count, data.max_count);

        const polyline = L.polyline(latlngs, {
            color: color,
            weight: 5,
            opacity: 0.8,
        });

        polyline._favIdx = idx;
        polyline._favSelected = false;

        polyline.on("mouseover", function () {
            showSegmentInfo(seg);
            if (!polyline._favSelected) {
                polyline.setStyle({ weight: 8, opacity: 1 });
            }
        });

        polyline.on("mouseout", function () {
            if (!polyline._favSelected) {
                polyline.setStyle({ weight: 5, opacity: 0.8 });
            }
        });

        polyline.on("click", function () {
            toggleSegmentSelection(polyline, seg, idx);
        });

        segmentLayers.addLayer(polyline);
        bounds.push.apply(bounds, latlngs);
    });

    if (bounds.length > 0) {
        map.fitBounds(bounds, { padding: [20, 20] });
    }
}

// ---- Hover info ----

async function showSegmentInfo(seg) {
    const panel = document.getElementById("segment-info");
    document.getElementById("info-count").textContent = seg.count;
    panel.classList.remove("hidden");

    try {
        const resp = await fetch("/api/segment_info?activity_ids=" + seg.activity_ids.join(","));
        if (!resp.ok) return;
        const info = await resp.json();
        document.getElementById("info-last-date").textContent = info.last_date || "-";
        document.getElementById("info-last-name").textContent = info.last_name || "-";
    } catch (_) {
        // silently ignore hover fetch errors
    }
}

// ---- Selection ----

function toggleSegmentSelection(polyline, seg, idx) {
    polyline._favSelected = !polyline._favSelected;

    if (polyline._favSelected) {
        polyline.setStyle({ weight: 8, opacity: 1, color: "#3b82f6", dashArray: "8 4" });
        selectedSegments.push({ idx: idx, seg: seg });
    } else {
        const maxCount = segmentData.length > 0
            ? Math.max.apply(null, segmentData.map(function (s) { return s.count; }))
            : 1;
        polyline.setStyle({
            weight: 5,
            opacity: 0.8,
            color: countToColor(seg.count, maxCount),
            dashArray: null,
        });
        selectedSegments = selectedSegments.filter(function (s) { return s.idx !== idx; });
    }
    updateSelectionPanel();
}

function updateSelectionPanel() {
    const panel = document.getElementById("selection-panel");
    const countEl = document.getElementById("selection-count");
    if (selectedSegments.length > 0) {
        panel.classList.remove("hidden");
        countEl.textContent = selectedSegments.length;
    } else {
        panel.classList.add("hidden");
    }
}

function clearSelection() {
    segmentLayers.eachLayer(function (layer) {
        if (layer._favSelected) {
            layer._favSelected = false;
            const seg = segmentData[layer._favIdx];
            const maxCount = Math.max.apply(null, segmentData.map(function (s) { return s.count; }));
            layer.setStyle({
                weight: 5,
                opacity: 0.8,
                color: countToColor(seg.count, maxCount),
                dashArray: null,
            });
        }
    });
    selectedSegments = [];
    updateSelectionPanel();
}

// ---- GPX Export ----

async function exportGpx() {
    if (selectedSegments.length === 0) return;

    const category = document.getElementById("category").value;
    const multiSegment = document.getElementById("multi-segment").checked;

    const body = {
        category: category,
        multi_segment: multiSegment,
        segments: selectedSegments.map(function (s) {
            return {
                activity_ids: s.seg.activity_ids,
                cells: s.seg.cells,
            };
        }),
    };

    setStatus("Exporting GPX...");
    try {
        const resp = await fetch("/api/export_gpx", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.error || "Export failed");
        }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
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
        const resp = await fetch("/api/recompute", { method: "POST" });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.error || "Recompute failed");
        }
        const summary = await resp.json();
        setStatus("Recompute done: " + summary.processed + " processed, " + summary.skipped + " skipped");
    } catch (err) {
        setStatus("Recompute error: " + err.message, true);
    } finally {
        document.getElementById("btn-recompute").disabled = false;
    }
}

// ---- Init ----

document.getElementById("btn-load").addEventListener("click", loadSegments);
document.getElementById("btn-export").addEventListener("click", exportGpx);
document.getElementById("btn-clear-selection").addEventListener("click", clearSelection);
document.getElementById("btn-recompute").addEventListener("click", recompute);

loadUsers();
