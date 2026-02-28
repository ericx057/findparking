var Filters = (function () {
    var panel = null;
    var toggleBtn = null;
    var onChanged = null;

    // Default state
    var state = {
        radius_km: 2.0,
        fare_type: null,
        max_hourly_rate: null,
        is_covered: null,
        is_multi_level: null,
        is_above_ground: null
    };

    function init(panelEl, toggleBtnEl, callback) {
        panel = panelEl;
        toggleBtn = toggleBtnEl;
        onChanged = callback;

        if (toggleBtn) {
            toggleBtn.addEventListener('click', function () {
                panel.classList.toggle('open');
                toggleBtn.classList.toggle('active');
            });
        }

        // Radius slider
        var radiusSlider = document.getElementById('filter-radius');
        var radiusLabel = document.getElementById('filter-radius-label');
        if (radiusSlider) {
            radiusSlider.addEventListener('input', function () {
                var km = parseFloat(radiusSlider.value);
                state.radius_km = km;
                var walkMin = Math.round((km / 5.0) * 60);
                radiusLabel.textContent = km.toFixed(1) + ' km / ~' + walkMin + ' min walk';
                fireChanged();
            });
        }

        // Fare type select
        var fareSelect = document.getElementById('filter-fare-type');
        if (fareSelect) {
            fareSelect.addEventListener('change', function () {
                state.fare_type = fareSelect.value || null;
                fireChanged();
            });
        }

        // Max hourly rate
        var rateInput = document.getElementById('filter-max-rate');
        if (rateInput) {
            rateInput.addEventListener('change', function () {
                var val = rateInput.value;
                state.max_hourly_rate = val ? parseFloat(val) : null;
                fireChanged();
            });
        }

        // Boolean toggles
        bindToggle('filter-covered', 'is_covered');
        bindToggle('filter-multi-level', 'is_multi_level');
        bindToggle('filter-above-ground', 'is_above_ground');

        // Reset button
        var resetBtn = document.getElementById('filter-reset');
        if (resetBtn) {
            resetBtn.addEventListener('click', reset);
        }
    }

    function bindToggle(elementId, stateKey) {
        var el = document.getElementById(elementId);
        if (!el) return;
        el.addEventListener('change', function () {
            if (el.checked) {
                state[stateKey] = true;
            } else {
                state[stateKey] = null;
            }
            fireChanged();
        });
    }

    function fireChanged() {
        if (typeof onChanged === 'function') {
            onChanged(getState());
        }
    }

    function getState() {
        return {
            radius_km: state.radius_km,
            fare_type: state.fare_type,
            max_hourly_rate: state.max_hourly_rate,
            is_covered: state.is_covered,
            is_multi_level: state.is_multi_level,
            is_above_ground: state.is_above_ground
        };
    }

    function getRadius() {
        return state.radius_km;
    }

    function reset() {
        state = {
            radius_km: 2.0,
            fare_type: null,
            max_hourly_rate: null,
            is_covered: null,
            is_multi_level: null,
            is_above_ground: null
        };

        // Reset UI elements
        var radiusSlider = document.getElementById('filter-radius');
        var radiusLabel = document.getElementById('filter-radius-label');
        if (radiusSlider) {
            radiusSlider.value = '2.0';
            radiusLabel.textContent = '2.0 km / ~24 min walk';
        }

        var fareSelect = document.getElementById('filter-fare-type');
        if (fareSelect) fareSelect.value = '';

        var rateInput = document.getElementById('filter-max-rate');
        if (rateInput) rateInput.value = '';

        var toggleIds = ['filter-covered', 'filter-multi-level', 'filter-above-ground'];
        toggleIds.forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.checked = false;
        });

        fireChanged();
    }

    return {
        init: init,
        getState: getState,
        getRadius: getRadius,
        reset: reset
    };
})();
