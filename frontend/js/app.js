(function () {
    var POLL_INTERVAL_MS = 30000;
    var overlay = document.getElementById('loading-overlay');
    var statusEl = document.getElementById('connection-status');
    var citySelector = document.getElementById('city-selector');
    var pollTimer = null;
    var lotsCache = {};
    var activeCity = 'waterloo';
    var cityConfigs = {};

    function setOnline(online) {
        if (online) {
            statusEl.textContent = 'LIVE';
            statusEl.classList.add('online');
        } else {
            statusEl.textContent = 'OFFLINE';
            statusEl.classList.remove('online');
        }
    }

    function dismissLoader() {
        if (overlay) {
            overlay.classList.add('fade-out');
            setTimeout(function () {
                overlay.style.display = 'none';
            }, 600);
        }
    }

    function handlePinClick(lotId) {
        var lot = lotsCache[lotId];
        if (lot) {
            BottomSheet.open(lot);
        } else {
            ParkingAPI.fetchLotDetail(lotId)
                .then(function (detail) {
                    lotsCache[lotId] = detail;
                    BottomSheet.open(detail);
                })
                .catch(function (err) {
                    console.error('Failed to fetch lot detail:', err);
                });
        }
    }

    function pollLots() {
        ParkingAPI.fetchAllLots(activeCity)
            .then(function (lots) {
                setOnline(true);

                lots.forEach(function (lot) {
                    lotsCache[lot.lot_id] = lot;
                });

                ParkingMap.updatePins(lots, handlePinClick);
            })
            .catch(function (err) {
                console.error('Poll failed:', err);
                setOnline(false);
            });
    }

    function switchCity(city) {
        activeCity = city;
        lotsCache = {};
        BottomSheet.close();
        ParkingMap.clearPins();

        var config = cityConfigs[city];
        if (config) {
            ParkingMap.setView(config.center, config.zoom);
            document.title = 'findparking // ' + city;
        }

        pollLots();
    }

    function init() {
        // Fetch config first, then init map with correct center
        ParkingAPI.fetchConfig()
            .then(function (config) {
                activeCity = config.active_city || 'waterloo';
                cityConfigs = config.cities || {};

                // Set dropdown to active city
                if (citySelector) {
                    citySelector.value = activeCity;
                }

                document.title = 'findparking // ' + activeCity;

                var center = config.center;
                var zoom = config.zoom;
                ParkingMap.initMap(center, zoom);

                return ParkingAPI.fetchAllLots(activeCity);
            })
            .then(function (lots) {
                setOnline(true);
                lots.forEach(function (lot) {
                    lotsCache[lot.lot_id] = lot;
                });
                ParkingMap.updatePins(lots, handlePinClick);
                dismissLoader();
            })
            .catch(function () {
                // Config fetch failed -- init map with fallback
                ParkingMap.initMap();
                setOnline(false);
                dismissLoader();
            });

        // City selector change handler
        if (citySelector) {
            citySelector.addEventListener('change', function () {
                switchCity(citySelector.value);
            });
        }

        pollTimer = setInterval(pollLots, POLL_INTERVAL_MS);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
