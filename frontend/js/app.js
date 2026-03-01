(function () {
    var POLL_INTERVAL_MS = 30000;
    var SEARCH_LIMIT = 500;
    var RANK_COUNT = 3;
    var PROB_WEIGHT = 0.65;
    var DIST_WEIGHT = 0.35;
    var overlay = document.getElementById('loading-overlay');
    var statusEl = document.getElementById('connection-status');
    var citySelector = document.getElementById('city-selector');
    var searchInput = document.getElementById('search-input');
    var searchResults = document.getElementById('search-results');
    var geolocateBtn = document.getElementById('geolocate-btn');
    var filterPanel = document.getElementById('filter-panel');
    var filterToggle = document.getElementById('filter-toggle');
    var pollTimer = null;
    var lotsCache = {};
    var activeCity = 'waterloo';
    var cityConfigs = {};
    var userLocation = null; // { lat, lon, label }

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

    function computeRankings(lots) {
        // Only rank lots that have both probability and distance data
        var candidates = lots.filter(function (lot) {
            return lot.probability_score != null
                && lot.distance_km != null
                && lot.availability !== 'stale';
        });
        if (candidates.length === 0) return [];

        // Normalize distance: invert so closer = higher score
        var maxDist = 0;
        candidates.forEach(function (lot) {
            if (lot.distance_km > maxDist) maxDist = lot.distance_km;
        });
        if (maxDist === 0) maxDist = 1;

        var scored = candidates.map(function (lot) {
            var probScore = lot.probability_score;
            var distScore = 1 - (lot.distance_km / maxDist);
            var combined = (PROB_WEIGHT * probScore) + (DIST_WEIGHT * distScore);
            return { lot: lot, score: combined };
        });

        scored.sort(function (a, b) { return b.score - a.score; });

        var top = [];
        for (var i = 0; i < Math.min(RANK_COUNT, scored.length); i++) {
            top.push({ lot: scored[i].lot, rank: i + 1 });
        }
        return top;
    }

    function pollLots() {
        var fetchPromise;
        if (userLocation) {
            var filterState = Filters.getState();
            var radiusKm = filterState.radius_km;
            fetchPromise = ParkingAPI.fetchNearbyLots(
                userLocation.lat, userLocation.lon,
                radiusKm, SEARCH_LIMIT, filterState
            );
        } else {
            fetchPromise = ParkingAPI.fetchAllLots(activeCity);
        }

        fetchPromise
            .then(function (lots) {
                setOnline(true);

                lots.forEach(function (lot) {
                    lotsCache[lot.lot_id] = lot;
                });

                ParkingMap.updatePins(lots, handlePinClick);

                // Compute and display top-3 rankings when location is set
                if (userLocation) {
                    var ranked = computeRankings(lots);
                    ParkingMap.updateRankings(ranked);
                } else {
                    ParkingMap.clearRankMarkers();
                }
            })
            .catch(function (err) {
                console.error('Poll failed:', err);
                setOnline(false);
            });
    }

    function handleLocationSelected(lat, lon, label) {
        userLocation = { lat: lat, lon: lon, label: label };
        lotsCache = {};
        BottomSheet.close();
        ParkingMap.clearPins();
        ParkingMap.setUserLocation(lat, lon, Filters.getRadius());
        pollLots();
    }

    function handleFiltersChanged() {
        if (userLocation) {
            lotsCache = {};
            ParkingMap.clearPins();
            ParkingMap.updateRadius(Filters.getRadius());
            pollLots();
        }
    }

    function clearLocationSearch() {
        userLocation = null;
        lotsCache = {};
        BottomSheet.close();
        ParkingMap.clearPins();
        ParkingMap.clearRankMarkers();
        ParkingMap.clearUserLocation();
        LocationSearch.clearInput();

        var config = cityConfigs[activeCity];
        if (config) {
            ParkingMap.setView(config.center, config.zoom);
        }
        pollLots();
    }

    function switchCity(city) {
        activeCity = city;
        userLocation = null;
        lotsCache = {};
        BottomSheet.close();
        ParkingMap.clearPins();
        ParkingMap.clearRankMarkers();
        ParkingMap.clearUserLocation();
        LocationSearch.clearInput();

        var config = cityConfigs[city];
        if (config) {
            ParkingMap.setView(config.center, config.zoom);
            document.title = 'findparking // ' + city;
        }

        pollLots();
    }

    function init() {
        // Initialize filters
        if (filterPanel && filterToggle) {
            Filters.init(filterPanel, filterToggle, handleFiltersChanged);
        }

        ParkingAPI.fetchConfig()
            .then(function (config) {
                activeCity = config.active_city || 'waterloo';
                cityConfigs = config.cities || {};

                if (citySelector) {
                    citySelector.value = activeCity;
                }

                document.title = 'findparking // ' + activeCity;

                var center = config.center;
                var zoom = config.zoom;
                ParkingMap.initMap(center, zoom);

                // Wire map click for pin-drop location
                ParkingMap.enableMapClick(function (lat, lon) {
                    if (searchInput) {
                        searchInput.value = lat.toFixed(4) + ', ' + lon.toFixed(4);
                    }
                    handleLocationSelected(lat, lon, 'Dropped pin');
                });

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
                ParkingMap.initMap();
                setOnline(false);
                dismissLoader();
            });

        // Search bar
        if (searchInput && searchResults) {
            LocationSearch.init(searchInput, searchResults, handleLocationSelected);
        }

        // Geolocation button
        if (geolocateBtn) {
            geolocateBtn.addEventListener('click', function () {
                LocationSearch.getUserLocation(function (lat, lon, label) {
                    if (searchInput) {
                        searchInput.value = 'My Location';
                    }
                    handleLocationSelected(lat, lon, label);
                });
            });
        }

        // City selector
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
