var ParkingMap = (function () {
    var map = null;
    var pinLayer = null;
    var markers = {};

    var PIN_COLORS = {
        high: '#22c55e',
        medium: '#eab308',
        low: '#ef4444',
        stale: '#6b7280'
    };

    var FALLBACK_CENTER = [43.4643, -80.5204];
    var FALLBACK_ZOOM = 14;

    function initMap(center, zoom) {
        var mapCenter = center || FALLBACK_CENTER;
        var mapZoom = zoom || FALLBACK_ZOOM;

        map = L.map('map', {
            center: mapCenter,
            zoom: mapZoom,
            zoomControl: true
        });

        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
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

    function getPinColor(availability) {
        return PIN_COLORS[availability] || PIN_COLORS.stale;
    }

    function updatePins(lots, onPinClick) {
        var currentIds = {};

        lots.forEach(function (lot) {
            currentIds[lot.lot_id] = true;
            var availability = getAvailability(lot);
            var color = getPinColor(availability);

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

                marker.bindTooltip(lot.name, {
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
            }
        });
    }

    function getMap() {
        return map;
    }

    return {
        initMap: initMap,
        setView: setView,
        clearPins: clearPins,
        updatePins: updatePins,
        getMap: getMap
    };
})();
