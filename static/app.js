"use strict";

var map = L.map("map").setView([48.2, 11.8], 10);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 19,
}).addTo(map);

var trackLayers = L.layerGroup().addTo(map);   // grey base tracks
var edgeLayers = L.layerGroup().addTo(map);    // colored frequency overlay
var selectedEdges = [];
var edgeData = [];
var currentMaxCount = 0;

// ISO dates for API calls, kept in sync by flatpickr
var dateFromISO = "";
var dateToISO = "";

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
    dateFromISO = year + "-01-01";
    dateToISO   = year + "-12-31";

    flatpickr("#date-from", {
        locale: "de",
        dateFormat: "d.m.Y",
        defaultDate: dateFromISO,
        onChange: function (selectedDates, dateStr, instance) {
            if (selectedDates[0]) {
                dateFromISO = selectedDates[0].toISOString().slice(0, 10);
            }
        },
    });

    flatpickr("#date-to", {
        locale: "de",
        dateFormat: "d.m.Y",
        defaultDate: dateToISO,
        onChange: function (selectedDates, dateStr, instance) {
            if (selectedDates[0]) {
                dateToISO = selectedDates[0].toISOString().slice(0, 10);
            }
        },
    });
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
// 5-stop gradient: blue → cyan → green → yellow → orange → red
// Uses logarithmic scaling so low-frequency segments spread out more

var COLOR_STOPS = [
    [41, 121, 255],    // blue
    [0, 200, 200],     // cyan
    [34, 197, 94],     // green
    [250, 204, 21],    // yellow
    [249, 115, 22],    // orange
    [220, 38, 38],     // red
];

function countToColor(count, maxCount) {
    if (maxCount <= 1) return "rgb(41,121,255)";
    // Logarithmic scale for better spread
    var logCount = Math.log(count);
    var logMax = Math.log(maxCount);
    var ratio = logCount / logMax;
    ratio = Math.max(0, Math.min(1, ratio));

    // Map ratio to color stops
    var pos = ratio * (COLOR_STOPS.length - 1);
    var idx = Math.min(Math.floor(pos), COLOR_STOPS.length - 2);
    var t = pos - idx;

    var c0 = COLOR_STOPS[idx];
    var c1 = COLOR_STOPS[idx + 1];
    var r = Math.round(c0[0] + (c1[0] - c0[0]) * t);
    var g = Math.round(c0[1] + (c1[1] - c0[1]) * t);
    var b = Math.round(c0[2] + (c1[2] - c0[2]) * t);
    return "rgb(" + r + "," + g + "," + b + ")";
}

// ---- Load segments ----

async function loadSegments() {
    var category = document.getElementById("category").value;
    var userIds = getSelectedUserIds();

    var params = new URLSearchParams({ category: category });
    if (dateFromISO) params.set("date_from", dateFromISO);
    if (dateToISO)   params.set("date_to",   dateToISO);
    if (userIds.length > 0) params.set("user_ids", userIds.join(","));

    setStatus("Loading tracks and segments...");
    document.getElementById("btn-load").disabled = true;

    try {
        // Fetch both tracks and segments in parallel
        var [tracksResp, segmentsResp] = await Promise.all([
            fetch("/api/tracks?"    + params.toString()),
            fetch("/api/segments?"  + params.toString()),
        ]);
        if (!tracksResp.ok)   throw new Error("Failed to load tracks");
        if (!segmentsResp.ok) throw new Error((await segmentsResp.json()).error || "Server error");

        var tracksData   = await tracksResp.json();
        var data = await segmentsResp.json();
        renderTracks(tracksData.tracks || []);
        renderEdges(data);
        showActivityStats(data);
        setStatus("Loaded " + (tracksData.tracks || []).length + " tracks, " + data.edges.length + " segments");
    } catch (err) {
        setStatus("Error: " + err.message, true);
    } finally {
        document.getElementById("btn-load").disabled = false;
    }
}

function renderTracks(tracks) {
    trackLayers.clearLayers();
    if (!tracks.length) return;

    var bounds = [];
    tracks.forEach(function (track) {
        var latlngs = track.coords.map(function (c) { return [c[0], c[1]]; });
        L.polyline(latlngs, {
            color: "#1565c0",
            weight: 4,
            opacity: 0.75,
            dashArray: "6 5",
            lineCap: "round",
            lineJoin: "round",
        }).addTo(trackLayers);
        bounds.push(latlngs[0]);
        bounds.push(latlngs[latlngs.length - 1]);
    });

    if (bounds.length > 0) {
        map.fitBounds(bounds, { padding: [20, 20] });
    }
}

function showActivityStats(data) {
    var panel = document.getElementById("activity-stats");
    document.getElementById("stats-filtered").textContent = data.filtered_activities || 0;
    document.getElementById("stats-total").textContent = data.total_activities || 0;
    panel.classList.remove("hidden");
}

function renderEdges(data) {
    edgeLayers.clearLayers();
    selectedEdges = [];
    // fit bounds driven by tracks; only fit here if no tracks loaded
    if (!trackLayers.getLayers().length && data.edges.length) {
        var b = data.edges.map(function (e) { return e.coords; }).flat();
        if (b.length) map.fitBounds(b, { padding: [20, 20] });
    }
    updateSelectionPanel();
    edgeData = data.edges;

    if (!data.edges.length) return;

    currentMaxCount = data.max_count || 1;

    data.edges.forEach(function (edge, idx) {
        var latlngs = edge.coords.map(function (c) { return [c[0], c[1]]; });
        var color = countToColor(edge.count, currentMaxCount);

        var lineStyle = edge.count === 1
            ? { color: color, weight: 4, opacity: 0.7, dashArray: "6 5", lineCap: "round" }
            : { color: color, weight: 5, opacity: 0.8, lineCap: "round" };
        var line = L.polyline(latlngs, lineStyle);

        line._favIdx = idx;
        line._favSelected = false;

        line.on("mouseover", function () {
            showEdgeInfo(edge);
            if (!line._favSelected) {
                line.setStyle({ weight: 8, opacity: 1 });
            }
        });

        line.on("mouseout", function () {
            if (!line._favSelected) {
                line.setStyle(lineStyle);
            }
        });

        line.on("click", function () {
            toggleEdgeSelection(line, edge, idx);
        });

        edgeLayers.addLayer(line);
    });
}

// ---- Hover info ----

function truncate(str, max) {
    if (!str) return "-";
    return str.length > max ? str.slice(0, max - 1) + "\u2026" : str;
}

async function showEdgeInfo(edge) {
    var panel = document.getElementById("segment-info");
    document.getElementById("info-count").textContent = edge.count;
    document.getElementById("info-table-wrap").innerHTML = "<em>Loading\u2026</em>";
    panel.classList.remove("hidden");

    try {
        var resp = await fetch("/api/segment_info?activity_ids=" + edge.activity_ids.join(","));
        if (!resp.ok) return;
        var info = await resp.json();
        var rows = (info.activities || []).map(function (a) {
            return "<tr><td>" + truncate(a.user, 12) + "</td>"
                 + "<td>" + formatDateDE(a.date) + "</td>"
                 + "<td title=\"" + (a.name || "").replace(/"/g, "&quot;") + "\">"
                 + truncate(a.name, 24) + "</td></tr>";
        });
        var html = "<table class=\"info-table\"><thead><tr>"
                 + "<th>User</th><th>Date</th><th>Activity</th>"
                 + "</tr></thead><tbody>" + rows.join("") + "</tbody></table>";
        document.getElementById("info-table-wrap").innerHTML = html;
    } catch (_) {
        // silently ignore hover fetch errors
    }
}

// ---- Selection ----

function toggleEdgeSelection(line, edge, idx) {
    line._favSelected = !line._favSelected;

    if (line._favSelected) {
        line.setStyle({ color: "#3b82f6", weight: 8, opacity: 1 });
        selectedEdges.push({ idx: idx, edge: edge });
    } else {
        var color = countToColor(edge.count, currentMaxCount);
        var restoreStyle = edge.count === 1
            ? { color: color, weight: 4, opacity: 0.7, dashArray: "6 5", lineCap: "round" }
            : { color: color, weight: 5, opacity: 0.8, lineCap: "round" };
        line.setStyle(restoreStyle);
        selectedEdges = selectedEdges.filter(function (s) { return s.idx !== idx; });
    }
    updateSelectionPanel();
}

function updateSelectionPanel() {
    var panel = document.getElementById("selection-panel");
    var countEl = document.getElementById("selection-count");
    if (selectedEdges.length > 0) {
        panel.classList.remove("hidden");
        countEl.textContent = selectedEdges.length;
    } else {
        panel.classList.add("hidden");
    }
}

function clearSelection() {
    edgeLayers.eachLayer(function (layer) {
        if (layer._favSelected) {
            layer._favSelected = false;
            var edge = edgeData[layer._favIdx];
            var color = countToColor(edge.count, currentMaxCount);
            var restoreStyle = edge.count === 1
                ? { color: color, weight: 4, opacity: 0.7, dashArray: "6 5", lineCap: "round" }
                : { color: color, weight: 5, opacity: 0.8, lineCap: "round" };
            layer.setStyle(restoreStyle);
        }
    });
    selectedEdges = [];
    updateSelectionPanel();
}

// ---- GPX Export ----

async function exportGpx() {
    if (selectedEdges.length === 0) return;

    var category = document.getElementById("category").value;
    var multiSegment = document.getElementById("multi-segment").checked;

    var allActivityIds = [];
    var allCellCoords = [];
    selectedEdges.forEach(function (s) {
        s.edge.activity_ids.forEach(function (id) {
            if (allActivityIds.indexOf(id) === -1) allActivityIds.push(id);
        });
        s.edge.cells.forEach(function (c) {
            allCellCoords.push(c);
        });
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

function recompute() {
    if (!confirm("This will recompute all segments from scratch. Continue?")) return;

    document.getElementById("btn-recompute").disabled = true;
    setStatus("Recomputing: starting...");

    fetch("/api/recompute", { method: "POST" }).then(function (resp) {
        var reader = resp.body.getReader();
        var decoder = new TextDecoder();
        var buffer = "";

        function read() {
            reader.read().then(function (result) {
                if (result.done) {
                    document.getElementById("btn-recompute").disabled = false;
                    return;
                }
                buffer += decoder.decode(result.value, { stream: true });
                var lines = buffer.split("\n");
                buffer = lines.pop();
                lines.forEach(function (line) {
                    if (line.startsWith("data: ")) {
                        try {
                            var data = JSON.parse(line.substring(6));
                            if (data.error) {
                                setStatus("Recompute error: " + data.error, true);
                            } else if (data.done) {
                                setStatus("Recompute done: " + data.processed + " processed, " + data.skipped + " skipped");
                            } else {
                                var done = data.processed + data.skipped;
                                setStatus("Recomputing: " + done + " / " + data.total + " (" + data.processed + " processed, " + data.skipped + " skipped)");
                            }
                        } catch (_) {}
                    }
                });
                read();
            });
        }
        read();
    }).catch(function (err) {
        setStatus("Recompute error: " + err.message, true);
        document.getElementById("btn-recompute").disabled = false;
    });
}

// ---- Init ----

document.getElementById("btn-load").addEventListener("click", loadSegments);
document.getElementById("btn-export").addEventListener("click", exportGpx);
document.getElementById("btn-clear-selection").addEventListener("click", clearSelection);
document.getElementById("btn-recompute").addEventListener("click", recompute);

initDateInputs();
loadUsers();
