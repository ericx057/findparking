var BottomSheet = (function () {
    var sheet = document.getElementById('bottom-sheet');
    var lotName = document.getElementById('sheet-lot-name');
    var score = document.getElementById('sheet-score');
    var badge = document.getElementById('sheet-badge');
    var trend = document.getElementById('sheet-trend');
    var capacity = document.getElementById('sheet-capacity');
    var walking = document.getElementById('sheet-walking');
    var confidence = document.getElementById('sheet-confidence');
    var updated = document.getElementById('sheet-updated');
    var closeBtn = document.getElementById('sheet-close');
    var fareEl = document.getElementById('sheet-fare');
    var lotTypeEl = document.getElementById('sheet-lot-type');
    var predictedEl = document.getElementById('sheet-predicted');
    var signalsEl = document.getElementById('sheet-signals');

    var userPosition = null;

    // Attempt to get user position for walking ETA
    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
            function (pos) {
                userPosition = { lat: pos.coords.latitude, lng: pos.coords.longitude };
            },
            function () {
                userPosition = null;
            }
        );
    }

    if (closeBtn) {
        closeBtn.addEventListener('click', close);
    }

    function haversineKm(lat1, lon1, lat2, lon2) {
        var R = 6371;
        var dLat = (lat2 - lat1) * Math.PI / 180;
        var dLon = (lon2 - lon1) * Math.PI / 180;
        var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
                Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
                Math.sin(dLon / 2) * Math.sin(dLon / 2);
        var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        return R * c;
    }

    function computeWalkingEta(lot) {
        // Prefer server-computed walking_minutes
        if (lot.walking_minutes != null) {
            if (lot.walking_minutes < 1) return '< 1 min walk';
            return '~' + lot.walking_minutes + ' min walk';
        }
        var km = null;
        if (lot.distance_km != null) {
            km = lot.distance_km;
        } else if (userPosition) {
            km = haversineKm(userPosition.lat, userPosition.lng, lot.latitude, lot.longitude);
        }
        if (km == null) return 'Location unavailable';
        var minutes = Math.round((km / 5) * 60);
        if (minutes < 1) return '< 1 min walk';
        return '~' + minutes + ' min walk';
    }

    function computeTrend(lot) {
        if (!lot.trend) return { text: '-- STABLE', className: 'trend-stable' };
        if (lot.trend === 'filling') return { text: 'v FILLING', className: 'trend-filling' };
        if (lot.trend === 'emptying') return { text: '^ EMPTYING', className: 'trend-emptying' };
        return { text: '-- STABLE', className: 'trend-stable' };
    }

    function formatUpdated(freshnessSeconds) {
        if (freshnessSeconds == null) return '--';
        if (freshnessSeconds < 60) return freshnessSeconds + 's ago';
        var mins = Math.floor(freshnessSeconds / 60);
        return mins + 'm ago';
    }

    function formatFareType(lot) {
        if (!lot.fare_type) return '--';
        var label = lot.fare_type.toUpperCase();
        if (lot.fare_type === 'hourly' && lot.hourly_rate != null) {
            label += ' ($' + lot.hourly_rate.toFixed(2) + '/hr)';
        }
        return label;
    }

    function formatLotType(lot) {
        var parts = [];
        if (lot.is_covered) parts.push('Covered');
        if (lot.is_multi_level) parts.push('Multi-level');
        if (lot.is_above_ground === false) {
            parts.push('Underground');
        } else if (lot.is_above_ground === true) {
            parts.push('Surface');
        }
        return parts.length > 0 ? parts.join(', ') : '--';
    }

    function formatSignals(lot) {
        if (!lot.signals_used || lot.signals_used.length === 0) return '--';
        var labels = {
            'camera': 'CAM',
            'heuristic_baseline': 'EST',
            'sports_event': 'EVENT',
            'weather': 'WX',
            'time_weights': 'TIME',
            'road_disruptions': 'ROAD',
        };
        return lot.signals_used.map(function (s) {
            return labels[s] || s.toUpperCase();
        }).join(' + ');
    }

    function open(lot) {
        lotName.textContent = lot.name || '--';

        var pct = lot.probability_score != null ? Math.round(lot.probability_score * 100) : '--';
        score.textContent = pct;

        var avail = lot.availability || 'stale';
        badge.textContent = avail.toUpperCase();
        badge.className = 'sheet-availability-badge ' + avail;

        var trendInfo = computeTrend(lot);
        trend.textContent = trendInfo.text;
        trend.className = 'detail-value ' + trendInfo.className;

        var occ = lot.current_occupancy != null ? lot.current_occupancy : '?';
        var cap = lot.capacity != null ? lot.capacity : '?';
        capacity.textContent = occ + ' / ' + cap;

        walking.textContent = computeWalkingEta(lot);

        var conf = lot.confidence_range || null;
        confidence.textContent = conf ? conf : '--';

        updated.textContent = formatUpdated(lot.freshness_seconds);

        // Lot attributes
        if (fareEl) fareEl.textContent = formatFareType(lot);
        if (lotTypeEl) lotTypeEl.textContent = formatLotType(lot);
        if (predictedEl) {
            if (lot.predicted_probability != null) {
                predictedEl.textContent = Math.round(lot.predicted_probability * 100) + '%';
            } else {
                predictedEl.textContent = 'No data';
            }
        }
        if (signalsEl) signalsEl.textContent = formatSignals(lot);

        sheet.classList.remove('hidden');
    }

    function close() {
        sheet.classList.add('hidden');
    }

    function isOpen() {
        return !sheet.classList.contains('hidden');
    }

    return {
        open: open,
        close: close,
        isOpen: isOpen
    };
})();
