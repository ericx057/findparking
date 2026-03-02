var ParkingAPI = (function () {
    var BASE_URL = '/api';

    function handleResponse(response) {
        if (!response.ok) {
            throw new Error('API request failed: ' + response.status + ' ' + response.statusText);
        }
        return response.json();
    }

    function fetchConfig() {
        return fetch(BASE_URL + '/config')
            .then(handleResponse);
    }

    function fetchAllLots(city, filters) {
        var url = BASE_URL + '/lots';
        if (city) {
            url += '?city=' + encodeURIComponent(city);
        }
        if (filters) {
            var sep = url.indexOf('?') === -1 ? '?' : '&';
            if (filters.min_confidence != null) { url += sep + 'min_confidence=' + filters.min_confidence; sep = '&'; }
            if (filters.min_probability != null) { url += sep + 'min_probability=' + filters.min_probability; sep = '&'; }
        }
        return fetch(url)
            .then(handleResponse);
    }

    function fetchLotDetail(lotId) {
        return fetch(BASE_URL + '/lots/' + encodeURIComponent(lotId))
            .then(handleResponse);
    }

    function fetchNearbyLots(lat, lon, radiusKm, limit, filters) {
        var url = BASE_URL + '/lots/nearby?lat=' + lat + '&lon=' + lon;
        if (radiusKm != null) url += '&radius_km=' + radiusKm;
        if (limit != null) url += '&limit=' + limit;
        if (filters) {
            if (filters.fare_type) url += '&fare_type=' + encodeURIComponent(filters.fare_type);
            if (filters.max_hourly_rate != null) url += '&max_hourly_rate=' + filters.max_hourly_rate;
            if (filters.is_covered != null) url += '&is_covered=' + filters.is_covered;
            if (filters.is_multi_level != null) url += '&is_multi_level=' + filters.is_multi_level;
            if (filters.is_above_ground != null) url += '&is_above_ground=' + filters.is_above_ground;
            if (filters.min_confidence != null) url += '&min_confidence=' + filters.min_confidence;
            if (filters.min_probability != null) url += '&min_probability=' + filters.min_probability;
        }
        return fetch(url)
            .then(handleResponse);
    }

    function fetchHealth() {
        return fetch(BASE_URL + '/health')
            .then(handleResponse);
    }

    return {
        fetchConfig: fetchConfig,
        fetchAllLots: fetchAllLots,
        fetchNearbyLots: fetchNearbyLots,
        fetchLotDetail: fetchLotDetail,
        fetchHealth: fetchHealth
    };
})();
