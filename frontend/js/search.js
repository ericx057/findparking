var LocationSearch = (function () {
    var NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search';
    var DEBOUNCE_MS = 400;
    var MAX_RESULTS = 5;

    var inputEl = null;
    var resultsEl = null;
    var onLocationSelected = null;
    var debounceTimer = null;

    function init(input, results, callback) {
        inputEl = input;
        resultsEl = results;
        onLocationSelected = callback;

        inputEl.addEventListener('input', function () {
            clearTimeout(debounceTimer);
            var query = inputEl.value.trim();
            if (query.length < 3) {
                hideResults();
                return;
            }
            debounceTimer = setTimeout(function () {
                geocodeAddress(query);
            }, DEBOUNCE_MS);
        });

        inputEl.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                hideResults();
                inputEl.blur();
            }
        });

        // Close results when clicking outside
        document.addEventListener('click', function (e) {
            if (resultsEl && !resultsEl.contains(e.target) && e.target !== inputEl) {
                hideResults();
            }
        });
    }

    function geocodeAddress(query) {
        var url = NOMINATIM_URL +
            '?q=' + encodeURIComponent(query) +
            '&format=json' +
            '&countrycodes=ca' +
            '&limit=' + MAX_RESULTS +
            '&addressdetails=1';

        fetch(url, {
            headers: { 'Accept': 'application/json' }
        })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                renderResults(data);
            })
            .catch(function (err) {
                console.error('Geocoding failed:', err);
                hideResults();
            });
    }

    function renderResults(results) {
        if (!resultsEl) return;
        resultsEl.innerHTML = '';

        if (!results || results.length === 0) {
            hideResults();
            return;
        }

        results.forEach(function (item) {
            var div = document.createElement('div');
            div.className = 'search-result-item';
            div.textContent = item.display_name;
            div.addEventListener('click', function () {
                var lat = parseFloat(item.lat);
                var lon = parseFloat(item.lon);
                inputEl.value = item.display_name.split(',')[0];
                hideResults();
                if (typeof onLocationSelected === 'function') {
                    onLocationSelected(lat, lon, item.display_name);
                }
            });
            resultsEl.appendChild(div);
        });

        resultsEl.classList.add('visible');
    }

    function hideResults() {
        if (resultsEl) {
            resultsEl.innerHTML = '';
            resultsEl.classList.remove('visible');
        }
    }

    function getUserLocation(callback) {
        if (!navigator.geolocation) {
            console.error('Geolocation not supported');
            return;
        }
        navigator.geolocation.getCurrentPosition(
            function (pos) {
                callback(pos.coords.latitude, pos.coords.longitude, 'Your Location');
            },
            function (err) {
                console.error('Geolocation error:', err.message);
            },
            { enableHighAccuracy: true, timeout: 10000 }
        );
    }

    function clearInput() {
        if (inputEl) {
            inputEl.value = '';
        }
        hideResults();
    }

    return {
        init: init,
        getUserLocation: getUserLocation,
        clearInput: clearInput
    };
})();
