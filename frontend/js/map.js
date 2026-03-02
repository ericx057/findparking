var ParkingMap = (function () {
    var map = null;
    var pinLayer = null;
    var tileLayer = null;
    var markers = {};
    var lotDataCache = {};
    var rankMarkers = {};
    var userMarker = null;
    var userCircle = null;
    var mapClickCallback = null;

    var TILE_URLS = {
        dark: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
        light: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'
    };

    var TILE_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>';

    var PIN_COLORS = {
        high: '#22c55e',
        medium: '#eab308',
        low: '#ef4444',
        stale: '#6b7280'
    };

    var SIGNAL_LABELS = {
        'camera': 'CAM',
        'heuristic_baseline': 'EST',
        'sports_event': 'EVENT',
        'weather': 'WX',
        'time_weights': 'TIME',
        'road_disruptions': 'ROAD'
    };

    function escapeHtml(str) {
        if (str == null) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    var FALLBACK_CENTER = [43.4643, -80.5204];
    var FALLBACK_ZOOM = 14;

    function initMap(center, zoom, theme) {
        var mapCenter = center || FALLBACK_CENTER;
        var mapZoom = zoom || FALLBACK_ZOOM;

        map = L.map('map', {
            center: mapCenter,
            zoom: mapZoom,
            zoomControl: true
        });

        var tileUrl = TILE_URLS[theme] || TILE_URLS.dark;
        tileLayer = L.tileLayer(tileUrl, {
            attribution: TILE_ATTRIBUTION,
            subdomains: 'abcd',
            maxZoom: 19
        }).addTo(map);

        pinLayer = L.layerGroup().addTo(map);

        return map;
    }

    function setView(center, zoom) {
        if (map && center) {
            map.setView(center, zoom || map.getZoom(), { animate: true });
        }
    }

    function clearPins() {
        if (pinLayer) {
            pinLayer.clearLayers();
        }
        markers = {};
    }

    function getAvailability(lot) {
        if (lot.freshness_seconds > 600) return 'stale';
        return lot.availability || 'stale';
    }

    function getPinColor(lot) {
        if (lot.pin_color) return lot.pin_color;
        // Fallback to discrete colors
        var availability = getAvailability(lot);
        return PIN_COLORS[availability] || PIN_COLORS.stale;
    }

    function buildContextPopupHtml(lot) {
        var pct = lot.probability_score != null
            ? (lot.probability_score * 100).toFixed(1) + '%'
            : '--';
        var conf = lot.confidence_range || '--';
        var avail = lot.availability ? lot.availability.toUpperCase() : '--';
        var signals = '--';
        if (lot.signals_used && lot.signals_used.length > 0) {
            signals = lot.signals_used.map(function (s) {
                return '<span class="ctx-signal-tag">' + escapeHtml(SIGNAL_LABELS[s] || s.toUpperCase()) + '</span>';
            }).join(' ');
        }
        var trendText = lot.trend ? lot.trend.toUpperCase() : 'STABLE';
        var trendClass = 'ctx-trend-stable';
        if (lot.trend === 'filling') trendClass = 'ctx-trend-filling';
        if (lot.trend === 'emptying') trendClass = 'ctx-trend-emptying';

        var predicted = lot.predicted_probability != null
            ? Math.round(lot.predicted_probability * 100) + '%'
            : '--';
        var freshness = '--';
        if (lot.freshness_seconds != null) {
            if (lot.freshness_seconds < 60) freshness = Math.round(lot.freshness_seconds) + 's ago';
            else freshness = Math.floor(lot.freshness_seconds / 60) + 'm ago';
        }

        var occ = lot.current_occupancy != null ? lot.current_occupancy : '?';
        var cap = lot.capacity != null ? lot.capacity : '?';

        var safeName = escapeHtml(lot.name || '--');
        var safeAvailClass = escapeHtml(lot.availability || 'stale');

        return '<div class="ctx-popup">' +
            '<div class="ctx-header">' + safeName + '</div>' +
            '<div class="ctx-row"><span class="ctx-label">PROBABILITY</span><span class="ctx-value">' + escapeHtml(pct) + '</span></div>' +
            '<div class="ctx-row"><span class="ctx-label">CONFIDENCE</span><span class="ctx-value">' + escapeHtml(conf) + '</span></div>' +
            '<div class="ctx-row"><span class="ctx-label">AVAILABILITY</span><span class="ctx-value ctx-avail-' + safeAvailClass + '">' + escapeHtml(avail) + '</span></div>' +
            '<div class="ctx-row"><span class="ctx-label">TREND</span><span class="ctx-value ' + trendClass + '">' + escapeHtml(trendText) + '</span></div>' +
            '<div class="ctx-row"><span class="ctx-label">OCCUPANCY</span><span class="ctx-value">' + escapeHtml(occ + ' / ' + cap) + '</span></div>' +
            '<div class="ctx-row"><span class="ctx-label">PREDICTED</span><span class="ctx-value">' + escapeHtml(predicted) + '</span></div>' +
            '<div class="ctx-row"><span class="ctx-label">UPDATED</span><span class="ctx-value">' + escapeHtml(freshness) + '</span></div>' +
            '<div class="ctx-row ctx-signals-row"><span class="ctx-label">SIGNALS</span><span class="ctx-value">' + signals + '</span></div>' +
            '</div>';
    }

    function updatePins(lots, onPinClick) {
        var currentIds = {};

        lots.forEach(function (lot) {
            currentIds[lot.lot_id] = true;
            lotDataCache[lot.lot_id] = lot;
            var color = getPinColor(lot);

            if (markers[lot.lot_id]) {
                markers[lot.lot_id].setStyle({
                    fillColor: color,
                    color: color
                });
            } else {
                var marker = L.circleMarker([lot.latitude, lot.longitude], {
                    radius: 10,
                    fillColor: color,
                    color: color,
                    weight: 2,
                    opacity: 0.9,
                    fillOpacity: 0.6
                });

                marker.on('click', function () {
                    if (typeof onPinClick === 'function') {
                        onPinClick(lot.lot_id);
                    }
                });

                (function (lotId) {
                    marker.on('contextmenu', function (e) {
                        L.DomEvent.stopPropagation(e);
                        L.DomEvent.preventDefault(e);
                        var data = lotDataCache[lotId];
                        if (!data) return;
                        var popup = L.popup({
                            className: 'ctx-popup-wrapper',
                            closeButton: true,
                            maxWidth: 260,
                            minWidth: 200,
                            autoPan: true
                        })
                            .setLatLng(e.latlng)
                            .setContent(buildContextPopupHtml(data))
                            .openOn(map);
                    });
                })(lot.lot_id);

                marker.bindTooltip(escapeHtml(lot.name), {
                    permanent: false,
                    direction: 'top',
                    className: 'pin-tooltip',
                    offset: [0, -12]
                });

                marker.addTo(pinLayer);
                markers[lot.lot_id] = marker;
            }
        });

        // Remove markers for lots no longer in the data
        Object.keys(markers).forEach(function (id) {
            if (!currentIds[id]) {
                pinLayer.removeLayer(markers[id]);
                delete markers[id];
                delete lotDataCache[id];
            }
        });
    }

    function getMap() {
        return map;
    }

    function setUserLocation(lat, lon, radiusKm) {
        clearUserLocation();
        userMarker = L.circleMarker([lat, lon], {
            radius: 8,
            fillColor: '#3b82f6',
            color: '#ffffff',
            weight: 2,
            opacity: 1,
            fillOpacity: 0.9
        }).addTo(map);

        if (radiusKm) {
            userCircle = L.circle([lat, lon], {
                radius: radiusKm * 1000,
                fillColor: '#3b82f6',
                fillOpacity: 0.08,
                color: '#3b82f6',
                weight: 1,
                opacity: 0.3
            }).addTo(map);
        }

        map.flyTo([lat, lon], 15, { animate: true, duration: 1.0 });
    }

    function clearUserLocation() {
        if (userMarker) {
            map.removeLayer(userMarker);
            userMarker = null;
        }
        if (userCircle) {
            map.removeLayer(userCircle);
            userCircle = null;
        }
    }

    function enableMapClick(callback) {
        mapClickCallback = callback;
        if (map) {
            map.on('click', function (e) {
                if (typeof mapClickCallback === 'function') {
                    mapClickCallback(e.latlng.lat, e.latlng.lng);
                }
            });
        }
    }

    function updateRadius(radiusKm) {
        if (userCircle) {
            userCircle.setRadius(radiusKm * 1000);
        }
    }

    function clearRankMarkers() {
        Object.keys(rankMarkers).forEach(function (id) {
            if (map) map.removeLayer(rankMarkers[id]);
        });
        rankMarkers = {};
    }

    function updateRankings(rankedLots) {
        clearRankMarkers();
        rankedLots.forEach(function (entry) {
            var lot = entry.lot;
            var rank = parseInt(entry.rank, 10) || 0;
            var icon = L.divIcon({
                className: 'rank-badge rank-' + rank,
                html: '<span>#' + rank + '</span>',
                iconSize: [22, 22],
                iconAnchor: [11, -4]
            });
            var rm = L.marker([lot.latitude, lot.longitude], {
                icon: icon,
                interactive: false,
                zIndexOffset: 1000 - rank
            }).addTo(map);
            rankMarkers[lot.lot_id] = rm;
        });
    }

    function setTheme(theme) {
        if (!map || !tileLayer) return;
        var url = TILE_URLS[theme] || TILE_URLS.dark;
        map.removeLayer(tileLayer);
        tileLayer = L.tileLayer(url, {
            attribution: TILE_ATTRIBUTION,
            subdomains: 'abcd',
            maxZoom: 19
        }).addTo(map);
    }

    return {
        initMap: initMap,
        setView: setView,
        clearPins: clearPins,
        updatePins: updatePins,
        getMap: getMap,
        setUserLocation: setUserLocation,
        clearUserLocation: clearUserLocation,
        enableMapClick: enableMapClick,
        updateRadius: updateRadius,
        updateRankings: updateRankings,
        clearRankMarkers: clearRankMarkers,
        setTheme: setTheme
    };
})();
