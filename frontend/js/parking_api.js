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

    function fetchAllLots(city) {
        var url = BASE_URL + '/lots';
        if (city) {
            url += '?city=' + encodeURIComponent(city);
        }
        return fetch(url)
            .then(handleResponse);
    }

    function fetchLotDetail(lotId) {
        return fetch(BASE_URL + '/lots/' + encodeURIComponent(lotId))
            .then(handleResponse);
    }

    function fetchHealth() {
        return fetch(BASE_URL + '/health')
            .then(handleResponse);
    }

    return {
        fetchConfig: fetchConfig,
        fetchAllLots: fetchAllLots,
        fetchLotDetail: fetchLotDetail,
        fetchHealth: fetchHealth
    };
})();
