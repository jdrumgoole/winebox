/**
 * Wine Price Tracker — mobile-first standalone app.
 *
 * Captures individual bottles or shelves of wine with price, photo,
 * and location data, storing them in the wine price index.
 */

(function () {
    'use strict';

    // ── State ──────────────────────────────────────────────────────────
    let token = localStorage.getItem('pt_token') || '';
    let captureType = 'bottle';
    let selectedPhoto = null;       // File object
    let previewDataUrl = null;      // For display
    let geoCoords = null;           // { latitude, longitude, accuracy_metres }
    let geoWatchId = null;

    // ── DOM refs ───────────────────────────────────────────────────────
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    // Pages
    const loginOverlay = $('#login-overlay');
    const capturePage = $('#page-capture');
    const historyPage = $('#page-history');

    // Login form
    const loginForm = $('#login-form');
    const loginEmail = $('#login-email');
    const loginPassword = $('#login-password');
    const loginError = $('#login-error');
    const loginBtn = $('#login-btn');

    // Capture form
    const photoPreview = $('#photo-preview');
    const photoImg = $('#photo-img');
    const photoInput = $('#photo-input');
    const wineName = $('#wine-name');
    const wineVintage = $('#wine-vintage');
    const wineType = $('#wine-type');
    const priceAmount = $('#price-amount');
    const priceCurrency = $('#price-currency');
    const shopName = $('#shop-name');
    const townCity = $('#town-city');
    const stateCounty = $('#state-county');
    const countryField = $('#country');
    const notesField = $('#notes');
    const coordsDisplay = $('#coords-display');
    const locateBtn = $('#locate-btn');
    const submitBtn = $('#submit-capture');

    // History
    const capturesList = $('#captures-list');
    const emptyState = $('#empty-state');

    // Nav
    const navCapture = $('#nav-capture');
    const navHistory = $('#nav-history');
    const navLogout = $('#nav-logout');

    // ── Helpers ────────────────────────────────────────────────────────

    function showToast(message, type) {
        const existing = document.querySelector('.toast');
        if (existing) existing.remove();

        const toast = document.createElement('div');
        toast.className = 'toast ' + (type || '');
        toast.textContent = message;
        document.body.appendChild(toast);
        requestAnimationFrame(function () {
            toast.classList.add('show');
        });
        setTimeout(function () {
            toast.classList.remove('show');
            setTimeout(function () { toast.remove(); }, 300);
        }, 3000);
    }

    async function api(method, path, body, isFormData) {
        const headers = {};
        if (token) headers['Authorization'] = 'Bearer ' + token;
        if (!isFormData && body) headers['Content-Type'] = 'application/json';

        const opts = { method: method, headers: headers };
        if (body) opts.body = isFormData ? body : JSON.stringify(body);

        const resp = await fetch('/api/prices' + path, opts);
        if (resp.status === 401) {
            logout();
            throw new Error('Session expired');
        }
        return resp;
    }

    function formatDate(isoStr) {
        var d = new Date(isoStr);
        return d.toLocaleDateString(undefined, {
            day: 'numeric', month: 'short', year: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
    }

    function formatPrice(price, currency) {
        if (price == null) return '';
        try {
            return new Intl.NumberFormat(undefined, {
                style: 'currency', currency: currency || 'EUR'
            }).format(price);
        } catch (e) {
            return price.toFixed(2) + ' ' + currency;
        }
    }

    // ── Auth ───────────────────────────────────────────────────────────

    function isLoggedIn() { return !!token; }

    function showLogin() {
        loginOverlay.style.display = 'flex';
    }

    function hideLogin() {
        loginOverlay.style.display = 'none';
    }

    function logout() {
        token = '';
        localStorage.removeItem('pt_token');
        showLogin();
        stopGeo();
    }

    async function doLogin(e) {
        e.preventDefault();
        loginError.textContent = '';
        loginBtn.disabled = true;
        loginBtn.textContent = 'Signing in\u2026';

        try {
            var formData = new URLSearchParams();
            formData.append('username', loginEmail.value.trim());
            formData.append('password', loginPassword.value);

            var resp = await fetch('/api/auth/token', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: formData.toString()
            });

            if (!resp.ok) {
                var err = await resp.json().catch(function () { return {}; });
                throw new Error(err.detail || 'Invalid email or password');
            }

            var data = await resp.json();
            token = data.access_token;
            localStorage.setItem('pt_token', token);
            hideLogin();
            loginPassword.value = '';
            startGeo();
            loadHistory();
        } catch (err) {
            loginError.textContent = err.message;
        } finally {
            loginBtn.disabled = false;
            loginBtn.textContent = 'Sign In';
        }
    }

    // ── Geolocation ───────────────────────────────────────────────────

    function startGeo() {
        if (!navigator.geolocation) return;
        coordsDisplay.textContent = 'Locating\u2026';
        geoWatchId = navigator.geolocation.watchPosition(
            function (pos) {
                geoCoords = {
                    latitude: pos.coords.latitude,
                    longitude: pos.coords.longitude,
                    accuracy_metres: pos.coords.accuracy ? Math.round(pos.coords.accuracy) : null
                };
                coordsDisplay.textContent =
                    pos.coords.latitude.toFixed(4) + ', ' +
                    pos.coords.longitude.toFixed(4) +
                    (pos.coords.accuracy ? ' (\u00b1' + Math.round(pos.coords.accuracy) + ' m accuracy)' : '');
                coordsDisplay.classList.add('found');
            },
            function (err) {
                coordsDisplay.textContent = 'Location unavailable';
                coordsDisplay.classList.remove('found');
            },
            { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 }
        );
    }

    function stopGeo() {
        if (geoWatchId != null) {
            navigator.geolocation.clearWatch(geoWatchId);
            geoWatchId = null;
        }
    }

    // ── Photo ─────────────────────────────────────────────────────────

    function onPhotoSelect(e) {
        var file = e.target.files && e.target.files[0];
        if (!file) return;
        selectedPhoto = file;

        var reader = new FileReader();
        reader.onload = function (ev) {
            previewDataUrl = ev.target.result;
            photoImg.src = previewDataUrl;
            photoPreview.classList.add('has-photo');
        };
        reader.readAsDataURL(file);
    }

    function clearPhoto() {
        selectedPhoto = null;
        previewDataUrl = null;
        photoImg.src = '';
        photoPreview.classList.remove('has-photo');
        photoInput.value = '';
    }

    function triggerCamera() {
        photoInput.click();
    }

    // ── Capture submit ────────────────────────────────────────────────

    async function submitCapture() {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Saving\u2026';

        try {
            var fd = new FormData();
            fd.append('capture_type', captureType);

            if (wineName.value.trim()) fd.append('wine_name', wineName.value.trim());
            if (wineVintage.value) fd.append('vintage', wineVintage.value);
            if (wineType.value) fd.append('wine_type', wineType.value);
            if (priceAmount.value) fd.append('price', priceAmount.value);
            fd.append('currency', priceCurrency.value);
            if (notesField.value.trim()) fd.append('notes', notesField.value.trim());

            // Location
            if (shopName.value.trim()) fd.append('shop_name', shopName.value.trim());
            if (townCity.value.trim()) fd.append('town_city', townCity.value.trim());
            if (stateCounty.value.trim()) fd.append('state_county', stateCounty.value.trim());
            if (countryField.value.trim()) fd.append('country', countryField.value.trim());

            // GPS
            if (geoCoords) {
                fd.append('latitude', geoCoords.latitude);
                fd.append('longitude', geoCoords.longitude);
                if (geoCoords.accuracy_metres != null) {
                    fd.append('accuracy_metres', geoCoords.accuracy_metres);
                }
            }

            fd.append('captured_at', new Date().toISOString());

            // Photo
            if (selectedPhoto) {
                fd.append('photo', selectedPhoto);
            }

            var resp = await api('POST', '', fd, true);
            if (!resp.ok) {
                var err = await resp.json().catch(function () { return {}; });
                throw new Error(err.detail || 'Failed to save');
            }

            showToast('Price captured!', 'success');
            resetForm();
            loadHistory();
        } catch (err) {
            showToast(err.message, 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Save Price';
        }
    }

    function resetForm() {
        wineName.value = '';
        wineVintage.value = '';
        wineType.value = '';
        priceAmount.value = '';
        priceCurrency.value = 'EUR';
        notesField.value = '';
        // Keep location fields — user is likely in the same shop
        clearPhoto();
    }

    // ── History ────────────────────────────────────────────────────────

    async function loadHistory() {
        if (!isLoggedIn()) return;

        try {
            var resp = await api('GET', '?limit=100');
            if (!resp.ok) return;
            var captures = await resp.json();
            renderHistory(captures);
        } catch (e) {
            // Silently fail — history is not critical
        }
    }

    function renderHistory(captures) {
        capturesList.innerHTML = '';

        if (!captures || captures.length === 0) {
            emptyState.style.display = 'block';
            return;
        }

        emptyState.style.display = 'none';

        captures.forEach(function (c) {
            var li = document.createElement('li');
            li.className = 'capture-card';

            var title = c.wine_name || (c.capture_type === 'shelf' ? 'Shelf capture' : 'Bottle capture');
            var meta = [];
            if (c.vintage) meta.push(c.vintage + ' vintage');
            if (c.wine_type) meta.push(c.wine_type);
            if (c.location && c.location.shop_name) meta.push(c.location.shop_name);
            if (c.location && c.location.town_city) meta.push(c.location.town_city);
            meta.push(formatDate(c.captured_at));

            var thumbHtml = '';
            if (c.photo_url) {
                thumbHtml = '<img class="capture-card-thumb" src="' + c.photo_url + '" alt="Wine photo" loading="lazy">';
            } else {
                thumbHtml = '<div class="capture-card-thumb"></div>';
            }

            var priceHtml = '';
            if (c.price != null) {
                priceHtml = '<div class="capture-price">' + formatPrice(c.price, c.currency) + '</div>';
            }

            li.innerHTML =
                '<div class="capture-card-header">' +
                    thumbHtml +
                    '<div class="capture-card-info">' +
                        '<h3>' + escapeHtml(title) + '</h3>' +
                        '<div class="capture-meta">' + escapeHtml(meta.join(' \u00b7 ')) + '</div>' +
                        priceHtml +
                    '</div>' +
                '</div>' +
                '<div class="capture-card-actions">' +
                    '<button class="btn btn-danger btn-small" data-delete="' + c.id + '">Delete</button>' +
                '</div>';

            capturesList.appendChild(li);
        });
    }

    function escapeHtml(str) {
        var div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    async function deleteCapture(id) {
        if (!confirm('Delete this price capture?')) return;
        try {
            var resp = await api('DELETE', '/' + id);
            if (resp.ok || resp.status === 204) {
                showToast('Deleted', 'success');
                loadHistory();
            } else {
                showToast('Failed to delete', 'error');
            }
        } catch (e) {
            showToast('Failed to delete', 'error');
        }
    }

    // ── Navigation ────────────────────────────────────────────────────

    function showPage(name) {
        capturePage.classList.remove('active');
        historyPage.classList.remove('active');
        navCapture.classList.remove('active');
        navHistory.classList.remove('active');

        if (name === 'capture') {
            capturePage.classList.add('active');
            navCapture.classList.add('active');
        } else {
            historyPage.classList.add('active');
            navHistory.classList.add('active');
            loadHistory();
        }
    }

    // ── Capture type toggle ───────────────────────────────────────────

    function setCaptureType(type) {
        captureType = type;
        $$('.capture-type-toggle button').forEach(function (btn) {
            btn.classList.toggle('active', btn.dataset.type === type);
        });
    }

    // ── Init ──────────────────────────────────────────────────────────

    function init() {
        // Login
        loginForm.addEventListener('submit', doLogin);

        // Navigation
        navCapture.addEventListener('click', function () { showPage('capture'); });
        navHistory.addEventListener('click', function () { showPage('history'); });
        navLogout.addEventListener('click', function (e) { e.preventDefault(); logout(); });

        // Capture type
        $$('.capture-type-toggle button').forEach(function (btn) {
            btn.addEventListener('click', function () { setCaptureType(btn.dataset.type); });
        });

        // Photo
        photoPreview.addEventListener('click', triggerCamera);
        photoInput.addEventListener('change', onPhotoSelect);
        $('#btn-clear-photo').addEventListener('click', function (e) {
            e.stopPropagation();
            clearPhoto();
        });

        // Location
        locateBtn.addEventListener('click', function () {
            geoCoords = null;
            coordsDisplay.textContent = 'Locating\u2026';
            coordsDisplay.classList.remove('found');
            stopGeo();
            startGeo();
        });

        // Submit
        submitBtn.addEventListener('click', submitCapture);

        // History delete delegation
        capturesList.addEventListener('click', function (e) {
            var btn = e.target.closest('[data-delete]');
            if (btn) deleteCapture(btn.dataset.delete);
        });

        // Initial state
        if (isLoggedIn()) {
            hideLogin();
            startGeo();
            showPage('capture');
            loadHistory();
        } else {
            showLogin();
            showPage('capture');
        }
    }

    // Wait for DOM
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
