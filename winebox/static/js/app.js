/**
 * WineBox - Wine Cellar Management Application
 * Frontend JavaScript
 */

const API_BASE = '/api';

// Analytics wrapper
const analytics = {
    isEnabled: function() {
        return window.posthog && window.POSTHOG_CONFIG && window.POSTHOG_CONFIG.enabled;
    },
    capture: function(event, props) {
        if (this.isEnabled()) {
            try {
                posthog.capture(event, props);
            } catch (e) {
                console.debug('Analytics capture error:', e);
            }
        }
    },
    identify: function(userId, props) {
        if (this.isEnabled()) {
            try {
                posthog.identify(userId, props);
            } catch (e) {
                console.debug('Analytics identify error:', e);
            }
        }
    },
    reset: function() {
        if (this.isEnabled()) {
            try {
                posthog.reset();
            } catch (e) {
                console.debug('Analytics reset error:', e);
            }
        }
    }
};

// Token storage: use localStorage if "stay logged in" was checked, else sessionStorage
function getTokenStorage() {
    return localStorage.getItem('winebox_remember') === 'true' ? localStorage : sessionStorage;
}

// State
let currentPage = 'dashboard';
let isHandlingPopState = false;
let authToken = localStorage.getItem('winebox_token') || sessionStorage.getItem('winebox_token');
let currentUser = null;
let lastScanResult = null;  // Store last scan result to avoid rescanning on checkin
let cellarViewMode = 'cards';
let cellarLastWines = [];
let cellarGroupedData = null;
let currentCellarTab = 'dashboard';
let metViewMode = 'cards';
let metLastWines = [];
let selectedMetWineId = null;

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initForms();
    initModals();
    initAuth();
    initAutocomplete();
    initExportDropdowns();
    initXWinesPage();
    initImportPage();
    initCustomFields();
    initMetPage();
    initAddToCellarPage();
    checkAuth();
    loadAppInfo();
});

// Load app info for footer
async function loadAppInfo() {
    try {
        const response = await fetch('/health');
        const data = await response.json();
        const appInfo = document.getElementById('app-info');
        if (appInfo && data.app_name && data.version) {
            appInfo.innerHTML = `${data.app_name} <span class="version">v${data.version}</span>`;
        }
    } catch (error) {
        console.log('Could not load app info');
    }
}

// X-Wines Autocomplete
let autocompleteSelectedIndex = -1;
let autocompleteResults = [];

function initAutocomplete() {
    const wineNameInput = document.getElementById('wine-name');
    const autocompleteDropdown = document.getElementById('wine-autocomplete');

    if (!wineNameInput || !autocompleteDropdown) return;

    // Input event for search
    wineNameInput.addEventListener('input', debounce(async (e) => {
        const query = e.target.value.trim();
        if (query.length < 2) {
            hideAutocomplete();
            return;
        }
        await searchXWines(query);
    }, 300));

    // Keyboard navigation
    wineNameInput.addEventListener('keydown', (e) => {
        if (!autocompleteDropdown.classList.contains('active')) return;

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                navigateAutocomplete(1);
                break;
            case 'ArrowUp':
                e.preventDefault();
                navigateAutocomplete(-1);
                break;
            case 'Enter':
                e.preventDefault();
                if (autocompleteSelectedIndex >= 0) {
                    selectAutocompleteItem(autocompleteResults[autocompleteSelectedIndex]);
                }
                break;
            case 'Escape':
                hideAutocomplete();
                break;
        }
    });

    // Close on click outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.autocomplete-wrapper')) {
            hideAutocomplete();
        }
    });

    // Focus shows dropdown if there are results
    wineNameInput.addEventListener('focus', () => {
        if (autocompleteResults.length > 0 && wineNameInput.value.length >= 2) {
            showAutocomplete();
        }
    });
}

async function searchXWines(query) {
    const autocompleteDropdown = document.getElementById('wine-autocomplete');

    // Show loading state
    autocompleteDropdown.innerHTML = '<div class="autocomplete-loading">Searching...</div>';
    autocompleteDropdown.classList.add('active');

    try {
        const response = await fetchWithAuth(`${API_BASE}/xwines/search?q=${encodeURIComponent(query)}&limit=10`);

        if (!response.ok) {
            throw new Error('Search failed');
        }

        const data = await response.json();
        autocompleteResults = data.results;
        autocompleteSelectedIndex = -1;

        if (autocompleteResults.length === 0) {
            autocompleteDropdown.innerHTML = '<div class="autocomplete-no-results">No wines found</div>';
        } else {
            renderAutocompleteResults();
        }
    } catch (error) {
        console.error('X-Wines search error:', error);
        autocompleteDropdown.innerHTML = '<div class="autocomplete-no-results">Search unavailable</div>';
    }
}

function renderAutocompleteResults() {
    const autocompleteDropdown = document.getElementById('wine-autocomplete');

    autocompleteDropdown.innerHTML = autocompleteResults.map((wine, index) => {
        const ratingStars = wine.avg_rating ? '★'.repeat(Math.round(wine.avg_rating)) : '';
        return `
            <div class="autocomplete-item ${index === autocompleteSelectedIndex ? 'selected' : ''}"
                 data-index="${index}">
                <div class="autocomplete-item-name">${escapeHtml(wine.name)}</div>
                <div class="autocomplete-item-details">
                    ${wine.winery ? `<span class="autocomplete-item-detail">${escapeHtml(wine.winery)}</span>` : ''}
                    ${wine.wine_type ? `<span class="autocomplete-item-detail">${escapeHtml(wine.wine_type)}</span>` : ''}
                    ${wine.country ? `<span class="autocomplete-item-detail">${escapeHtml(wine.country)}</span>` : ''}
                    ${wine.avg_rating ? `<span class="autocomplete-item-detail autocomplete-item-rating">${ratingStars} (${wine.rating_count})</span>` : ''}
                </div>
            </div>
        `;
    }).join('');

    // Add click handlers
    autocompleteDropdown.querySelectorAll('.autocomplete-item').forEach(item => {
        item.addEventListener('click', () => {
            const index = parseInt(item.dataset.index);
            selectAutocompleteItem(autocompleteResults[index]);
        });
    });
}

function navigateAutocomplete(direction) {
    const newIndex = autocompleteSelectedIndex + direction;
    if (newIndex >= -1 && newIndex < autocompleteResults.length) {
        autocompleteSelectedIndex = newIndex;
        renderAutocompleteResults();

        // Scroll selected item into view
        const dropdown = document.getElementById('wine-autocomplete');
        const selectedItem = dropdown.querySelector('.autocomplete-item.selected');
        if (selectedItem) {
            selectedItem.scrollIntoView({ block: 'nearest' });
        }
    }
}

function selectAutocompleteItem(wine) {
    // Fill in the form fields with the selected wine data
    document.getElementById('wine-name').value = wine.name || '';
    document.getElementById('winery').value = wine.winery || '';
    document.getElementById('country').value = wine.country || '';

    // Fill region from search result
    const regionInput = document.getElementById('region');
    if (wine.region && regionInput && !regionInput.value) {
        regionInput.value = wine.region;
    }

    // Fill alcohol percentage if available
    const alcoholInput = document.getElementById('alcohol');
    if (wine.abv && alcoholInput) {
        alcoholInput.value = wine.abv;
    }

    // Fetch full X-Wines detail to fill remaining fields
    if (wine.id) {
        fetchXWinesDetailForForm(wine.id);
    }

    // Add visual indicator that fields were auto-filled
    const autoFilledFields = ['wine-name', 'winery', 'country', 'region', 'alcohol'];
    autoFilledFields.forEach(fieldId => {
        const input = document.getElementById(fieldId);
        if (input && input.value) {
            input.classList.add('auto-filled');
            setTimeout(() => input.classList.remove('auto-filled'), 2000);
        }
    });

    hideAutocomplete();
    showToast(`Selected: ${wine.name}`, 'success');
}

async function fetchXWinesDetailForForm(xwinesId) {
    try {
        const response = await fetchWithAuth(`${API_BASE}/xwines/wines/${xwinesId}`);
        if (!response.ok) return;
        const detail = await response.json();

        // Fill empty fields from X-Wines detail
        const grapeInput = document.getElementById('grape-variety');
        if (grapeInput && !grapeInput.value && detail.grapes) {
            grapeInput.value = parsePythonList(detail.grapes);
            grapeInput.classList.add('auto-filled');
            setTimeout(() => grapeInput.classList.remove('auto-filled'), 2000);
        }

        const regionInput = document.getElementById('region');
        if (regionInput && !regionInput.value && detail.region_name) {
            regionInput.value = detail.region_name;
            regionInput.classList.add('auto-filled');
            setTimeout(() => regionInput.classList.remove('auto-filled'), 2000);
        }

        const wineTypeSelect = document.getElementById('wine-type');
        if (wineTypeSelect && !wineTypeSelect.value && detail.wine_type) {
            const typeValue = detail.wine_type.toLowerCase();
            // Check if option exists in the select
            const option = Array.from(wineTypeSelect.options).find(
                opt => opt.value === typeValue
            );
            if (option) {
                wineTypeSelect.value = typeValue;
                wineTypeSelect.classList.add('auto-filled');
                setTimeout(() => wineTypeSelect.classList.remove('auto-filled'), 2000);
            }
        }
    } catch (error) {
        console.debug('X-Wines detail fetch for form failed:', error);
    }
}

function showAutocomplete() {
    document.getElementById('wine-autocomplete').classList.add('active');
}

function hideAutocomplete() {
    document.getElementById('wine-autocomplete').classList.remove('active');
    autocompleteSelectedIndex = -1;
}

// Authentication
function initAuth() {
    // Login form
    document.getElementById('login-form').addEventListener('submit', handleLogin);

    // Logout button
    document.getElementById('logout-btn').addEventListener('click', handleLogout);

    // Username link to settings
    document.getElementById('username-display').addEventListener('click', (e) => {
        e.preventDefault();
        navigateTo('settings');
    });

    // Password toggle for all password fields
    initPasswordToggles();

    // Registration form
    const registerForm = document.getElementById('register-form');
    if (registerForm) {
        registerForm.addEventListener('submit', handleRegister);
    }

    // Forgot password form
    const forgotForm = document.getElementById('forgot-password-form');
    if (forgotForm) {
        forgotForm.addEventListener('submit', handleForgotPassword);
    }

    // Reset password form
    const resetForm = document.getElementById('reset-password-form');
    if (resetForm) {
        resetForm.addEventListener('submit', handleResetPassword);
    }

    // Card navigation links
    document.getElementById('show-register')?.addEventListener('click', (e) => {
        e.preventDefault();
        showAuthCard('register-card');
    });

    document.getElementById('show-forgot-password')?.addEventListener('click', (e) => {
        e.preventDefault();
        showAuthCard('forgot-password-card');
    });

    document.getElementById('show-login-from-register')?.addEventListener('click', (e) => {
        e.preventDefault();
        showAuthCard('login-card');
    });

    document.getElementById('show-login-from-forgot')?.addEventListener('click', (e) => {
        e.preventDefault();
        showAuthCard('login-card');
    });

    document.getElementById('show-login-from-verify')?.addEventListener('click', (e) => {
        e.preventDefault();
        showAuthCard('login-card');
    });

    // Check for hash parameters (email verification or password reset)
    handleHashParams();
}

function initPasswordToggles() {
    document.querySelectorAll('.password-toggle').forEach(toggle => {
        toggle.addEventListener('click', function() {
            const wrapper = this.closest('.password-input-wrapper');
            const passwordInput = wrapper.querySelector('input[type="password"], input[type="text"]');
            const eyeIcon = this.querySelector('.eye-icon');
            const eyeOffIcon = this.querySelector('.eye-off-icon');

            if (passwordInput.type === 'password') {
                passwordInput.type = 'text';
                eyeIcon.style.display = 'none';
                eyeOffIcon.style.display = 'block';
                this.setAttribute('aria-label', 'Hide password');
            } else {
                passwordInput.type = 'password';
                eyeIcon.style.display = 'block';
                eyeOffIcon.style.display = 'none';
                this.setAttribute('aria-label', 'Show password');
            }
        });
    });
}

async function checkAuth() {
    if (!authToken) {
        showLoginPage();
        return;
    }

    try {
        const response = await fetchWithAuth(`${API_BASE}/auth/me`);
        if (!response.ok) {
            throw new Error('Not authenticated');
        }
        currentUser = await response.json();
        await showMainApp();
    } catch (error) {
        localStorage.removeItem('winebox_token');
        sessionStorage.removeItem('winebox_token');
        authToken = null;
        showLoginPage();
    }
}

function showLoginPage() {
    closeModals();
    document.body.classList.add('logged-out');
    document.getElementById('page-login').classList.add('active');
    document.getElementById('user-info').style.display = 'none';
}

const APP_PAGES = ['dashboard', 'import', 'checkin', 'cellar', 'met', 'add-to-cellar', 'history', 'search', 'xwines', 'settings'];
// 'dashboard' kept in APP_PAGES for backward compat with old bookmarks — redirects to cellar

async function showMainApp() {
    document.body.classList.remove('logged-out');
    document.getElementById('page-login').classList.remove('active');
    document.getElementById('user-info').style.display = 'flex';
    document.getElementById('username-display').textContent = currentUser.email;

    // Identify user for analytics
    analytics.identify(currentUser.id, { email: currentUser.email });

    // Check if URL hash specifies a valid app page
    const hashPage = window.location.hash.slice(1).split('?')[0];
    if (hashPage && APP_PAGES.includes(hashPage)) {
        isHandlingPopState = true;
        navigateTo(hashPage);
        isHandlingPopState = false;
        // Set initial history entry with replaceState to avoid phantom extra entry
        history.replaceState(null, '', `#${hashPage}`);
        return;
    }

    // Always start on My Cellar

    // Only navigate to cellar if user hasn't navigated elsewhere
    const finalHash = window.location.hash.slice(1).split('?')[0];
    if (!finalHash || !APP_PAGES.includes(finalHash)) {
        isHandlingPopState = true;
        navigateTo('cellar');
        isHandlingPopState = false;
        history.replaceState(null, '', '#cellar');
    }
}

async function handleLogin(e) {
    e.preventDefault();
    const form = e.target;
    const email = document.getElementById('login-email').value.trim();
    const password = document.getElementById('login-password').value;
    const errorDiv = document.getElementById('login-error');

    errorDiv.style.display = 'none';

    try {
        const formData = new URLSearchParams();
        formData.append('username', email);  // OAuth2 spec uses 'username' field
        formData.append('password', password);

        const response = await fetch(`${API_BASE}/auth/token`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            const errorMessage = error.detail || 'Login failed';

            // Check if account needs verification
            if (errorMessage.toLowerCase().includes('not verified') ||
                errorMessage.toLowerCase().includes('email not verified')) {
                throw new Error('Email not verified. Please check your email for the verification link.');
            }

            throw new Error(errorMessage);
        }

        const data = await response.json();
        authToken = data.access_token;

        // Store token in localStorage (persistent) or sessionStorage (browser session only)
        const rememberMe = document.getElementById('login-remember-me').checked;
        localStorage.setItem('winebox_remember', rememberMe ? 'true' : 'false');
        getTokenStorage().setItem('winebox_token', authToken);

        // Track successful login
        analytics.capture('frontend_login_success');

        form.reset();
        await checkAuth();
    } catch (error) {
        errorDiv.textContent = error.message;
        errorDiv.style.display = 'block';
    }
}

function handleLogout() {
    // Track logout before clearing state
    analytics.capture('frontend_logout');
    analytics.reset();

    localStorage.removeItem('winebox_token');
    sessionStorage.removeItem('winebox_token');
    localStorage.removeItem('winebox_remember');
    authToken = null;
    currentUser = null;
    showLoginPage();
}

// Show different auth cards (login, register, forgot password, etc.)
function showAuthCard(cardId) {
    const cards = ['login-card', 'register-card', 'forgot-password-card', 'reset-password-card', 'verify-card'];
    cards.forEach(id => {
        const card = document.getElementById(id);
        if (card) {
            card.style.display = id === cardId ? 'block' : 'none';
        }
    });

    // Clear any error/success messages when switching cards
    document.querySelectorAll('.login-error, .login-success').forEach(el => {
        el.style.display = 'none';
    });
}

// Handle hash parameters for email verification, password reset, and login/register navigation
function handleHashParams() {
    const hash = window.location.hash;
    if (!hash) return;

    const params = new URLSearchParams(hash.slice(1).split('?')[1] || '');
    const action = hash.slice(1).split('?')[0];

    if (action === 'verify' && params.get('token')) {
        handleEmailVerification(params.get('token'));
    } else if (action === 'reset-password' && params.get('token')) {
        document.getElementById('reset-token').value = params.get('token');
        showAuthCard('reset-password-card');
    } else if (action === 'login') {
        // Show login card when coming from landing page
        showAuthCard('login-card');
    } else if (action === 'register') {
        // Show register card when coming from landing page
        showAuthCard('register-card');
    }
}

// Handle hash navigation on page load and hash changes
function handleHashNavigation() {
    const rawHash = window.location.hash.slice(1).split('?')[0];

    // Support cellar sub-tab hashes: #cellar/search, #cellar/import, #cellar/history
    const cellarSubTabs = ['dashboard', 'search', 'import', 'history'];
    if (rawHash.startsWith('cellar/') && authToken && currentUser) {
        const subTab = rawHash.split('/')[1];
        if (cellarSubTabs.includes(subTab)) {
            isHandlingPopState = true;
            currentCellarTab = subTab;
            navigateTo('cellar');
            isHandlingPopState = false;
            return;
        }
    }

    // Backward compat: #search and #history redirect to cellar sub-tabs
    if ((rawHash === 'search' || rawHash === 'history') && authToken && currentUser) {
        isHandlingPopState = true;
        currentCellarTab = rawHash;
        navigateTo('cellar');
        isHandlingPopState = false;
        return;
    }

    const hashPage = rawHash;
    // If it's a valid app page and user is logged in, navigate to it
    if (hashPage && APP_PAGES.includes(hashPage) && authToken && currentUser) {
        isHandlingPopState = true;
        navigateTo(hashPage);
        isHandlingPopState = false;
        return;
    }

    // Otherwise handle auth-related hash params (verify, reset-password, login, register)
    handleHashParams();
}

// Listen for hash changes (when user clicks back/forward)
window.addEventListener('hashchange', handleHashNavigation);

// Handle user registration
async function handleRegister(e) {
    e.preventDefault();

    const email = document.getElementById('register-email').value.trim();
    const password = document.getElementById('register-password').value;
    const confirmPassword = document.getElementById('register-confirm-password').value;
    const errorDiv = document.getElementById('register-error');

    errorDiv.style.display = 'none';

    // Validate passwords match
    if (password !== confirmPassword) {
        errorDiv.textContent = 'Passwords do not match';
        errorDiv.style.display = 'block';
        return;
    }

    // Validate password length
    if (password.length < 8) {
        errorDiv.textContent = 'Password must be at least 8 characters';
        errorDiv.style.display = 'block';
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/auth/register`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                email: email,
                password: password,
            })
        });

        if (!response.ok) {
            const error = await response.json();
            // Map API error codes to user-friendly messages
            let message = error.detail || 'Registration failed';
            if (message === 'REGISTER_USER_ALREADY_EXISTS') {
                message = 'A user with this email already exists';
            } else if (message === 'REGISTER_INVALID_PASSWORD') {
                message = 'Password does not meet requirements';
            }
            throw new Error(message);
        }

        // Registration successful
        showToast('Account created! Please check your email to verify your account.', 'success');
        showAuthCard('login-card');
        document.getElementById('register-form').reset();

    } catch (error) {
        errorDiv.textContent = error.message;
        errorDiv.style.display = 'block';
    }
}

// Handle forgot password request
async function handleForgotPassword(e) {
    e.preventDefault();

    const email = document.getElementById('forgot-email').value.trim();
    const errorDiv = document.getElementById('forgot-error');
    const successDiv = document.getElementById('forgot-success');

    errorDiv.style.display = 'none';
    successDiv.style.display = 'none';

    try {
        const response = await fetch(`${API_BASE}/auth/forgot-password`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ email: email })
        });

        // Note: fastapi-users returns 202 for security (doesn't reveal if email exists)
        if (response.ok || response.status === 202) {
            successDiv.textContent = 'If an account exists with this email, a password reset link has been sent.';
            successDiv.style.display = 'block';
            document.getElementById('forgot-password-form').reset();
        } else {
            const error = await response.json();
            throw new Error(error.detail || 'Request failed');
        }

    } catch (error) {
        errorDiv.textContent = error.message;
        errorDiv.style.display = 'block';
    }
}

// Handle password reset
async function handleResetPassword(e) {
    e.preventDefault();

    const token = document.getElementById('reset-token').value;
    const password = document.getElementById('reset-password').value;
    const confirmPassword = document.getElementById('reset-confirm-password').value;
    const errorDiv = document.getElementById('reset-error');

    errorDiv.style.display = 'none';

    // Validate passwords match
    if (password !== confirmPassword) {
        errorDiv.textContent = 'Passwords do not match';
        errorDiv.style.display = 'block';
        return;
    }

    // Validate password length
    if (password.length < 8) {
        errorDiv.textContent = 'Password must be at least 8 characters';
        errorDiv.style.display = 'block';
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/auth/reset-password`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                token: token,
                password: password,
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Password reset failed');
        }

        // Clear the hash
        window.location.hash = '';

        showToast('Password reset successful! You can now sign in with your new password.', 'success');
        showAuthCard('login-card');
        document.getElementById('reset-password-form').reset();

    } catch (error) {
        errorDiv.textContent = error.message;
        errorDiv.style.display = 'block';
    }
}

// Handle email verification
async function handleEmailVerification(token) {
    showAuthCard('verify-card');

    const titleEl = document.getElementById('verify-title');
    const messageEl = document.getElementById('verify-message');
    const spinnerEl = document.getElementById('verify-spinner');
    const successEl = document.getElementById('verify-success');
    const errorEl = document.getElementById('verify-error');
    const loginLink = document.getElementById('verify-login-link');

    try {
        const response = await fetch(`${API_BASE}/auth/verify`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ token: token })
        });

        spinnerEl.style.display = 'none';

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Verification failed');
        }

        titleEl.textContent = 'Email Verified!';
        messageEl.textContent = 'Your email has been verified successfully.';
        successEl.textContent = 'You can now sign in to your account.';
        successEl.style.display = 'block';
        loginLink.style.display = 'block';

        // Clear the hash
        window.location.hash = '';

    } catch (error) {
        titleEl.textContent = 'Verification Failed';
        messageEl.textContent = 'Unable to verify your email address.';
        errorEl.textContent = error.message;
        errorEl.style.display = 'block';
        loginLink.style.display = 'block';
    }
}

// Fetch with authentication
async function fetchWithAuth(url, options = {}) {
    const headers = options.headers || {};
    if (authToken) {
        headers['Authorization'] = `Bearer ${authToken}`;
    }

    const response = await fetch(url, { ...options, headers });

    // Handle 401 - redirect to login
    if (response.status === 401) {
        localStorage.removeItem('winebox_token');
        sessionStorage.removeItem('winebox_token');
        authToken = null;
        showLoginPage();
        throw new Error('Session expired');
    }

    return response;
}

// Navigation
function initNavigation() {
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', (e) => {
            const page = link.dataset.page;
            if (!page) return; // Let normal links (e.g. Admin) navigate normally
            e.preventDefault();
            navigateTo(page);
            // Close mobile menu on navigation
            const nav = document.getElementById('main-nav');
            const hamburger = document.getElementById('hamburger-btn');
            if (nav && hamburger) {
                nav.classList.remove('nav-open');
                hamburger.setAttribute('aria-expanded', 'false');
            }
        });
    });

    // Delegated handler for any [data-page] link (e.g. welcome message, empty states)
    document.addEventListener('click', (e) => {
        const link = e.target.closest('a[data-page]');
        if (!link || link.classList.contains('nav-link')) return; // nav-links handled above
        e.preventDefault();

        const page = link.dataset.page;

        // Handle mode flag for checkin page (met vs cellar)
        if (link.dataset.mode === 'met' && page === 'checkin') {
            currentCheckinMode = 'met';
            navigateTo('checkin');
            const heading = document.querySelector('#page-checkin h2');
            const subtitle = document.querySelector('#page-checkin .page-subtitle');
            if (heading) heading.textContent = 'Record a Wine';
            if (subtitle) subtitle.textContent = 'Scan a label to record a wine you\'ve encountered';
            return;
        }

        // Handle import tab shortcut on add-to-cellar page
        if (link.dataset.tab && page === 'add-to-cellar') {
            navigateTo('add-to-cellar');
            setTimeout(() => selectEntryPath(link.dataset.tab), 50);
            return;
        }

        navigateTo(page);
    });

    // Hamburger menu toggle
    const hamburger = document.getElementById('hamburger-btn');
    const nav = document.getElementById('main-nav');
    if (hamburger && nav) {
        hamburger.addEventListener('click', () => {
            const isOpen = nav.classList.toggle('nav-open');
            hamburger.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        });
    }
}

function navigateTo(page) {
    // Redirect old dashboard bookmarks to cellar
    if (page === 'dashboard') page = 'cellar';

    // Redirect search/history to cellar sub-tabs
    if (page === 'search') {
        currentCellarTab = 'search';
        page = 'cellar';
    } else if (page === 'history') {
        currentCellarTab = 'history';
        page = 'cellar';
    }

    // Update nav links — highlight "My Cellar" when on add-to-cellar page
    document.querySelectorAll('.nav-link').forEach(link => {
        const isActive = link.dataset.page === page ||
            (link.dataset.page === 'cellar' && page === 'add-to-cellar');
        link.classList.toggle('active', isActive);
        if (isActive) {
            link.setAttribute('aria-current', 'page');
        } else {
            link.removeAttribute('aria-current');
        }
    });

    // Update pages
    document.querySelectorAll('.page').forEach(p => {
        p.classList.toggle('active', p.id === `page-${page}`);
    });

    currentPage = page;

    // Update URL hash to reflect current page
    if (!isHandlingPopState) {
        const hash = page === 'cellar' && currentCellarTab !== 'dashboard'
            ? `#cellar/${currentCellarTab}`
            : `#${page}`;
        if (window.location.hash !== hash) {
            history.pushState(null, '', hash);
        }
    }

    // Track page view
    analytics.capture('page_view', { page: page });

    // Load page data
    switch (page) {
        case 'cellar':
            loadCellar();
            break;
        case 'met':
            loadMet();
            break;
        case 'add-to-cellar':
            resetAddToCellarWizard();
            break;
        case 'import':
            // Import has been merged into Add to Cellar wizard — redirect
            navigateTo('add-to-cellar');
            setTimeout(() => selectEntryPath('import'), 50);
            return;
        case 'xwines':
            loadXWinesFilters();
            break;
        case 'settings':
            loadSettings();
            break;
    }
}

// Forms
function initForms() {
    // Check-in form
    const checkinForm = document.getElementById('checkin-form');
    checkinForm.addEventListener('submit', handleCheckin);
    checkinForm.addEventListener('reset', () => {
        document.getElementById('front-preview').innerHTML = 'Tap to take photo or select image';
        document.getElementById('back-preview').innerHTML = 'Tap to take photo or select image';
        clearRawLabelText();
        lastScanResult = null;  // Clear stored scan result
    });

    // Image previews - make clickable to trigger file input
    const frontLabel = document.getElementById('front-label');
    const backLabel = document.getElementById('back-label');
    const frontPreview = document.getElementById('front-preview');
    const backPreview = document.getElementById('back-preview');

    frontLabel.addEventListener('change', (e) => {
        previewImage(e.target, 'front-preview');
        scanLabels();
    });
    backLabel.addEventListener('change', (e) => {
        previewImage(e.target, 'back-preview');
        scanLabels();
    });

    // Click on preview to trigger file input
    frontPreview.addEventListener('click', () => {
        frontLabel.click();
    });
    backPreview.addEventListener('click', () => {
        backLabel.click();
    });

    // Label text collapsible toggle
    const labelTextToggle = document.getElementById('label-text-toggle');
    if (labelTextToggle) {
        labelTextToggle.addEventListener('click', () => {
            const section = document.getElementById('label-text-section');
            const content = document.getElementById('label-text-content');
            const icon = section.querySelector('.collapse-icon');

            section.classList.toggle('open');
            if (section.classList.contains('open')) {
                content.style.display = 'block';
                icon.textContent = '-';
            } else {
                content.style.display = 'none';
                icon.textContent = '+';
            }
        });
    }

    // Cellar sub-tab switching
    document.querySelectorAll('.cellar-tab').forEach(btn => {
        btn.addEventListener('click', () => switchCellarTab(btn.dataset.cellarTab));
    });

    // Search form
    document.getElementById('search-form').addEventListener('submit', handleSearch);

    // X-Wines search form
    document.getElementById('xwines-search-form').addEventListener('submit', handleXWinesSearch);

    // Remove form
    document.getElementById('remove-form').addEventListener('submit', handleRemoval);

    // Reason picker cards (remove modal only — not case action cards)
    document.querySelectorAll('#remove-reason-picker .reason-card').forEach(card => {
        card.addEventListener('click', () => selectRemovalReason(card.dataset.reason));
    });

    // Case action reason cards
    document.querySelectorAll('.case-reason-card').forEach(card => {
        card.addEventListener('click', () => {
            document.querySelectorAll('.case-reason-card').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
            // Show/hide context fields based on reason
            document.querySelectorAll('.case-action-context').forEach(el => el.style.display = 'none');
            const reason = card.dataset.reason;
            if (reason === 'sold') {
                document.getElementById('case-action-sold-fields').style.display = 'block';
            } else if (reason === 'gifted') {
                document.getElementById('case-action-gifted-fields').style.display = 'block';
            }
        });
    });

    // Case action confirm button
    document.getElementById('case-action-confirm-btn')?.addEventListener('click', handleCaseAction);

    // Back button in remove modal
    document.getElementById('remove-back-btn').addEventListener('click', resetRemovalPicker);

    // Load sample wines button on cellar welcome panel
    document.getElementById('cellar-demo-install-btn')?.addEventListener('click', installDemoData);

    // History filter
    document.getElementById('history-filter').addEventListener('change', loadHistory);

    // Settings forms
    document.getElementById('password-form').addEventListener('submit', handlePasswordChange);

    // Delete collection
    document.getElementById('delete-collection-btn').addEventListener('click', () => {
        document.getElementById('delete-confirm-input').value = '';
        document.getElementById('confirm-delete-collection-btn').disabled = true;
        openModal('delete-collection-modal');
    });

    document.getElementById('delete-confirm-input').addEventListener('input', (e) => {
        document.getElementById('confirm-delete-collection-btn').disabled = e.target.value !== 'DELETE';
    });

    document.getElementById('confirm-delete-collection-btn').addEventListener('click', handleDeleteCollection);
}

function previewImage(input, previewId) {
    const preview = document.getElementById(previewId);
    if (input.files && input.files[0]) {
        const reader = new FileReader();
        reader.onload = (e) => {
            preview.innerHTML = `<img src="${e.target.result}" alt="Preview">`;
        };
        reader.readAsDataURL(input.files[0]);
    } else {
        preview.innerHTML = '';
    }
}

async function scanLabels() {
    const frontLabel = document.getElementById('front-label');

    // Only scan if front label is present
    if (!frontLabel.files || !frontLabel.files[0]) {
        return;
    }

    const backLabel = document.getElementById('back-label');
    const formData = new FormData();
    formData.append('front_label', frontLabel.files[0]);

    if (backLabel.files && backLabel.files[0]) {
        formData.append('back_label', backLabel.files[0]);
    }

    // Show scanning indicator
    showScanningIndicator(true);

    try {
        const response = await fetchWithAuth(`${API_BASE}/wines/scan`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Scan failed');
        }

        const result = await response.json();
        lastScanResult = result;  // Store for checkin
        populateFormFromScan(result);
        const methodName = result.method === 'claude_vision' ? 'Claude Vision' : 'Tesseract OCR';
        showToast(`Label scanned with ${methodName}`, 'success');
    } catch (error) {
        showToast(`Scan failed: ${error.message}`, 'error');
    } finally {
        showScanningIndicator(false);
    }
}

function populateFormFromScan(result) {
    const parsed = result.parsed;

    // Update fields with scanned values (overwrites previous scan results)
    const fields = {
        'wine-name': parsed.name,
        'winery': parsed.winery,
        'vintage': parsed.vintage,
        'grape-variety': parsed.grape_variety,
        'region': parsed.region,
        'sub-region': parsed.sub_region,
        'appellation': parsed.appellation,
        'country': parsed.country,
        'classification': parsed.classification,
        'alcohol': parsed.alcohol_percentage
    };

    for (const [fieldId, value] of Object.entries(fields)) {
        const input = document.getElementById(fieldId);
        if (input && value !== null && value !== undefined) {
            input.value = value;
            // Add visual indicator that field was auto-filled
            input.classList.add('auto-filled');
            setTimeout(() => input.classList.remove('auto-filled'), 2000);
        }
    }

    // Set Wine Type dropdown from enriched scan data
    if (parsed.wine_type) {
        const wineTypeSelect = document.getElementById('wine-type');
        if (wineTypeSelect) {
            const typeValue = parsed.wine_type.toLowerCase();
            const option = Array.from(wineTypeSelect.options).find(
                opt => opt.value === typeValue
            );
            if (option) {
                wineTypeSelect.value = typeValue;
                wineTypeSelect.classList.add('auto-filled');
                setTimeout(() => wineTypeSelect.classList.remove('auto-filled'), 2000);
            }
        }
    }

    // Populate raw label text section
    populateRawLabelText(result.ocr, result.method);
}

function populateRawLabelText(ocr, method) {
    const section = document.getElementById('label-text-section');
    const frontText = document.getElementById('raw-front-label-text');
    const backSection = document.getElementById('raw-back-label-section');
    const backText = document.getElementById('raw-back-label-text');
    const header = section.querySelector('h3');

    // Update header to show scan method
    const methodName = method === 'claude_vision' ? 'Claude Vision' : 'Tesseract OCR';
    header.innerHTML = `Raw Label Text <span class="scan-method-badge">${methodName}</span>`;

    if (ocr.front_label_text) {
        frontText.textContent = ocr.front_label_text;
        section.style.display = 'block';
    }

    if (ocr.back_label_text) {
        backText.textContent = ocr.back_label_text;
        backSection.style.display = 'block';
    } else {
        backSection.style.display = 'none';
    }
}

function clearRawLabelText() {
    const section = document.getElementById('label-text-section');
    const frontText = document.getElementById('raw-front-label-text');
    const backSection = document.getElementById('raw-back-label-section');
    const backText = document.getElementById('raw-back-label-text');

    section.style.display = 'none';
    section.classList.remove('open');
    document.getElementById('label-text-content').style.display = 'none';
    document.querySelector('#label-text-section .collapse-icon').textContent = '+';
    frontText.textContent = '';
    backText.textContent = '';
    backSection.style.display = 'none';
}

function showScanningIndicator(show) {
    const submitBtn = document.querySelector('#checkin-form button[type="submit"]');
    const formNote = document.querySelector('#checkin-form .form-note');

    if (show) {
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.dataset.originalText = submitBtn.textContent;
            submitBtn.textContent = 'Scanning...';
        }
        if (formNote) {
            formNote.dataset.originalText = formNote.textContent;
            formNote.textContent = 'Analyzing label with Claude Vision...';
            formNote.classList.add('scanning');
        }
    } else {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = submitBtn.dataset.originalText || 'Add Wine';
        }
        if (formNote) {
            formNote.textContent = formNote.dataset.originalText || 'Leave fields blank to use OCR-detected values';
            formNote.classList.remove('scanning');
        }
    }
}

// Store pending checkin data for confirmation
let pendingCheckinData = null;
let currentCheckinMode = 'met'; // 'met' or 'cellar' — determines where the wine is saved

function handleCheckin(e) {
    e.preventDefault();

    const frontLabel = document.getElementById('front-label');
    if (!frontLabel.files || !frontLabel.files[0]) {
        showToast('Please select a front label image', 'error');
        return;
    }

    // Store the form data for later submission
    pendingCheckinData = {
        frontLabel: frontLabel.files[0],
        backLabel: document.getElementById('back-label').files?.[0] || null,
        name: document.getElementById('wine-name').value,
        winery: document.getElementById('winery').value,
        vintage: document.getElementById('vintage').value,
        grapeVariety: document.getElementById('grape-variety').value,
        region: document.getElementById('region').value,
        subRegion: document.getElementById('sub-region').value,
        appellation: document.getElementById('appellation').value,
        country: document.getElementById('country').value,
        classification: document.getElementById('classification').value,
        alcohol: document.getElementById('alcohol').value,
        wineTypeId: document.getElementById('wine-type').value,
        notes: document.getElementById('notes').value,
        frontLabelText: lastScanResult?.ocr?.front_label_text || '',
        backLabelText: lastScanResult?.ocr?.back_label_text || '',
        customFields: collectCustomFields('custom-fields-container')
    };

    // Show the confirmation modal with editable fields
    showCheckinConfirmation();
}

function showCheckinConfirmation() {
    const modal = document.getElementById('checkin-confirm-modal');
    const data = pendingCheckinData;

    // Adapt modal for cellar vs met mode
    const headerEl = modal.querySelector('.checkin-confirm-header h3');
    const subtitleEl = modal.querySelector('.checkin-confirm-subtitle');
    const confirmBtn = document.getElementById('checkin-confirm-btn');
    const qtySection = document.getElementById('confirm-quantity-section');

    if (currentCheckinMode === 'cellar') {
        headerEl.textContent = 'Add to Cellar';
        subtitleEl.textContent = 'Review the details and set the quantity';
        confirmBtn.textContent = 'Add to Cellar';
        qtySection.style.display = 'block';
    } else {
        headerEl.textContent = 'Record Wine';
        subtitleEl.textContent = 'Review and edit the details before saving';
        confirmBtn.textContent = 'Record Wine';
        qtySection.style.display = 'none';
    }

    // Set image preview
    const imageContainer = document.getElementById('checkin-confirm-image');
    if (data.frontLabel) {
        const reader = new FileReader();
        reader.onload = (e) => {
            imageContainer.innerHTML = `<img src="${e.target.result}" alt="Wine label">`;
        };
        reader.readAsDataURL(data.frontLabel);
    } else {
        imageContainer.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted);">No image</div>';
    }

    // Populate editable fields
    document.getElementById('confirm-wine-name').value = data.name || '';
    document.getElementById('confirm-winery').value = data.winery || '';
    document.getElementById('confirm-vintage').value = data.vintage || '';
    document.getElementById('confirm-grape-variety').value = data.grapeVariety || '';
    document.getElementById('confirm-region').value = data.region || '';
    document.getElementById('confirm-sub-region').value = data.subRegion || '';
    document.getElementById('confirm-appellation').value = data.appellation || '';
    document.getElementById('confirm-country').value = data.country || '';
    document.getElementById('confirm-classification').value = data.classification || '';
    document.getElementById('confirm-alcohol').value = data.alcohol || '';
    document.getElementById('confirm-notes').value = data.notes || '';

    // Set Wine Type in confirmation modal
    const confirmWineType = document.getElementById('confirm-wine-type');
    if (confirmWineType && data.wineTypeId) {
        confirmWineType.value = data.wineTypeId;
    }

    // Set custom fields in confirmation modal
    const confirmCfContainer = document.getElementById('confirm-custom-fields-container');
    confirmCfContainer.innerHTML = '';
    if (data.customFields && Object.keys(data.customFields).length > 0) {
        for (const [key, value] of Object.entries(data.customFields)) {
            addCustomFieldRow(confirmCfContainer, key, value);
        }
    }

    // Set OCR text (hidden by default)
    const ocrSection = document.getElementById('confirm-ocr-section');
    const ocrContent = document.getElementById('confirm-ocr-content');
    const ocrToggle = document.getElementById('confirm-ocr-toggle');

    if (data.frontLabelText) {
        document.getElementById('checkin-confirm-front-ocr').textContent = data.frontLabelText;
        ocrSection.style.display = 'block';
        ocrContent.style.display = 'none';  // Hidden by default
        ocrSection.classList.remove('open');
        ocrToggle.querySelector('.collapse-icon').textContent = '+';
        ocrToggle.querySelector('.label').textContent = 'Show Raw Label Text';
    } else {
        ocrSection.style.display = 'none';
    }

    const backOcrSection = document.getElementById('checkin-confirm-back-ocr-section');
    if (data.backLabelText) {
        backOcrSection.style.display = 'block';
        document.getElementById('checkin-confirm-back-ocr').textContent = data.backLabelText;
    } else {
        backOcrSection.style.display = 'none';
    }

    // Show modal
    modal.classList.add('active');

    // Set up OCR toggle
    ocrToggle.onclick = () => {
        ocrSection.classList.toggle('open');
        if (ocrSection.classList.contains('open')) {
            ocrContent.style.display = 'block';
            ocrToggle.querySelector('.collapse-icon').textContent = '-';
            ocrToggle.querySelector('.label').textContent = 'Hide Raw Label Text';
        } else {
            ocrContent.style.display = 'none';
            ocrToggle.querySelector('.collapse-icon').textContent = '+';
            ocrToggle.querySelector('.label').textContent = 'Show Raw Label Text';
        }
    };

    // Set up button handlers
    document.getElementById('checkin-confirm-btn').onclick = submitCheckin;
    document.getElementById('checkin-cancel-btn').onclick = cancelCheckin;
}

async function submitCheckin() {
    const modal = document.getElementById('checkin-confirm-modal');
    const data = pendingCheckinData;

    // Build form data from confirmation modal fields
    const formData = new FormData();
    formData.append('front_label', data.frontLabel);
    if (data.backLabel) {
        formData.append('back_label', data.backLabel);
    }

    // Get values from confirmation modal (may have been edited)
    formData.append('name', document.getElementById('confirm-wine-name').value);
    formData.append('winery', document.getElementById('confirm-winery').value);
    const vintage = document.getElementById('confirm-vintage').value;
    if (vintage) formData.append('vintage', vintage);
    formData.append('grape_variety', document.getElementById('confirm-grape-variety').value);
    formData.append('region', document.getElementById('confirm-region').value);
    formData.append('sub_region', document.getElementById('confirm-sub-region').value);
    formData.append('appellation', document.getElementById('confirm-appellation').value);
    formData.append('country', document.getElementById('confirm-country').value);
    formData.append('classification', document.getElementById('confirm-classification').value);
    const alcohol = document.getElementById('confirm-alcohol').value;
    if (alcohol) formData.append('alcohol_percentage', alcohol);
    const wineTypeId = document.getElementById('confirm-wine-type').value;
    if (wineTypeId) formData.append('wine_type_id', wineTypeId);
    formData.append('notes', document.getElementById('confirm-notes').value);

    // Include pre-scanned OCR text to avoid rescanning (saves API costs)
    if (data.frontLabelText) {
        formData.append('front_label_text', data.frontLabelText);
    }
    if (data.backLabelText) {
        formData.append('back_label_text', data.backLabelText);
    }

    // Include custom fields
    const customFields = collectCustomFields('confirm-custom-fields-container');
    if (customFields && Object.keys(customFields).length > 0) {
        formData.append('custom_fields', JSON.stringify(customFields));
    }

    // Add quantity for cellar mode
    if (currentCheckinMode === 'cellar') {
        const qty = document.getElementById('confirm-quantity')?.value || '1';
        formData.append('quantity', qty);
    }

    try {
        const endpoint = currentCheckinMode === 'cellar' ? 'wines/checkin' : 'wines/met';
        const response = await fetchWithAuth(`${API_BASE}/${endpoint}`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || (currentCheckinMode === 'cellar' ? 'Failed to add wine' : 'Failed to record wine'));
        }

        const wine = await response.json();
        const toastMsg = currentCheckinMode === 'cellar' ? `Added to cellar: ${wine.name}` : `Recorded: ${wine.name}`;
        showToast(toastMsg, 'success');

        // Track event
        const eventName = currentCheckinMode === 'cellar' ? 'frontend_wine_cellar_added' : 'frontend_wine_met_recorded';
        analytics.capture(eventName, {
            wine_name: wine.name,
            country: document.getElementById('confirm-country').value || null
        });

        // Close modal and reset form
        modal.classList.remove('active');
        document.getElementById('checkin-form').reset();
        document.getElementById('front-preview').innerHTML = 'Tap to take photo or select image';
        document.getElementById('back-preview').innerHTML = 'Tap to take photo or select image';
        clearRawLabelText();
        lastScanResult = null;
        pendingCheckinData = null;

        // Navigate to the appropriate page
        navigateTo(currentCheckinMode === 'cellar' ? 'cellar' : 'met');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

function cancelCheckin() {
    const modal = document.getElementById('checkin-confirm-modal');
    modal.classList.remove('active');
    // Keep the form data so user can make changes and try again
}

async function handleSearch(e) {
    e.preventDefault();
    const form = e.target;
    const params = new URLSearchParams();

    // Add non-empty form values to params
    const formData = new FormData(form);
    for (const [key, value] of formData) {
        if (value && key !== 'in_stock') {
            params.append(key, value);
        }
    }

    // Handle checkbox
    const inStock = document.getElementById('search-in-stock');
    if (inStock.checked) {
        params.append('in_stock', 'true');
    }

    try {
        const response = await fetchWithAuth(`${API_BASE}/search?${params}`);
        const wines = await response.json();
        renderWineGrid('search-results', wines);
    } catch (error) {
        showToast('Search failed', 'error');
    }
}

function selectRemovalReason(reason) {
    document.getElementById('remove-reason').value = reason;
    document.getElementById('remove-reason-picker').style.display = 'none';
    document.getElementById('remove-details').style.display = 'block';

    // Hide all conditional fields and remove required
    document.querySelectorAll('.removal-conditional-field').forEach(f => {
        f.style.display = 'none';
        f.querySelectorAll('[required]').forEach(el => el.removeAttribute('required'));
    });

    // Show the relevant conditional field
    const fieldMap = { DRINK: 'drink', SELL: 'sell', GIFT: 'gift', BREAKAGE: 'breakage', OTHER: 'other' };
    const fieldId = `remove-field-${fieldMap[reason]}`;
    const field = document.getElementById(fieldId);
    if (field) {
        field.style.display = 'block';
        // Re-add required for sell price and gift recipient
        if (reason === 'SELL') {
            document.getElementById('remove-sale-price').setAttribute('required', '');
        } else if (reason === 'GIFT') {
            document.getElementById('remove-gift-recipient').setAttribute('required', '');
        }
    }

    // Update submit button text
    const btnLabels = { DRINK: 'Record', SELL: 'Record Sale', GIFT: 'Record Gift', BREAKAGE: 'Record Breakage', OTHER: 'Record' };
    document.getElementById('remove-submit-btn').textContent = btnLabels[reason] || 'Record';

    // Highlight selected reason card
    document.querySelectorAll('.reason-card').forEach(c => c.classList.remove('selected'));
    const selectedCard = document.querySelector(`.reason-card[data-reason="${reason}"]`);
    if (selectedCard) selectedCard.classList.add('selected');
}

function resetRemovalPicker() {
    document.getElementById('remove-reason').value = '';
    document.getElementById('remove-reason-picker').style.display = 'block';
    document.getElementById('remove-details').style.display = 'none';
    document.querySelectorAll('.reason-card').forEach(c => c.classList.remove('selected'));
}

async function handleRemoval(e) {
    e.preventDefault();
    const wineId = document.getElementById('remove-wine-id').value;
    const formData = new FormData(e.target);

    // Remove empty optional fields so they don't get sent as empty strings
    for (const [key, value] of [...formData.entries()]) {
        if (value === '' && key !== 'quantity') {
            formData.delete(key);
        }
    }

    try {
        const response = await fetchWithAuth(`${API_BASE}/wines/${wineId}/checkout`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Removal failed');
        }

        const wine = await response.json();
        const reason = document.getElementById('remove-reason').value;
        const qty = parseInt(formData.get('quantity')) || 1;

        // Create bottle events for removed bottles
        const eventType = { DRINK: 'drunk', SELL: 'sold', GIFT: 'gifted', BREAKAGE: 'breakage', OTHER: 'other' }[reason] || 'other';
        try {
            // Get bottles for this wine that are still in cellar
            const bottlesResp = await fetchWithAuth(`${API_BASE}/bottles?wine_id=${wineId}`);
            if (bottlesResp.ok) {
                const bottlesData = await bottlesResp.json();
                const inCellar = bottlesData.bottles.filter(b => b.in_cellar);
                const toRemove = inCellar.slice(0, qty);

                for (const bottle of toRemove) {
                    await fetchWithAuth(`${API_BASE}/bottles/${bottle.id}/events`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            event_type: eventType,
                            tasting_notes: formData.get('tasting_notes') || null,
                            sale_price: formData.get('sale_price_usd') ? parseFloat(formData.get('sale_price_usd')) : null,
                            gift_recipient: formData.get('gift_recipient') || null,
                            notes: formData.get('removal_notes') || null,
                        }),
                    });
                }
            }
        } catch (bottleErr) {
            console.warn('Failed to create bottle events:', bottleErr);
        }

        const reasonLabels = { DRINK: 'Recorded', SELL: 'Sale recorded', GIFT: 'Gift recorded', BREAKAGE: 'Breakage recorded', OTHER: 'Removal recorded' };
        showToast(`${reasonLabels[reason] || 'Removed'}: ${wine.name}`, 'success');
        closeModals();
        loadCellar();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// Modals
function initModals() {
    // Close buttons
    document.querySelectorAll('.modal-close, .modal-cancel').forEach(btn => {
        btn.addEventListener('click', closeModals);
    });

    // Click outside to close
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeModals();
            }
        });
    });

    // Escape key to close
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeModals();
        }
    });
}

function closeModals() {
    document.querySelectorAll('.modal').forEach(modal => {
        modal.classList.remove('active');
    });
}

function openModal(modalId) {
    document.getElementById(modalId).classList.add('active');
}

// (Dashboard removed — loadCellar at line ~1902 is the cellar loader)

// Active Chart.js instances (destroy before re-creating)
const _dashboardCharts = {};

function _destroyChart(id) {
    if (_dashboardCharts[id]) {
        _dashboardCharts[id].destroy();
        delete _dashboardCharts[id];
    }
}

// Color palette derived from the app's wine theme
const CHART_COLORS = [
    '#8B1A4A', '#B82860', '#D4526E', '#5C0A2D', '#A0344F',
    '#C76B8A', '#6B3A5A', '#E8A0B0', '#4A0E35', '#9E5070',
    '#D98EA5', '#7C2952', '#BF5070', '#E0C0C8', '#3A0020',
];

const WINE_TYPE_COLORS = {
    red: '#8B1A4A',
    white: '#D4A84B',
    rose: '#E8A0B0',
    sparkling: '#C9B037',
    fortified: '#5C0A2D',
    dessert: '#D4956B',
};

const WINE_TYPE_LABELS = {
    red: 'Red',
    white: 'White',
    rose: 'Rosé',
    sparkling: 'Sparkling',
    fortified: 'Fortified',
    dessert: 'Dessert',
};

const PRICE_TIER_ORDER = ['budget', 'value', 'mid_range', 'premium', 'luxury', 'ultra_premium'];
const PRICE_TIER_LABELS = {
    budget: 'Budget (< $15)',
    value: 'Value ($15-25)',
    mid_range: 'Mid-Range ($25-50)',
    premium: 'Premium ($50-100)',
    luxury: 'Luxury ($100-250)',
    ultra_premium: 'Ultra Premium (> $250)',
};
const PRICE_TIER_COLORS = {
    budget: '#6DB65B',
    value: '#A0C850',
    mid_range: '#D4A84B',
    premium: '#D4826B',
    luxury: '#B82860',
    ultra_premium: '#8B1A4A',
};

const CHART_DEFAULTS = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
        legend: {
            labels: {
                font: { family: "'Cormorant Garamond', serif", size: 13 },
                color: '#444',
            },
        },
        tooltip: {
            bodyFont: { family: "'Cormorant Garamond', serif" },
            titleFont: { family: "'Playfair Display', serif" },
        },
    },
};

function renderDashboardCharts(summary) {
    // Wine Type — doughnut
    _renderDoughnutChart('chart-wine-type', summary.by_wine_type, WINE_TYPE_LABELS, WINE_TYPE_COLORS);

    // Price Tier — doughnut
    _renderDoughnutChart('chart-price-tier', summary.by_price_tier, PRICE_TIER_LABELS, PRICE_TIER_COLORS, PRICE_TIER_ORDER);

    // Country — horizontal bar (top 10)
    _renderHorizontalBarChart('chart-country', summary.by_country, 10);

    // Grape Variety — horizontal bar (top 10)
    _renderHorizontalBarChart('chart-grape', summary.by_grape_variety, 10);

    // Vintage — vertical bar (sorted chronologically)
    _renderVintageChart('chart-vintage', summary.by_vintage);
}

function _renderDoughnutChart(canvasId, data, labelMap, colorMap, order) {
    _destroyChart(canvasId);
    const canvas = document.getElementById(canvasId);
    if (!canvas || !data || Object.keys(data).length === 0) return;

    let entries = Object.entries(data);
    if (order) {
        entries.sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]));
    } else {
        entries.sort((a, b) => b[1] - a[1]);
    }

    const labels = entries.map(([k]) => (labelMap && labelMap[k]) || k);
    const values = entries.map(([, v]) => v);
    const colors = entries.map(([k], i) => (colorMap && colorMap[k]) || CHART_COLORS[i % CHART_COLORS.length]);

    _dashboardCharts[canvasId] = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: colors,
                borderWidth: 2,
                borderColor: '#fff',
            }],
        },
        options: {
            ...CHART_DEFAULTS,
            cutout: '55%',
            plugins: {
                ...CHART_DEFAULTS.plugins,
                legend: {
                    ...CHART_DEFAULTS.plugins.legend,
                    position: 'bottom',
                },
            },
        },
    });
}

function _renderHorizontalBarChart(canvasId, data, maxItems) {
    _destroyChart(canvasId);
    const canvas = document.getElementById(canvasId);
    if (!canvas || !data || Object.keys(data).length === 0) return;

    const entries = Object.entries(data)
        .sort((a, b) => b[1] - a[1])
        .slice(0, maxItems || 10);

    const labels = entries.map(([k]) => k);
    const values = entries.map(([, v]) => v);

    _dashboardCharts[canvasId] = new Chart(canvas, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: CHART_COLORS.slice(0, entries.length),
                borderRadius: 4,
            }],
        },
        options: {
            ...CHART_DEFAULTS,
            indexAxis: 'y',
            plugins: {
                ...CHART_DEFAULTS.plugins,
                legend: { display: false },
            },
            scales: {
                x: {
                    beginAtZero: true,
                    ticks: {
                        font: { family: "'Cormorant Garamond', serif" },
                        precision: 0,
                    },
                    grid: { display: false },
                },
                y: {
                    ticks: {
                        font: { family: "'Cormorant Garamond', serif", size: 12 },
                        color: '#444',
                    },
                    grid: { display: false },
                },
            },
        },
    });
}

function _renderVintageChart(canvasId, data) {
    _destroyChart(canvasId);
    const canvas = document.getElementById(canvasId);
    if (!canvas || !data || Object.keys(data).length === 0) return;

    // Sort by year ascending
    const entries = Object.entries(data)
        .map(([k, v]) => [parseInt(k), v])
        .filter(([k]) => !isNaN(k))
        .sort((a, b) => a[0] - b[0]);

    const labels = entries.map(([k]) => String(k));
    const values = entries.map(([, v]) => v);

    _dashboardCharts[canvasId] = new Chart(canvas, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: '#8B1A4A',
                borderRadius: 3,
            }],
        },
        options: {
            ...CHART_DEFAULTS,
            plugins: {
                ...CHART_DEFAULTS.plugins,
                legend: { display: false },
            },
            scales: {
                x: {
                    ticks: {
                        font: { family: "'Cormorant Garamond', serif", size: 11 },
                        maxRotation: 45,
                        autoSkip: true,
                        maxTicksLimit: 20,
                    },
                    grid: { display: false },
                },
                y: {
                    beginAtZero: true,
                    ticks: {
                        font: { family: "'Cormorant Garamond', serif" },
                        precision: 0,
                    },
                    grid: { color: '#eee' },
                },
            },
        },
    });
}

function getRemovalBadge(t) {
    if (t.transaction_type === 'CHECK_IN') return { label: 'Added', cssClass: 'added' };
    if (!t.removal_reason) return { label: 'Removed', cssClass: 'removed' };
    const map = {
        DRINK: { label: 'Drank', cssClass: 'drank' },
        SELL: { label: 'Sold', cssClass: 'sold' },
        GIFT: { label: 'Gifted', cssClass: 'gifted' },
        OTHER: { label: 'Other', cssClass: 'other' },
    };
    return map[t.removal_reason] || { label: 'Removed', cssClass: 'removed' };
}

function getRemovalDetail(t) {
    if (t.transaction_type === 'CHECK_IN' || !t.removal_reason) return '';
    if (t.removal_reason === 'DRINK' && t.tasting_notes) {
        return `<span class="tasting-notes-display">${escapeHtml(t.tasting_notes)}</span>`;
    }
    if (t.removal_reason === 'SELL' && t.sale_price_usd != null) {
        return `<span class="sale-price-display">Sold for $${Number(t.sale_price_usd).toFixed(2)}</span>`;
    }
    if (t.removal_reason === 'GIFT' && t.gift_recipient) {
        return `<span class="gift-recipient-display">Gifted to ${escapeHtml(t.gift_recipient)}</span>`;
    }
    if (t.removal_reason === 'OTHER' && t.removal_notes) {
        return `<span class="removal-notes-display">${escapeHtml(t.removal_notes)}</span>`;
    }
    return '';
}

function renderActivityList(transactions) {
    const container = document.getElementById('recent-activity');
    if (!transactions || transactions.length === 0) {
        container.innerHTML = '<div class="empty-state">No recent activity</div>';
        return;
    }

    container.innerHTML = transactions.map(t => {
        const badge = getRemovalBadge(t);
        const detail = getRemovalDetail(t);
        return `
        <div class="activity-item">
            <div class="activity-icon ${t.transaction_type === 'CHECK_IN' ? 'check-in' : 'check-out'}">
                ${t.transaction_type === 'CHECK_IN' ? '+' : '-'}
            </div>
            <div class="activity-content">
                <div class="activity-title">
                    ${t.wine ? t.wine.name : 'Unknown Wine'}
                    ${t.wine && t.wine.vintage ? `(${t.wine.vintage})` : ''}
                </div>
                <div class="activity-meta">
                    ${t.quantity} bottle${t.quantity > 1 ? 's' : ''} &middot;
                    ${badge.label} &middot;
                    ${formatDate(t.transaction_date)}
                </div>
                ${detail ? `<div class="activity-detail">${detail}</div>` : ''}
            </div>
        </div>
    `;
    }).join('');
}

// Cellar
async function loadCellar() {
    try {
        switchCellarTab(currentCellarTab);
    } catch (error) {
        console.error('Failed to load cellar:', error);
    }
}

function switchCellarTab(tab) {
    currentCellarTab = tab;

    // Toggle tab buttons
    document.querySelectorAll('.cellar-tab').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.cellarTab === tab);
    });

    // Toggle panels
    document.querySelectorAll('.cellar-panel').forEach(panel => {
        const isActive = panel.id === `cellar-panel-${tab}`;
        panel.classList.toggle('active', isActive);
        panel.style.display = isActive ? 'block' : 'none';
    });

    // Update URL hash
    if (!isHandlingPopState) {
        const hash = tab !== 'dashboard' ? `#cellar/${tab}` : '#cellar';
        if (window.location.hash !== hash) {
            history.replaceState(null, '', hash);
        }
    }

    // Load data for the active tab
    switch (tab) {
        case 'dashboard':
            loadCellarAnalytics();
            break;
        case 'search':
            // Search results loaded on form submit
            break;
        case 'import':
            loadImportTab();
            break;
        case 'history':
            loadHistory();
            break;
    }
}

async function loadImportTab() {
    // Update welcome panel (demo data button state)
    updateWelcomePanel();

    // Find the most recent completed import batch
    try {
        const resp = await fetchWithAuth(`${API_BASE}/import/batches?limit=5`);
        if (!resp.ok) return;
        const batches = await resp.json();

        const actionsDiv = document.getElementById('import-tab-actions');
        const analyticsDiv = document.getElementById('import-batch-analytics');

        // Find the most recent completed (not rolled back) batch
        const lastBatch = batches.find(b => b.status === 'completed');

        if (lastBatch && lastBatch.wines_created > 0) {
            // Show undo button with batch info
            const lastImportInfo = document.getElementById('import-tab-last-import');
            const importDate = new Date(lastBatch.imported_at).toLocaleDateString();
            lastImportInfo.textContent = `Last import: ${lastBatch.filename} (${lastBatch.wines_created} wines, ${importDate})`;
            actionsDiv.style.display = '';

            // Wire up undo button
            const undoBtn = document.getElementById('import-tab-undo-btn');
            undoBtn.onclick = () => handleUndoLastImport(lastBatch);

            // Load batch-specific analytics
            const winesResp = await fetchWithAuth(`${API_BASE}/import/${lastBatch.id}/wines`);
            if (winesResp.ok) {
                const batchData = await winesResp.json();
                renderImportBatchAnalytics(batchData);
                analyticsDiv.style.display = '';
            }
        } else {
            actionsDiv.style.display = 'none';
            analyticsDiv.style.display = 'none';
        }
    } catch (error) {
        console.error('Failed to load import tab:', error);
    }
}

function renderImportBatchAnalytics(batchData) {
    const summary = batchData.summary;

    // Update import stats
    document.getElementById('import-stat-wines').textContent = summary.wines_created || 0;
    document.getElementById('import-stat-bottles').textContent = summary.total_bottles || 0;
    document.getElementById('import-stat-cases').textContent = summary.total_cases || 0;

    // Update heading
    const heading = document.getElementById('import-batch-heading');
    heading.textContent = `Last Import: ${batchData.filename}`;

    // Render charts using existing helpers with import-prefixed canvas IDs
    _renderDoughnutChart('chart-import-wine-type', summary.by_wine_type, WINE_TYPE_LABELS, WINE_TYPE_COLORS);
    _renderHorizontalBarChart('chart-import-country', summary.by_country, 10);
    _renderHorizontalBarChart('chart-import-grape', summary.by_grape_variety, 10);
    _renderVintageChart('chart-import-vintage', summary.by_vintage);
}

async function handleUndoLastImport(batch) {
    const confirmed = confirm(
        `Remove all ${batch.wines_created} wines from "${batch.filename}"?\n\nThis will permanently delete the wines added by this import.`
    );
    if (!confirmed) return;

    try {
        const resp = await fetchWithAuth(`${API_BASE}/import/batches/${batch.id}/wines`, {
            method: 'DELETE',
        });
        if (!resp.ok) {
            const err = await resp.json();
            showToast(err.detail || 'Failed to undo import', 'error');
            return;
        }
        const result = await resp.json();
        showToast(`Removed ${result.wines_deleted} wines from import`, 'success');

        // Refresh Import tab
        loadImportTab();

        // Refresh Dashboard analytics
        loadCellarAnalytics();
    } catch (error) {
        console.error('Failed to undo import:', error);
        showToast('Failed to undo import', 'error');
    }
}

async function updateWelcomePanel() {
    const panel = document.getElementById('cellar-welcome-panel');
    if (!panel) return;

    // Always show the panel (cards are always useful)
    panel.style.display = '';

    // Restore original HTML if it was replaced by progress bar
    if (!panel.querySelector('.entry-path-cards')) {
        // Panel was overwritten by installDemoData progress bar — page will reload
        return;
    }

    // Swap the demo button based on whether demo data is installed
    const btnContainer = panel.querySelector('.demo-welcome-content > div:last-child');
    if (!btnContainer) return;

    try {
        const resp = await fetchWithAuth(`${API_BASE}/demo/status`);
        if (!resp.ok) return;
        const status = await resp.json();

        if (status.installed && status.wine_count > 0) {
            btnContainer.innerHTML = `
                <button class="btn btn-outline btn-small" id="cellar-demo-remove-btn">Remove sample wines</button>
                <p class="demo-hint">Sample wines (${status.wine_count} wines, ${status.bottle_count} bottles)</p>
            `;
            document.getElementById('cellar-demo-remove-btn')?.addEventListener('click', removeDemoData);
        } else {
            btnContainer.innerHTML = `
                <button class="btn btn-outline btn-small" id="cellar-demo-install-btn">Load sample wines</button>
                <p class="demo-hint">Sample wines can be removed at any time</p>
            `;
            document.getElementById('cellar-demo-install-btn')?.addEventListener('click', installDemoData);
        }
    } catch { /* ignore */ }
}

async function loadCellarAnalytics() {
    try {
        // Load cellar summary for stats + charts
        const summaryResponse = await fetchWithAuth(`${API_BASE}/cellar/summary`);
        const summary = await summaryResponse.json();

        document.getElementById('stat-total-bottles').textContent = summary.total_bottles;
        document.getElementById('stat-unique-wines').textContent = summary.unique_wines;
        document.getElementById('stat-total-cases').textContent = summary.total_cases || 0;

        // Render charts
        renderDashboardCharts(summary);

        // Render value by wine type panel
        renderCellarValuePanel(summary.value_by_wine_type || []);

        // Load met count
        try {
            const metResponse = await fetchWithAuth(`${API_BASE}/met/summary`);
            const metSummary = await metResponse.json();
            document.getElementById('stat-wines-met').textContent = metSummary.total_met;
        } catch {
            document.getElementById('stat-wines-met').textContent = '0';
        }

        // Load recent activity
        const transResponse = await fetchWithAuth(`${API_BASE}/transactions?limit=10`);
        const transactions = await transResponse.json();
        renderActivityList(transactions);
    } catch (error) {
        console.error('Failed to load cellar analytics:', error);
    }
}

function renderCellarValuePanel(valueData) {
    const grid = document.getElementById('cellar-value-grid');
    if (!grid) return;

    const typeLabels = {
        'red': 'Red',
        'white': 'White',
        'rose': 'Rosé',
        'rosé': 'Rosé',
        'sparkling': 'Sparkling',
        'dessert': 'Dessert',
        'fortified': 'Fortified',
        'other': 'Other',
    };

    const typeColors = {
        'red': '#722f37',
        'white': '#f5e6a8',
        'rose': '#f4a6b8',
        'rosé': '#f4a6b8',
        'sparkling': '#d4af37',
        'dessert': '#c8956e',
        'fortified': '#8b4513',
        'other': '#888888',
    };

    if (!valueData || valueData.length === 0) {
        grid.innerHTML = '<p class="empty-hint">No wine value data available yet.</p>';
        return;
    }

    const totalValue = valueData.reduce((sum, item) => sum + item.total_value, 0);
    const totalBottles = valueData.reduce((sum, item) => sum + item.bottles, 0);

    const cards = valueData.map(item => {
        const label = typeLabels[item.wine_type] || item.wine_type || 'Other';
        const color = typeColors[item.wine_type] || typeColors['other'];
        const value = item.total_value > 0
            ? `$${item.total_value.toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0})}`
            : 'No price data';
        return `
            <div class="value-card">
                <div class="value-card-color" style="background-color: ${color}"></div>
                <div class="value-card-content">
                    <div class="value-card-type">${escapeHtml(label)}</div>
                    <div class="value-card-amount">${value}</div>
                    <div class="value-card-bottles">${item.bottles} bottle${item.bottles !== 1 ? 's' : ''}</div>
                </div>
            </div>
        `;
    }).join('');

    const totalHtml = totalValue > 0
        ? `<div class="value-total">Total estimated value: $${totalValue.toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0})} (${totalBottles} bottles)</div>`
        : `<div class="value-total">${totalBottles} bottles total</div>`;

    grid.innerHTML = cards + totalHtml;
}

function renderCellarView() {
    if (cellarViewMode === 'table') {
        renderCellarTable('cellar-list', cellarLastWines);
    } else {
        renderWineGrid('cellar-list', cellarLastWines);
    }
    // Disable export when there's nothing to export
    const exportBtn = document.getElementById('cellar-export-btn');
    if (exportBtn) {
        exportBtn.disabled = cellarLastWines.length === 0;
    }
}

function renderGroupedCellar(data) {
    const container = document.getElementById('cellar-list');
    if (!container) return;

    if (!data.wines || data.wines.length === 0) {
        container.innerHTML = emptyCellarHtml();
        return;
    }

    const cards = data.wines.map(wine => {
        const casesHtml = wine.cases.length > 0
            ? wine.cases.map(c => `
                <div class="case-row">
                    <span class="case-label">Case of ${c.case_size}</span>
                    <span class="case-count">${c.bottles_remaining}/${c.case_size} remaining</span>
                    ${c.provenance ? `<span class="case-provenance">${escapeHtml(c.provenance)}</span>` : ''}
                    ${c.bottles_remaining > 0 ? `<button class="btn btn-small btn-outline case-action-btn" data-case-id="${c.id}" data-remaining="${c.bottles_remaining}">Sell / Gift</button>` : ''}
                </div>
            `).join('')
            : '';

        const looseHtml = wine.loose_bottles > 0
            ? `<div class="case-row"><span class="case-label">Loose</span><span class="case-count">${wine.loose_bottles} bottle${wine.loose_bottles !== 1 ? 's' : ''}</span></div>`
            : '';

        return `
            <div class="wine-card" data-wine-id="${wine.wine_id}">
                <div class="wine-card-header">
                    <h3 class="wine-card-title">${escapeHtml(wine.name)}</h3>
                    ${wine.vintage ? `<span class="wine-card-vintage">${wine.vintage}</span>` : ''}
                </div>
                <div class="wine-card-meta">
                    ${wine.winery ? `<span>${escapeHtml(wine.winery)}</span>` : ''}
                    ${wine.region ? `<span>${escapeHtml(wine.region)}</span>` : ''}
                    ${wine.country ? `<span>${escapeHtml(wine.country)}</span>` : ''}
                </div>
                ${wine.wine_type ? `<span class="wine-type-badge">${escapeHtml(wine.wine_type)}</span>` : ''}
                <div class="wine-card-cases">
                    ${casesHtml}
                    ${looseHtml}
                </div>
                <div class="wine-card-footer">
                    <span class="wine-quantity">${wine.total_bottles} bottle${wine.total_bottles !== 1 ? 's' : ''}${wine.cases.length > 0 ? ` (${wine.cases.length} case${wine.cases.length !== 1 ? 's' : ''})` : ''}</span>
                    ${wine.total_bottles > 0 ? `<button class="btn btn-small btn-primary remove-btn" data-wine-id="${wine.wine_id}" data-quantity="${wine.total_bottles}">Remove</button>` : ''}
                </div>
            </div>
        `;
    }).join('');

    container.innerHTML = cards;

    // Wire up click handlers for wine detail modal
    container.querySelectorAll('.wine-card[data-wine-id]').forEach(card => {
        card.addEventListener('click', (e) => {
            if (!e.target.classList.contains('remove-btn') && !e.target.classList.contains('case-action-btn')) {
                showWineDetail(card.dataset.wineId);
            }
        });
    });

    // Wire up remove buttons
    container.querySelectorAll('.remove-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            openRemoveModal(btn.dataset.wineId, btn.dataset.quantity);
        });
    });

    // Wire up case action buttons
    container.querySelectorAll('.case-action-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            openCaseActionModal(btn.dataset.caseId, btn.dataset.remaining);
        });
    });
}

function renderGroupedCellarTable(data) {
    const container = document.getElementById('cellar-list');
    if (!container) return;

    if (!data.wines || data.wines.length === 0) {
        container.innerHTML = emptyCellarHtml();
        return;
    }

    const rows = data.wines.map(wine => {
        const caseInfo = wine.cases.length > 0
            ? wine.cases.map(c => {
                const prov = c.provenance ? ` <span class="text-muted">(${escapeHtml(c.provenance)})</span>` : '';
                return `<span class="breakdown-case">${c.bottles_remaining}/${c.case_size} case${prov}</span>`;
            }).join('')
            : '';
        const looseInfo = wine.loose_bottles > 0
            ? `<span class="breakdown-loose">${wine.loose_bottles} loose</span>`
            : '';

        return `
            <tr class="cellar-table-row" data-wine-id="${wine.wine_id}">
                <td><strong>${escapeHtml(wine.name)}</strong>${wine.winery ? `<br><span class="text-muted">${escapeHtml(wine.winery)}</span>` : ''}</td>
                <td>${wine.vintage || '\u2014'}</td>
                <td class="wine-type-cell">${wine.wine_type ? `<span class="wine-type-badge">${escapeHtml(wine.wine_type)}</span>` : '\u2014'}</td>
                <td>${wine.country ? escapeHtml(wine.country) : '\u2014'}</td>
                <td><strong>${wine.total_bottles}</strong></td>
                <td>${caseInfo}${looseInfo}</td>
                <td>
                    ${wine.total_bottles > 0 ? `<button class="btn btn-small btn-primary remove-btn" data-wine-id="${wine.wine_id}" data-quantity="${wine.total_bottles}">Remove</button>` : ''}
                </td>
            </tr>
        `;
    }).join('');

    container.innerHTML = `
        <table class="cellar-table">
            <thead>
                <tr>
                    <th>Wine</th>
                    <th>Vintage</th>
                    <th>Type</th>
                    <th>Country</th>
                    <th>Bottles</th>
                    <th>Breakdown</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
    `;

    // Wire up click handlers for wine detail modal
    container.querySelectorAll('.cellar-table-row[data-wine-id]').forEach(row => {
        row.addEventListener('click', (e) => {
            if (!e.target.classList.contains('remove-btn')) {
                showWineDetail(row.dataset.wineId);
            }
        });
        row.style.cursor = 'pointer';
    });

    // Wire up remove buttons
    container.querySelectorAll('.remove-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            openRemoveModal(btn.dataset.wineId, btn.dataset.quantity);
        });
    });
}

function setCellarViewMode(mode) {
    cellarViewMode = mode;
}

function emptyCellarHtml() {
    return '';
}

function renderCellarTable(containerId, wines) {
    const container = document.getElementById(containerId);
    if (!wines || wines.length === 0) {
        container.innerHTML = emptyCellarHtml();
        return;
    }

    const tableRows = wines.map(wine => {
        const quantity = wine.inventory ? wine.inventory.quantity : 0;
        const inStock = quantity > 0;
        const ef = wine.enriched_fields || [];

        const additionalFields = [];
        if (wine.sub_region) additionalFields.push(['Sub-Region', `<span class="${ef.includes('sub_region') ? 'enriched' : ''}">${escapeHtml(wine.sub_region)}</span>`]);
        if (wine.appellation) additionalFields.push(['Appellation', `<span class="${ef.includes('appellation') ? 'enriched' : ''}">${escapeHtml(wine.appellation)}</span>`]);
        if (wine.classification) additionalFields.push(['Classification', `<span class="${ef.includes('classification') ? 'enriched' : ''}">${escapeHtml(wine.classification)}</span>`]);
        if (wine.alcohol_percentage) additionalFields.push(['Alcohol', `<span class="${ef.includes('alcohol_percentage') ? 'enriched' : ''}">${escapeHtml(String(wine.alcohol_percentage))}%</span>`]);
        if (wine.wine_type_id) additionalFields.push(['Wine Type', `<span class="${ef.includes('wine_type_id') ? 'enriched' : ''}">${escapeHtml(wine.wine_type_id)}</span>`]);
        if (wine.price_tier) additionalFields.push(['Price Tier', `<span class="${ef.includes('price_tier') ? 'enriched' : ''}">${escapeHtml(wine.price_tier)}</span>`]);
        if (wine.notes) additionalFields.push(['Notes', escapeHtml(wine.notes)]);
        if (wine.custom_fields) {
            Object.entries(wine.custom_fields).forEach(([k, v]) => {
                if (v) additionalFields.push([escapeHtml(k), escapeHtml(v)]);
            });
        }

        const hasDetails = additionalFields.length > 0;

        const detailRow = hasDetails ? `
            <tr class="wine-table-detail-row" data-detail-for="${wine.id}">
                <td colspan="8">
                    <div class="wine-table-detail-content">
                        ${additionalFields.map(([label, value]) => `
                            <div class="wine-table-detail-field">
                                <div class="label">${label}</div>
                                <div class="value">${value}</div>
                            </div>
                        `).join('')}
                    </div>
                </td>
            </tr>
        ` : '';

        return `
            <tr class="wine-table-row" data-wine-id="${wine.id}">
                <td class="wine-table-name">${hasDetails ? `<span class="wine-table-expand" data-wine-id="${wine.id}">&#9654;</span> ` : ''}${escapeHtml(wine.name)}</td>
                <td>${wine.winery ? `<span class="${ef.includes('winery') ? 'enriched' : ''}">${escapeHtml(wine.winery)}</span>` : '-'}</td>
                <td>${wine.vintage || '-'}</td>
                <td>${wine.grape_variety ? `<span class="${ef.includes('grape_variety') ? 'enriched' : ''}">${escapeHtml(wine.grape_variety)}</span>` : '-'}</td>
                <td class="wine-table-hide-mobile">${wine.region ? `<span class="${ef.includes('region') ? 'enriched' : ''}">${escapeHtml(wine.region)}</span>` : '-'}</td>
                <td class="wine-table-hide-mobile">${wine.country ? `<span class="${ef.includes('country') ? 'enriched' : ''}">${escapeHtml(wine.country)}</span>` : '-'}</td>
                <td><span class="wine-quantity ${inStock ? '' : 'out-of-stock'}">${inStock ? quantity : 'Out'}</span></td>
                <td>${inStock ? `<button class="btn btn-small btn-primary remove-btn" data-wine-id="${wine.id}" data-quantity="${quantity}">Remove</button>` : ''}</td>
            </tr>
            ${detailRow}
        `;
    }).join('');

    container.innerHTML = `
        <div class="wine-table-wrapper">
            <table class="wine-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Winery</th>
                        <th>Vintage</th>
                        <th>Grape</th>
                        <th class="wine-table-hide-mobile">Region</th>
                        <th class="wine-table-hide-mobile">Country</th>
                        <th>Qty</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${tableRows}
                </tbody>
            </table>
        </div>
    `;

    container.querySelectorAll('.wine-table-expand').forEach(chevron => {
        chevron.addEventListener('click', (e) => {
            e.stopPropagation();
            const wineId = chevron.dataset.wineId;
            const detailRow = container.querySelector(`.wine-table-detail-row[data-detail-for="${wineId}"]`);
            if (detailRow) {
                detailRow.classList.toggle('expanded');
                chevron.classList.toggle('expanded');
            }
        });
    });

    container.querySelectorAll('.wine-table-row').forEach(row => {
        row.addEventListener('click', (e) => {
            if (!e.target.classList.contains('remove-btn') && !e.target.classList.contains('wine-table-expand')) {
                showWineDetail(row.dataset.wineId);
            }
        });
    });

    container.querySelectorAll('.remove-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            openRemoveModal(btn.dataset.wineId, btn.dataset.quantity);
        });
    });

    // Make table sortable by column headers
    const cellarTable = container.querySelector('.wine-table');
    if (cellarTable) makeTableSortable(cellarTable);
}

function renderWineGrid(containerId, wines) {
    const container = document.getElementById(containerId);
    if (!wines || wines.length === 0) {
        container.innerHTML = emptyCellarHtml();
        return;
    }

    container.innerHTML = wines.map(wine => {
        const quantity = wine.inventory ? wine.inventory.quantity : 0;
        const inStock = quantity > 0;
        const ef = wine.enriched_fields || [];

        // Build "More" section tags
        const moreTags = [];
        if (wine.grape_variety) moreTags.push(`<span class="wine-tag${ef.includes('grape_variety') ? ' enriched' : ''}"><span class="wine-tag-label">Grape:</span> ${escapeHtml(wine.grape_variety)}</span>`);
        if (wine.appellation) moreTags.push(`<span class="wine-tag${ef.includes('appellation') ? ' enriched' : ''}"><span class="wine-tag-label">Appellation:</span> ${escapeHtml(wine.appellation)}</span>`);
        if (wine.classification) moreTags.push(`<span class="wine-tag${ef.includes('classification') ? ' enriched' : ''}"><span class="wine-tag-label">Classification:</span> ${escapeHtml(wine.classification)}</span>`);
        if (wine.sub_region) moreTags.push(`<span class="wine-tag${ef.includes('sub_region') ? ' enriched' : ''}"><span class="wine-tag-label">Sub-region:</span> ${escapeHtml(wine.sub_region)}</span>`);
        if (wine.alcohol_percentage) moreTags.push(`<span class="wine-tag${ef.includes('alcohol_percentage') ? ' enriched' : ''}"><span class="wine-tag-label">ABV:</span> ${escapeHtml(String(wine.alcohol_percentage))}%</span>`);
        if (wine.notes) moreTags.push(`<span class="wine-tag wine-tag-custom" title="${escapeHtml(wine.notes)}">${escapeHtml(wine.notes.length > 50 ? wine.notes.substring(0, 50) + '...' : wine.notes)}</span>`);
        if (wine.custom_fields) {
            Object.entries(wine.custom_fields).forEach(([k, v]) => {
                if (v) moreTags.push(`<span class="wine-tag wine-tag-custom"><span class="wine-tag-label">${escapeHtml(k)}:</span> ${escapeHtml(v)}</span>`);
            });
        }

        return `
            <div class="wine-card" data-wine-id="${wine.id}">
                <div class="wine-card-image">
                    ${wine.front_label_image_path
                        ? `<img src="/api/images/${wine.front_label_image_path}" alt="${wine.name}">`
                        : '<span style="color: white; opacity: 0.6;">No Image</span>'
                    }
                </div>
                <div class="wine-card-content">
                    <div class="wine-card-title">${wine.name}</div>
                    <div class="wine-card-subtitle">
                        ${wine.winery ? `<span class="${ef.includes('winery') ? 'enriched' : ''}">${escapeHtml(wine.winery)}</span>` : ''}
                        ${wine.vintage ? ` - ${wine.vintage}` : ''}
                    </div>
                    <div class="wine-card-fields">
                        <div class="wine-card-field">
                            <span class="wine-card-field-label">Country</span>
                            <span class="wine-card-field-value${ef.includes('country') ? ' enriched' : ''}">${wine.country ? escapeHtml(wine.country) : '\u2014'}</span>
                        </div>
                        <div class="wine-card-field">
                            <span class="wine-card-field-label">Region</span>
                            <span class="wine-card-field-value${ef.includes('region') ? ' enriched' : ''}">${wine.region ? escapeHtml(wine.region) : '\u2014'}</span>
                        </div>
                    </div>
                    ${moreTags.length > 0 ? `
                        <div class="wine-card-extra" style="display: none;">
                            ${moreTags.join('')}
                        </div>
                        <span class="wine-card-expand-btn">More...</span>
                    ` : ''}
                    <div class="wine-card-footer">
                        <span class="wine-quantity ${inStock ? '' : 'out-of-stock'}">
                            ${inStock ? `${quantity} bottle${quantity > 1 ? 's' : ''}` : 'Out of stock'}
                        </span>
                        ${inStock ? `<button class="btn btn-small btn-primary remove-btn" data-wine-id="${wine.id}" data-quantity="${quantity}">Remove</button>` : ''}
                    </div>
                </div>
            </div>
        `;
    }).join('');

    // Add click handlers
    container.querySelectorAll('.wine-card').forEach(card => {
        card.addEventListener('click', (e) => {
            if (!e.target.classList.contains('remove-btn') && !e.target.classList.contains('wine-card-expand-btn')) {
                showWineDetail(card.dataset.wineId);
            }
        });
    });

    container.querySelectorAll('.remove-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            openRemoveModal(btn.dataset.wineId, btn.dataset.quantity);
        });
    });

    // Add expand/collapse handlers for extra tags
    container.querySelectorAll('.wine-card-expand-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const extra = btn.previousElementSibling;
            if (extra && extra.classList.contains('wine-card-extra')) {
                const isHidden = extra.style.display === 'none';
                extra.style.display = isHidden ? 'flex' : 'none';
                btn.textContent = isHidden ? 'Less' : 'More...';
            }
        });
    });
}

async function showWineDetail(wineId) {
    try {
        const response = await fetchWithAuth(`${API_BASE}/wines/${wineId}`);
        const wine = await response.json();

        const quantity = wine.inventory ? wine.inventory.quantity : 0;
        const enrichedFields = wine.enriched_fields || [];
        const enrichedClass = (fieldKey) => enrichedFields.includes(fieldKey) ? ' enriched' : '';

        // Fetch bottle/case data for this wine
        let bottleInfo = null;
        try {
            const bottlesResp = await fetchWithAuth(`${API_BASE}/bottles?wine_id=${wineId}`);
            if (bottlesResp.ok) {
                bottleInfo = await bottlesResp.json();
            }
        } catch { /* bottles endpoint may not be available */ }

        // Build case/bottle breakdown HTML
        let bottleBreakdownHtml = '';
        if (bottleInfo && bottleInfo.bottles && bottleInfo.bottles.length > 0) {
            const bottles = bottleInfo.bottles;
            const inCellar = bottles.filter(b => b.in_cellar);
            const totalInCellar = inCellar.length;

            // Group by case
            const caseMap = {};
            let looseCount = 0;
            for (const b of inCellar) {
                if (b.case_id) {
                    if (!caseMap[b.case_id]) caseMap[b.case_id] = { bottles: [], case_id: b.case_id };
                    caseMap[b.case_id].bottles.push(b);
                } else {
                    looseCount++;
                }
            }

            // Fetch case details for provenance/size
            const caseRows = [];
            for (const [caseId, caseData] of Object.entries(caseMap)) {
                let caseSize = caseData.bottles.length;
                let provenance = '';
                let purchasePrice = '';
                try {
                    const caseResp = await fetchWithAuth(`${API_BASE}/cases/${caseId}`);
                    if (caseResp.ok) {
                        const caseDetail = await caseResp.json();
                        caseSize = caseDetail.case_size || caseSize;
                        provenance = caseDetail.provenance || '';
                        purchasePrice = caseDetail.purchase_price ? `\u00a3${caseDetail.purchase_price.toFixed(2)}` : '';
                    }
                } catch { /* case detail not available */ }

                caseRows.push(`
                    <div class="wine-detail-case-row">
                        <span class="case-label">Case of ${caseSize}</span>
                        <span class="case-count">${caseData.bottles.length}/${caseSize} remaining</span>
                        ${provenance ? `<span class="case-provenance">from ${escapeHtml(provenance)}</span>` : ''}
                        ${purchasePrice ? `<span class="case-price">${purchasePrice}</span>` : ''}
                        ${caseData.bottles.length > 0 ? `<button class="btn btn-small btn-outline case-action-btn" data-case-id="${caseId}" data-remaining="${caseData.bottles.length}">Sell / Gift</button>` : ''}
                    </div>
                `);
            }

            const looseHtml = looseCount > 0
                ? `<div class="wine-detail-case-row"><span class="case-label">Loose</span><span class="case-count">${looseCount} bottle${looseCount !== 1 ? 's' : ''}</span></div>`
                : '';

            bottleBreakdownHtml = `
                <div class="wine-detail-bottles">
                    <div class="label">Cellar Breakdown</div>
                    <div class="wine-detail-bottle-list">
                        ${caseRows.join('')}
                        ${looseHtml}
                    </div>
                </div>
            `;
        }

        document.getElementById('wine-detail').innerHTML = `
            <div class="wine-detail-images">
                ${wine.front_label_image_path
                    ? `<div class="wine-detail-image"><img src="/api/images/${wine.front_label_image_path}" alt="Front label"></div>`
                    : ''
                }
                ${wine.back_label_image_path
                    ? `<div class="wine-detail-image"><img src="/api/images/${wine.back_label_image_path}" alt="Back label"></div>`
                    : ''
                }
            </div>
            <div class="wine-detail-info">
                <h3>${wine.name}</h3>
                <div class="wine-detail-meta">
                    ${wine.winery ? `<span class="${enrichedClass('winery')}">${wine.winery}</span>` : ''}
                    ${wine.vintage ? ` - ${wine.vintage}` : ''}
                </div>

                <div class="wine-detail-fields">
                    <div class="wine-detail-field">
                        <div class="label">In Stock</div>
                        <div class="value">${quantity} bottle${quantity !== 1 ? 's' : ''}</div>
                    </div>

                    ${bottleBreakdownHtml}

                    ${wine.grape_variety ? `
                        <div class="wine-detail-field">
                            <div class="label">Grape Variety</div>
                            <div class="value${enrichedClass('grape_variety')}">${wine.grape_variety}</div>
                        </div>
                    ` : ''}

                    ${wine.region ? `
                        <div class="wine-detail-field">
                            <div class="label">Region</div>
                            <div class="value${enrichedClass('region')}">${wine.region}</div>
                        </div>
                    ` : ''}

                    ${wine.sub_region ? `
                        <div class="wine-detail-field">
                            <div class="label">Sub-Region</div>
                            <div class="value">${wine.sub_region}</div>
                        </div>
                    ` : ''}

                    ${wine.appellation ? `
                        <div class="wine-detail-field">
                            <div class="label">Appellation</div>
                            <div class="value">${wine.appellation}</div>
                        </div>
                    ` : ''}

                    ${wine.country ? `
                        <div class="wine-detail-field">
                            <div class="label">Country</div>
                            <div class="value${enrichedClass('country')}">${wine.country}</div>
                        </div>
                    ` : ''}

                    ${wine.classification ? `
                        <div class="wine-detail-field">
                            <div class="label">Classification</div>
                            <div class="value">${wine.classification}</div>
                        </div>
                    ` : ''}

                    ${wine.alcohol_percentage ? `
                        <div class="wine-detail-field">
                            <div class="label">Alcohol</div>
                            <div class="value${enrichedClass('alcohol_percentage')}">${wine.alcohol_percentage}%</div>
                        </div>
                    ` : ''}
                </div>

                ${wine.custom_fields && Object.keys(wine.custom_fields).length > 0 ? `
                    <div class="wine-detail-custom-fields">
                        ${Object.entries(wine.custom_fields).map(([k, v]) => `
                            <div class="wine-detail-field">
                                <div class="label">${escapeHtml(k)}</div>
                                <div class="value">${escapeHtml(v)}</div>
                            </div>
                        `).join('')}
                    </div>
                ` : ''}

                ${wine.front_label_text ? `
                    <div class="wine-detail-label-text collapsible">
                        <div class="collapsible-header" data-action="toggle-label-text">
                            <span class="label">Show Raw Label Text</span>
                            <span class="collapse-icon">+</span>
                        </div>
                        <div class="collapsible-content" style="display: none;">
                            <div class="ocr-raw-text">
                                <div class="ocr-raw-section">
                                    <label>Front Label:</label>
                                    <pre>${escapeHtml(wine.front_label_text)}</pre>
                                </div>
                                ${wine.back_label_text ? `
                                    <div class="ocr-raw-section">
                                        <label>Back Label:</label>
                                        <pre>${escapeHtml(wine.back_label_text)}</pre>
                                    </div>
                                ` : ''}
                            </div>
                        </div>
                    </div>
                ` : ''}

                <div style="margin-top: 1.5rem; display: flex; gap: 1rem;">
                    ${quantity > 0 ? `<button class="btn btn-primary detail-remove-btn" data-wine-id="${wine.id}" data-quantity="${quantity}">Remove</button>` : ''}
                    <button class="btn btn-danger detail-delete-btn" data-wine-id="${wine.id}">Delete Wine</button>
                </div>
            </div>

            ${wine.transactions && wine.transactions.length > 0 ? `
                <div class="wine-detail-transactions">
                    <h3>Transaction History</h3>
                    <div class="transaction-list">
                        ${wine.transactions.map(t => {
                            const badge = getRemovalBadge(t);
                            const detail = getRemovalDetail(t);
                            return `
                            <div class="transaction-item">
                                <span class="transaction-type ${badge.cssClass}">
                                    ${badge.label}
                                </span>
                                <span class="transaction-quantity">${t.quantity} bottle${t.quantity > 1 ? 's' : ''}</span>
                                <span class="transaction-date">${formatDate(t.transaction_date)}</span>
                                ${detail ? `<span class="transaction-detail">${detail}</span>` : ''}
                                ${t.notes ? `<span>${t.notes}</span>` : ''}
                            </div>
                        `;}).join('')}
                    </div>
                </div>
            ` : ''}
        `;

        openModal('wine-modal');

        // Wire up action buttons (CSP-compliant — no inline onclick)
        const detailEl = document.getElementById('wine-detail');
        detailEl.querySelector('.detail-remove-btn')?.addEventListener('click', (e) => {
            openRemoveModal(e.target.dataset.wineId, e.target.dataset.quantity);
        });
        detailEl.querySelector('.detail-delete-btn')?.addEventListener('click', (e) => {
            deleteWine(e.target.dataset.wineId);
        });
        detailEl.querySelector('[data-action="toggle-label-text"]')?.addEventListener('click', (e) => {
            const header = e.target.closest('[data-action="toggle-label-text"]');
            const content = header.nextElementSibling;
            const icon = header.querySelector('.collapse-icon');
            if (content.style.display === 'none') {
                content.style.display = 'block';
                icon.textContent = '−';
            } else {
                content.style.display = 'none';
                icon.textContent = '+';
            }
        });

        // Wire up case action buttons in the detail modal
        detailEl.querySelectorAll('.case-action-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                openCaseActionModal(btn.dataset.caseId, btn.dataset.remaining);
            });
        });
    } catch (error) {
        showToast('Failed to load wine details', 'error');
    }
}

function openRemoveModal(wineId, availableQuantity) {
    document.getElementById('remove-wine-id').value = wineId;
    document.getElementById('remove-quantity').max = availableQuantity;
    document.getElementById('remove-quantity').value = 1;
    document.getElementById('remove-available').textContent = `(${availableQuantity} available)`;
    // Reset form fields
    document.getElementById('remove-tasting-notes').value = '';
    document.getElementById('remove-sale-price').value = '';
    document.getElementById('remove-gift-recipient').value = '';
    document.getElementById('remove-removal-notes').value = '';
    resetRemovalPicker();
    openModal('remove-modal');
}

function openCaseActionModal(caseId, remaining) {
    const modal = document.getElementById('case-action-modal');
    if (!modal) return;

    document.getElementById('case-action-case-id').value = caseId;
    document.getElementById('case-action-remaining').textContent = `${remaining} bottle${remaining != 1 ? 's' : ''} remaining`;
    document.getElementById('case-action-notes').value = '';
    document.getElementById('case-action-sale-price').value = '';
    document.getElementById('case-action-buyer').value = '';
    document.getElementById('case-action-recipient').value = '';

    // Hide all context fields initially
    document.querySelectorAll('.case-action-context').forEach(el => el.style.display = 'none');

    // Reset reason selection
    document.querySelectorAll('.case-reason-card').forEach(card => card.classList.remove('selected'));

    openModal('case-action-modal');
}

async function handleCaseAction() {
    const caseId = document.getElementById('case-action-case-id').value;
    const selectedCard = document.querySelector('.case-reason-card.selected');
    if (!selectedCard) {
        showToast('Please select a reason', 'error');
        return;
    }

    const eventType = selectedCard.dataset.reason;
    const body = {
        event_type: eventType,
        notes: document.getElementById('case-action-notes').value || null,
    };

    if (eventType === 'sold') {
        const price = document.getElementById('case-action-sale-price').value;
        body.sale_price = price ? parseFloat(price) : null;
        body.buyer = document.getElementById('case-action-buyer').value || null;
    } else if (eventType === 'gifted') {
        body.gift_recipient = document.getElementById('case-action-recipient').value || null;
    }

    try {
        const response = await fetchWithAuth(`${API_BASE}/cases/${caseId}/events`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to process case action');
        }

        const result = await response.json();
        closeModals();
        showToast(`${result.bottles_affected} bottle${result.bottles_affected !== 1 ? 's' : ''} ${eventType}`, 'success');
        loadCellar();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

function deleteWine(wineId) {
    openModal('delete-wine-modal');
    const confirmBtn = document.getElementById('confirm-delete-wine-btn');
    const handler = async () => {
        confirmBtn.removeEventListener('click', handler);
        closeModals();
        try {
            const response = await fetchWithAuth(`${API_BASE}/wines/${wineId}`, {
                method: 'DELETE'
            });
            if (!response.ok) throw new Error('Delete failed');
            showToast('Wine deleted', 'success');
            loadCellar();
        } catch (error) {
            showToast('Failed to delete wine', 'error');
        }
    };
    confirmBtn.addEventListener('click', handler);
}

// History
async function loadHistory() {
    const filter = document.getElementById('history-filter').value;
    let url = `${API_BASE}/transactions?limit=100`;
    if (filter === 'CHECK_IN' || filter === 'CHECK_OUT') {
        url += `&transaction_type=${filter}`;
    } else if (filter === 'DRINK' || filter === 'SELL' || filter === 'GIFT' || filter === 'OTHER') {
        url += `&transaction_type=CHECK_OUT&removal_reason=${filter}`;
    }

    try {
        const response = await fetchWithAuth(url);
        const transactions = await response.json();
        renderTransactionList(transactions);
        renderHistoryCharts(transactions);
    } catch (error) {
        console.error('Failed to load history:', error);
    }
}

function renderTransactionList(transactions) {
    const container = document.getElementById('history-list');
    // Disable export when there's nothing to export
    const historyExportBtn = document.getElementById('history-export-btn');
    if (historyExportBtn) {
        historyExportBtn.disabled = !transactions || transactions.length === 0;
    }
    if (!transactions || transactions.length === 0) {
        container.innerHTML = '<div class="empty-state"><h3>No transactions yet</h3><p>Add some wine to get started</p></div>';
        return;
    }

    container.innerHTML = transactions.map(t => {
        const badge = getRemovalBadge(t);
        const detail = getRemovalDetail(t);
        return `
        <div class="transaction-item">
            <span class="transaction-type ${badge.cssClass}">
                ${badge.label}
            </span>
            <span class="transaction-wine">
                ${t.wine ? t.wine.name : 'Unknown Wine'}
                ${t.wine && t.wine.vintage ? `<span class="vintage">(${t.wine.vintage})</span>` : ''}
                ${detail ? `<span class="transaction-detail">${detail}</span>` : ''}
            </span>
            <span class="transaction-quantity">${t.quantity} bottle${t.quantity > 1 ? 's' : ''}</span>
            <span class="transaction-date">${formatDate(t.transaction_date)}</span>
        </div>
    `;
    }).join('');
}

// History Charts
function renderHistoryCharts(transactions) {
    const chartsContainer = document.getElementById('history-charts');
    if (!transactions || transactions.length === 0) {
        chartsContainer.style.display = 'none';
        return;
    }
    chartsContainer.style.display = '';

    _renderTimelineChart(transactions);
    _renderReasonsChart(transactions);
    _renderHistoryStats(transactions);
}

function _renderTimelineChart(transactions) {
    _destroyChart('chart-history-timeline');
    const canvas = document.getElementById('chart-history-timeline');
    if (!canvas) return;

    // Group by month
    const monthsMap = {};
    transactions.forEach(t => {
        const d = new Date(t.transaction_date);
        const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
        if (!monthsMap[key]) monthsMap[key] = { added: 0, removed: 0 };
        if (t.transaction_type === 'CHECK_IN') {
            monthsMap[key].added += t.quantity;
        } else {
            monthsMap[key].removed += t.quantity;
        }
    });

    const sortedKeys = Object.keys(monthsMap).sort();
    const labels = sortedKeys.map(k => {
        const [y, m] = k.split('-');
        return new Date(y, m - 1).toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
    });

    _dashboardCharts['chart-history-timeline'] = new Chart(canvas, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                {
                    label: 'Added',
                    data: sortedKeys.map(k => monthsMap[k].added),
                    backgroundColor: 'rgba(74, 124, 89, 0.7)',
                    borderRadius: 3,
                },
                {
                    label: 'Removed',
                    data: sortedKeys.map(k => -monthsMap[k].removed),
                    backgroundColor: 'rgba(139, 26, 74, 0.7)',
                    borderRadius: 3,
                },
            ],
        },
        options: {
            ...CHART_DEFAULTS,
            plugins: {
                ...CHART_DEFAULTS.plugins,
                legend: {
                    ...CHART_DEFAULTS.plugins.legend,
                    position: 'top',
                },
                tooltip: {
                    ...CHART_DEFAULTS.plugins.tooltip,
                    callbacks: {
                        label: function(ctx) {
                            const val = Math.abs(ctx.raw);
                            return `${ctx.dataset.label}: ${val} bottle${val !== 1 ? 's' : ''}`;
                        },
                    },
                },
            },
            scales: {
                x: {
                    ticks: {
                        font: { family: "'Cormorant Garamond', serif", size: 11 },
                        maxRotation: 45,
                        autoSkip: true,
                    },
                    grid: { display: false },
                },
                y: {
                    ticks: {
                        font: { family: "'Cormorant Garamond', serif" },
                        callback: v => Math.abs(v),
                        precision: 0,
                    },
                    grid: { color: 'rgba(0,0,0,0.05)' },
                },
            },
        },
    });
}

function _renderReasonsChart(transactions) {
    _destroyChart('chart-history-reasons');
    const canvas = document.getElementById('chart-history-reasons');
    if (!canvas) return;

    const removals = transactions.filter(t => t.transaction_type === 'CHECK_OUT');
    if (removals.length === 0) {
        canvas.parentElement.parentElement.style.display = 'none';
        return;
    }
    canvas.parentElement.parentElement.style.display = '';

    const reasonCounts = {};
    removals.forEach(t => {
        const reason = t.removal_reason || 'LEGACY';
        reasonCounts[reason] = (reasonCounts[reason] || 0) + t.quantity;
    });

    const labelMap = { DRINK: 'Drank', SELL: 'Sold', GIFT: 'Gifted', OTHER: 'Other', LEGACY: 'Removed' };
    const colorMap = { DRINK: '#8B1A4A', SELL: '#2962A8', GIFT: '#7E3AA8', OTHER: '#C9A227', LEGACY: '#999' };
    const order = ['DRINK', 'SELL', 'GIFT', 'OTHER', 'LEGACY'];

    const entries = Object.entries(reasonCounts)
        .sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]));

    _dashboardCharts['chart-history-reasons'] = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: entries.map(([k]) => labelMap[k] || k),
            datasets: [{
                data: entries.map(([, v]) => v),
                backgroundColor: entries.map(([k]) => colorMap[k] || '#ccc'),
                borderWidth: 2,
                borderColor: '#fff',
            }],
        },
        options: {
            ...CHART_DEFAULTS,
            cutout: '55%',
            plugins: {
                ...CHART_DEFAULTS.plugins,
                legend: {
                    ...CHART_DEFAULTS.plugins.legend,
                    position: 'bottom',
                },
                tooltip: {
                    ...CHART_DEFAULTS.plugins.tooltip,
                    callbacks: {
                        label: function(ctx) {
                            return `${ctx.label}: ${ctx.raw} bottle${ctx.raw !== 1 ? 's' : ''}`;
                        },
                    },
                },
            },
        },
    });
}

function _renderHistoryStats(transactions) {
    const container = document.getElementById('history-stats');
    if (!container) return;

    const totalAdded = transactions.filter(t => t.transaction_type === 'CHECK_IN').reduce((sum, t) => sum + t.quantity, 0);
    const totalRemoved = transactions.filter(t => t.transaction_type === 'CHECK_OUT').reduce((sum, t) => sum + t.quantity, 0);
    const totalTransactions = transactions.length;

    // Calculate date range
    const dates = transactions.map(t => new Date(t.transaction_date));
    const earliest = new Date(Math.min(...dates));
    const latest = new Date(Math.max(...dates));
    const rangeText = earliest.toLocaleDateString('en-US', { month: 'short', year: 'numeric' }) +
        ' \u2013 ' + latest.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });

    // Removal reason breakdown for stats
    const removals = transactions.filter(t => t.transaction_type === 'CHECK_OUT');
    const drank = removals.filter(t => t.removal_reason === 'DRINK').reduce((s, t) => s + t.quantity, 0);
    const sold = removals.filter(t => t.removal_reason === 'SELL').reduce((s, t) => s + t.quantity, 0);
    const gifted = removals.filter(t => t.removal_reason === 'GIFT').reduce((s, t) => s + t.quantity, 0);

    container.innerHTML = `
        <div class="history-stat-row">
            <span class="history-stat-label">Period</span>
            <span class="history-stat-value">${rangeText}</span>
        </div>
        <div class="history-stat-row">
            <span class="history-stat-label">Transactions</span>
            <span class="history-stat-value">${totalTransactions}</span>
        </div>
        <div class="history-stat-row">
            <span class="history-stat-label">Bottles added</span>
            <span class="history-stat-value history-stat-added">${totalAdded}</span>
        </div>
        <div class="history-stat-row">
            <span class="history-stat-label">Bottles removed</span>
            <span class="history-stat-value history-stat-removed">${totalRemoved}</span>
        </div>
        ${drank > 0 ? `<div class="history-stat-row"><span class="history-stat-label">Drank</span><span class="history-stat-value">${drank} bottle${drank !== 1 ? 's' : ''}</span></div>` : ''}
        ${sold > 0 ? `<div class="history-stat-row"><span class="history-stat-label">Sold</span><span class="history-stat-value">${sold} bottle${sold !== 1 ? 's' : ''}</span></div>` : ''}
        ${gifted > 0 ? `<div class="history-stat-row"><span class="history-stat-label">Gifted</span><span class="history-stat-value">${gifted} bottle${gifted !== 1 ? 's' : ''}</span></div>` : ''}
    `;
}

// Utilities
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatXWinesPrice(wine) {
    if (wine.price_low_usd && wine.price_high_usd)
        return `$${Math.round(wine.price_low_usd)}\u2013$${Math.round(wine.price_high_usd)}`;
    if (wine.price_tier) return wine.price_tier.replace(/_/g, ' ');
    return '';
}

// ---- Sortable tables ----
// Tracks current sort state per table: { tableId: { column: index, direction: 'asc'|'desc' } }
const _tableSortState = {};

function makeTableSortable(table) {
    /**
     * Make an HTML table sortable by clicking column headers.
     * Sorts the visible tbody rows client-side. Handles text, numbers, and
     * dash-as-empty. Clicking the same column toggles direction; clicking a
     * different column sorts ascending.
     */
    const thead = table.querySelector('thead');
    const tbody = table.querySelector('tbody');
    if (!thead || !tbody) return;

    const headers = thead.querySelectorAll('th');
    const tableId = table.className || 'table';

    headers.forEach((th, colIndex) => {
        // Skip "Actions" columns — not meaningful to sort
        if (th.textContent.trim() === 'Actions') return;

        th.style.cursor = 'pointer';
        th.style.userSelect = 'none';
        th.title = `Sort by ${th.textContent.trim()}`;

        // Add sort indicator span if not present
        if (!th.querySelector('.sort-indicator')) {
            th.insertAdjacentHTML('beforeend', ' <span class="sort-indicator">⇅</span>');
        }

        th.addEventListener('click', () => {
            const state = _tableSortState[tableId] || {};
            let direction = 'asc';
            if (state.column === colIndex) {
                direction = state.direction === 'asc' ? 'desc' : 'asc';
            }
            _tableSortState[tableId] = { column: colIndex, direction };

            // Update indicators: active column shows ▲/▼, others revert to ⇅
            headers.forEach(h => {
                const ind = h.querySelector('.sort-indicator');
                if (ind) {
                    ind.textContent = '⇅';
                    ind.classList.remove('sort-active');
                }
            });
            const indicator = th.querySelector('.sort-indicator');
            if (indicator) {
                indicator.textContent = direction === 'asc' ? '▲' : '▼';
                indicator.classList.add('sort-active');
            }

            // Collect rows (skip detail/expand rows)
            const rows = Array.from(tbody.querySelectorAll('tr'));
            const dataRows = [];
            const detailRows = {};

            rows.forEach(row => {
                if (row.classList.contains('wine-table-detail-row')) {
                    // Attach detail row to its parent data row
                    const forId = row.getAttribute('data-detail-for');
                    if (forId) detailRows[forId] = row;
                } else {
                    dataRows.push(row);
                }
            });

            dataRows.sort((a, b) => {
                const cellA = a.cells[colIndex];
                const cellB = b.cells[colIndex];
                if (!cellA || !cellB) return 0;

                let valA = cellA.textContent.trim();
                let valB = cellB.textContent.trim();

                // Treat '-' and empty as last
                const emptyA = valA === '-' || valA === '';
                const emptyB = valB === '-' || valB === '';
                if (emptyA && emptyB) return 0;
                if (emptyA) return 1;
                if (emptyB) return -1;

                // Strip non-numeric prefixes for price/percentage columns
                const numA = parseFloat(valA.replace(/[^0-9.\-]/g, ''));
                const numB = parseFloat(valB.replace(/[^0-9.\-]/g, ''));

                let cmp;
                if (!isNaN(numA) && !isNaN(numB)) {
                    cmp = numA - numB;
                } else {
                    cmp = valA.localeCompare(valB, undefined, { sensitivity: 'base' });
                }

                return direction === 'asc' ? cmp : -cmp;
            });

            // Re-append rows in sorted order
            tbody.innerHTML = '';
            dataRows.forEach(row => {
                tbody.appendChild(row);
                // Re-attach detail row if it exists
                const wineId = row.getAttribute('data-wine-id');
                if (wineId && detailRows[wineId]) {
                    tbody.appendChild(detailRows[wineId]);
                }
            });
        });
    });
}

function trimOverflowingTags(container) {
    // Remove tags that extend beyond their parent card's visible area
    container.querySelectorAll('.xwines-card').forEach(card => {
        const cardBottom = card.getBoundingClientRect().bottom;
        const footer = card.querySelector('.xwines-card-footer');
        // Tags must fit above the footer
        const cutoff = footer ? footer.getBoundingClientRect().top : cardBottom;
        const tags = card.querySelectorAll('.xwines-card-details .wine-tag');
        tags.forEach(tag => {
            if (tag.getBoundingClientRect().bottom > cutoff) {
                tag.remove();
            }
        });
    });
}

function parsePythonList(str) {
    if (!str) return '';
    try {
        // Try standard JSON first
        const parsed = JSON.parse(str);
        if (Array.isArray(parsed)) return parsed.join(', ');
        return str;
    } catch {
        // Handle Python-style single-quoted lists: ['Beef', 'Veal']
        try {
            const fixed = str.replace(/'/g, '"');
            const parsed = JSON.parse(fixed);
            if (Array.isArray(parsed)) return parsed.join(', ');
        } catch { /* fall through */ }
        return str;
    }
}

function toggleWineDetailLabelText(header) {
    const section = header.parentElement;
    const content = section.querySelector('.collapsible-content');
    const icon = header.querySelector('.collapse-icon');
    const label = header.querySelector('.label');

    section.classList.toggle('open');
    if (section.classList.contains('open')) {
        content.style.display = 'block';
        icon.textContent = '-';
        label.textContent = 'Hide Raw Label Text';
    } else {
        content.style.display = 'none';
        icon.textContent = '+';
        label.textContent = 'Show Raw Label Text';
    }
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.remove();
    }, 5000);
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Settings
function loadSettings() {
    // Clear password form
    document.getElementById('password-form').reset();
}

async function handlePasswordChange(e) {
    e.preventDefault();

    const currentPassword = document.getElementById('current-password').value;
    const newPassword = document.getElementById('new-password').value;
    const confirmPassword = document.getElementById('confirm-password').value;

    if (newPassword !== confirmPassword) {
        showToast('New passwords do not match', 'error');
        return;
    }

    if (newPassword.length < 6) {
        showToast('Password must be at least 6 characters', 'error');
        return;
    }

    try {
        const response = await fetchWithAuth(`${API_BASE}/auth/password`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                current_password: currentPassword,
                new_password: newPassword
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to change password');
        }

        document.getElementById('password-form').reset();
        showToast('Password changed successfully', 'success');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function handleDeleteCollection() {
    const input = document.getElementById('delete-confirm-input');
    if (input.value !== 'DELETE') return;

    const btn = document.getElementById('confirm-delete-collection-btn');
    btn.disabled = true;
    btn.textContent = 'Deleting...';

    try {
        const response = await fetchWithAuth(`${API_BASE}/wines/all`, {
            method: 'DELETE',
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to delete collection');
        }

        const result = await response.json();
        closeModals();
        showToast(`Deleted ${result.deleted_wines} wines, ${result.deleted_transactions} transactions`, 'success');
        loadCellar();
        resetImportPage();
    } catch (error) {
        btn.disabled = false;
        btn.textContent = 'Delete Everything';
        showToast(error.message, 'error');
    }
}

// Export Dropdowns
function initExportDropdowns() {
    // Initialize history export dropdown
    initExportDropdown('history-export-dropdown', 'history-export-btn');

    // Initialize X-Wines export dropdown
    initExportDropdown('xwines-export-dropdown', 'xwines-export-btn');

    // Close dropdowns when clicking outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.export-dropdown')) {
            document.querySelectorAll('.export-dropdown.active').forEach(dropdown => {
                dropdown.classList.remove('active');
            });
        }
    });
}

function initExportDropdown(dropdownId, buttonId) {
    const dropdown = document.getElementById(dropdownId);
    const button = document.getElementById(buttonId);

    if (!dropdown || !button) return;

    // Toggle dropdown on button click
    button.addEventListener('click', (e) => {
        e.stopPropagation();
        // Close other dropdowns
        document.querySelectorAll('.export-dropdown.active').forEach(other => {
            if (other !== dropdown) other.classList.remove('active');
        });
        dropdown.classList.toggle('active');
    });

    // Handle format selection
    dropdown.querySelectorAll('.export-dropdown-menu a').forEach(link => {
        link.addEventListener('click', async (e) => {
            e.preventDefault();
            const format = link.dataset.format;
            const type = link.dataset.type;

            dropdown.classList.remove('active');
            await handleExport(type, format);
        });
    });
}

async function handleExport(type, format) {
    // Build export URL with current filters
    let url;

    if (type === 'xwines') {
        // X-Wines uses a different endpoint
        if (!xwinesLastSearchParams || !xwinesLastSearchParams.q) {
            showToast('Please perform a search first', 'error');
            return;
        }
        url = `${API_BASE}/xwines/export?format=${format}&q=${encodeURIComponent(xwinesLastSearchParams.q)}`;
        if (xwinesLastSearchParams.wine_type) {
            url += `&wine_type=${encodeURIComponent(xwinesLastSearchParams.wine_type)}`;
        }
        if (xwinesLastSearchParams.country) {
            url += `&country=${encodeURIComponent(xwinesLastSearchParams.country)}`;
        }
    } else {
        url = `${API_BASE}/export/${type}?format=${format}`;

        // Add relevant filters based on export type
        if (type === 'wines') {
            const cellarFilter = document.getElementById('cellar-filter')?.value;
            if (cellarFilter === 'in-stock') {
                url += '&in_stock=true';
            } else if (cellarFilter === 'out-of-stock') {
                url += '&in_stock=false';
            }
        } else if (type === 'transactions') {
            const historyFilter = document.getElementById('history-filter')?.value;
            if (historyFilter === 'CHECK_IN' || historyFilter === 'CHECK_OUT') {
                url += `&transaction_type=${historyFilter}`;
            } else if (historyFilter === 'DRINK' || historyFilter === 'SELL' || historyFilter === 'GIFT' || historyFilter === 'OTHER') {
                url += `&transaction_type=CHECK_OUT&removal_reason=${historyFilter}`;
            }
        }
    }

    try {
        showToast('Preparing export...', 'info');

        const response = await fetchWithAuth(url);

        if (!response.ok) {
            throw new Error('Export failed');
        }

        // Get filename from Content-Disposition header
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = `winebox_${type}.${format}`;
        if (contentDisposition) {
            const match = contentDisposition.match(/filename=([^;]+)/);
            if (match) {
                filename = match[1].trim();
            }
        }

        // Handle different formats
        if (format === 'json') {
            // JSON is returned as response body
            const data = await response.json();
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            downloadBlob(blob, filename);
        } else {
            // Binary formats (CSV, XLSX, YAML)
            const blob = await response.blob();
            downloadBlob(blob, filename);
        }

        showToast(`Exported ${type} as ${format.toUpperCase()}`, 'success');
    } catch (error) {
        console.error('Export error:', error);
        showToast(`Export failed: ${error.message}`, 'error');
    }
}

function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

// X-Wines Search
let xwinesFiltersLoaded = false;
let xwinesCurrentPage = 1;
let xwinesTotal = 0;
let xwinesLastSearchParams = null;
let xwinesLastResults = [];
let xwinesViewMode = 'cards';

function initXWinesPage() {
    // Pagination button handlers
    document.getElementById('xwines-prev')?.addEventListener('click', () => goToXWinesPage('prev'));
    document.getElementById('xwines-next')?.addEventListener('click', () => goToXWinesPage('next'));

    // View toggle handlers
    document.getElementById('xwines-view-cards')?.addEventListener('click', () => setXWinesViewMode('cards'));
    document.getElementById('xwines-view-table')?.addEventListener('click', () => setXWinesViewMode('table'));
}

async function loadXWinesFilters() {
    if (xwinesFiltersLoaded) return;

    const typeSelect = document.getElementById('xwines-type');
    const countrySelect = document.getElementById('xwines-country');

    // Show loading state while fetching filters
    typeSelect.disabled = true;
    countrySelect.disabled = true;
    typeSelect.options[0].textContent = 'Loading\u2026';
    countrySelect.options[0].textContent = 'Loading\u2026';

    try {
        const [typesRes, countriesRes] = await Promise.all([
            fetchWithAuth(`${API_BASE}/xwines/types`),
            fetchWithAuth(`${API_BASE}/xwines/countries`)
        ]);

        if (typesRes.ok) {
            const types = await typesRes.json();
            types.forEach(t => {
                const opt = document.createElement('option');
                opt.value = t;
                opt.textContent = t;
                typeSelect.appendChild(opt);
            });
        }

        if (countriesRes.ok) {
            const countries = await countriesRes.json();
            countries.forEach(c => {
                const opt = document.createElement('option');
                opt.value = c.code;
                opt.textContent = `${c.name} (${c.count})`;
                countrySelect.appendChild(opt);
            });
        }

        xwinesFiltersLoaded = true;
    } catch (error) {
        console.error('Failed to load X-Wines filters:', error);
    } finally {
        // Restore default labels and re-enable
        typeSelect.options[0].textContent = 'All Types';
        countrySelect.options[0].textContent = 'All Countries';
        typeSelect.disabled = false;
        countrySelect.disabled = false;
    }
}

async function handleXWinesSearch(e) {
    e.preventDefault();
    // Reset pagination when performing new search
    xwinesCurrentPage = 1;
    await performXWinesSearch();
}

async function performXWinesSearch() {
    const params = new URLSearchParams();
    const q = document.getElementById('xwines-q').value.trim();
    if (q && q.length < 2) {
        showToast('Please enter at least 2 characters', 'error');
        return;
    }
    if (q) params.append('q', q);

    const wineType = document.getElementById('xwines-type').value;
    if (wineType) params.append('wine_type', wineType);

    const country = document.getElementById('xwines-country').value;
    if (country) params.append('country', country);

    const priceMin = document.getElementById('xwines-price-min').value;
    const priceMax = document.getElementById('xwines-price-max').value;

    // Validate price range
    if (priceMin && priceMax && parseFloat(priceMin) > parseFloat(priceMax)) {
        showToast('Minimum price cannot exceed maximum price', 'error');
        return;
    }

    if (priceMin) params.append('price_min', priceMin);
    if (priceMax) params.append('price_max', priceMax);

    // Require at least one search criterion
    if (!q && !wineType && !country && !priceMin && !priceMax) {
        showToast('Please enter a search term or select a filter', 'error');
        return;
    }

    const limit = parseInt(document.getElementById('xwines-limit').value);
    params.append('limit', limit);

    // Calculate skip for pagination
    const skip = (xwinesCurrentPage - 1) * limit;
    params.append('skip', skip);

    // Store search params for pagination and export
    xwinesLastSearchParams = {
        q: q,
        wine_type: wineType || null,
        country: country || null,
        price_min: priceMin || null,
        price_max: priceMax || null,
        limit: limit
    };

    try {
        const response = await fetchWithAuth(`${API_BASE}/xwines/search?${params}`);
        if (!response.ok) throw new Error('Search failed');
        const data = await response.json();

        // Store results and total for view switching
        xwinesLastResults = data.results;
        xwinesTotal = data.total;

        // Render based on current view mode
        renderXWinesResults();

        // Update pagination controls
        renderXWinesPagination(data.total, data.skip, data.limit);

        // Show toolbar if we have results
        const toolbar = document.getElementById('xwines-toolbar');
        toolbar.style.display = data.results.length > 0 ? 'flex' : 'none';

        // Update filter dropdowns with facet counts if available
        if (data.facets) {
            updateFilterCounts(data.facets);
        }
    } catch (error) {
        showToast('X-Wines search failed', 'error');
    }
}

function renderXWinesResults() {
    if (xwinesViewMode === 'table') {
        renderXWinesTable('xwines-results', xwinesLastResults, xwinesTotal);
    } else {
        renderXWinesGrid('xwines-results', xwinesLastResults, xwinesTotal);
    }
}

function renderXWinesPagination(total, skip, limit) {
    const paginationEl = document.getElementById('xwines-pagination');
    const pageInfoEl = document.getElementById('xwines-page-info');
    const prevBtn = document.getElementById('xwines-prev');
    const nextBtn = document.getElementById('xwines-next');

    const totalPages = Math.ceil(total / limit);
    const currentPage = Math.floor(skip / limit) + 1;

    if (totalPages <= 1) {
        paginationEl.style.display = 'none';
        return;
    }

    paginationEl.style.display = 'flex';
    pageInfoEl.textContent = `Page ${currentPage} of ${totalPages}`;

    prevBtn.disabled = currentPage <= 1;
    nextBtn.disabled = currentPage >= totalPages;
}

async function goToXWinesPage(direction) {
    const limit = parseInt(document.getElementById('xwines-limit').value);
    const totalPages = Math.ceil(xwinesTotal / limit);

    if (direction === 'prev' && xwinesCurrentPage > 1) {
        xwinesCurrentPage--;
    } else if (direction === 'next' && xwinesCurrentPage < totalPages) {
        xwinesCurrentPage++;
    }

    await performXWinesSearch();
}

function setXWinesViewMode(mode) {
    xwinesViewMode = mode;

    // Update button states
    document.getElementById('xwines-view-cards').classList.toggle('active', mode === 'cards');
    document.getElementById('xwines-view-table').classList.toggle('active', mode === 'table');

    // Toggle wine-grid class: cards need the grid layout, table needs full width
    const resultsContainer = document.getElementById('xwines-results');
    if (mode === 'table') {
        resultsContainer.classList.remove('wine-grid');
    } else {
        resultsContainer.classList.add('wine-grid');
    }

    // Re-render with current results
    if (xwinesLastResults.length > 0) {
        renderXWinesResults();
    }
}

function renderXWinesTable(containerId, results, total) {
    const container = document.getElementById(containerId);
    if (!results || results.length === 0) {
        container.innerHTML = '<div class="empty-state"><h3>No wines found</h3><p>Try a different search term or adjust filters</p></div>';
        return;
    }

    const header = total > results.length
        ? `<div class="xwines-results-header">Showing ${results.length} of ${total} results</div>`
        : `<div class="xwines-results-header">${results.length} result${results.length !== 1 ? 's' : ''}</div>`;

    const tableRows = results.map(wine => {
        const ratingDisplay = wine.avg_rating
            ? `${wine.avg_rating.toFixed(1)} (${wine.rating_count.toLocaleString()} ratings)`
            : '-';
        const priceDisplay = formatXWinesPrice(wine);

        return `
            <tr class="xwines-table-row" data-xwine-id="${wine.id}">
                <td class="xwines-table-name">${escapeHtml(wine.name)}</td>
                <td>${wine.winery ? escapeHtml(wine.winery) : '-'}</td>
                <td>${wine.wine_type ? `<span class="xwines-type-tag xwines-type-${wine.wine_type.toLowerCase().replace(/[éè]/g, 'e')}">${escapeHtml(wine.wine_type)}</span>` : '-'}</td>
                <td>${wine.country ? escapeHtml(wine.country) : '-'}</td>
                <td>${wine.region ? escapeHtml(wine.region) : '-'}</td>
                <td>${wine.abv ? `${wine.abv}%` : '-'}</td>
                <td class="xwines-table-rating">${ratingDisplay}</td>
                <td class="xwines-table-price">${priceDisplay || '-'}</td>
            </tr>
        `;
    }).join('');

    container.innerHTML = `
        ${header}
        <div class="xwines-table-wrapper">
            <table class="xwines-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Winery</th>
                        <th>Type</th>
                        <th>Country</th>
                        <th>Region</th>
                        <th>ABV</th>
                        <th>Rating</th>
                        <th>Price</th>
                    </tr>
                </thead>
                <tbody>
                    ${tableRows}
                </tbody>
            </table>
        </div>
    `;

    // Add click handlers for table rows
    container.querySelectorAll('.xwines-table-row').forEach(row => {
        row.addEventListener('click', () => {
            showXWinesDetail(row.dataset.xwineId);
        });
    });

    // Make table sortable by column headers
    const xwinesTable = container.querySelector('.xwines-table');
    if (xwinesTable) makeTableSortable(xwinesTable);
}

function updateFilterCounts(facets) {
    // Update wine type dropdown with facet counts
    if (facets.wine_type && facets.wine_type.length > 0) {
        const typeSelect = document.getElementById('xwines-type');
        const countMap = {};
        facets.wine_type.forEach(b => { countMap[b.value] = b.count; });

        Array.from(typeSelect.options).forEach(opt => {
            if (!opt.value) return; // skip "All Types" placeholder
            const count = countMap[opt.value];
            // Strip any existing count suffix before adding new one
            const baseLabel = opt.textContent.replace(/\s*\(\d[\d,]*\)$/, '');
            opt.textContent = count !== undefined ? `${baseLabel} (${count.toLocaleString()})` : baseLabel;
        });
    }

    // Update country dropdown with facet counts
    if (facets.country && facets.country.length > 0) {
        const countrySelect = document.getElementById('xwines-country');
        const countMap = {};
        facets.country.forEach(b => { countMap[b.value] = b.count; });

        Array.from(countrySelect.options).forEach(opt => {
            if (!opt.value) return; // skip "All Countries" placeholder
            // Country options show "Name (count)" — update the count portion
            const baseLabel = opt.textContent.replace(/\s*\(\d[\d,]*\)$/, '');
            const count = countMap[baseLabel];
            opt.textContent = count !== undefined ? `${baseLabel} (${count.toLocaleString()})` : baseLabel;
        });
    }
}

function renderXWinesGrid(containerId, results, total) {
    const container = document.getElementById(containerId);
    if (!results || results.length === 0) {
        container.innerHTML = '<div class="empty-state"><h3>No wines found</h3><p>Try a different search term or adjust filters</p></div>';
        return;
    }

    const header = total > results.length
        ? `<div class="xwines-results-header">Showing ${results.length} of ${total} results</div>`
        : `<div class="xwines-results-header">${results.length} result${results.length !== 1 ? 's' : ''}</div>`;

    container.innerHTML = header + results.map(wine => {
        const starsDisplay = wine.avg_rating
            ? `<span class="xwines-rating">${'★'.repeat(Math.round(wine.avg_rating))}${'☆'.repeat(5 - Math.round(wine.avg_rating))} ${wine.avg_rating.toFixed(1)}</span>`
            : '';

        return `
            <div class="xwines-card" data-xwine-id="${wine.id}">
                <div class="xwines-card-header">
                    ${wine.wine_type ? `<span class="xwines-type-tag xwines-type-${wine.wine_type.toLowerCase().replace(/[éè]/g, 'e')}">${escapeHtml(wine.wine_type)}</span>` : ''}
                </div>
                <div class="xwines-card-content">
                    <div class="xwines-card-title">${escapeHtml(wine.name)}</div>
                    <div class="xwines-card-subtitle">${wine.winery ? escapeHtml(wine.winery) : ''}</div>
                    <div class="xwines-card-details">
                        ${wine.country ? `<span class="wine-tag">${escapeHtml(wine.country)}</span>` : ''}
                        ${wine.region ? `<span class="wine-tag">${escapeHtml(wine.region)}</span>` : ''}
                        ${wine.abv ? `<span class="wine-tag">${wine.abv}% ABV</span>` : ''}
                    </div>
                </div>
                <div class="xwines-card-footer">
                    ${starsDisplay}
                    ${formatXWinesPrice(wine) ? `<span class="xwines-price-tag">${formatXWinesPrice(wine)}</span>` : ''}
                </div>
            </div>
        `;
    }).join('');

    container.querySelectorAll('.xwines-card').forEach(card => {
        card.addEventListener('click', () => {
            showXWinesDetail(card.dataset.xwineId);
        });
    });

    // Remove tags that overflow beyond 2 rows
    // Defer until browser has fully laid out the new elements (double-rAF)
    requestAnimationFrame(() => requestAnimationFrame(() => trimOverflowingTags(container)));
}

async function showXWinesDetail(wineId) {
    try {
        const response = await fetchWithAuth(`${API_BASE}/xwines/wines/${wineId}`);
        if (!response.ok) throw new Error('Failed to load wine details');
        const wine = await response.json();

        let grapes = '';
        if (wine.grapes) {
            grapes = parsePythonList(wine.grapes);
        }

        let harmonize = '';
        if (wine.harmonize) {
            harmonize = parsePythonList(wine.harmonize);
        }

        let vintages = '';
        if (wine.vintages) {
            try {
                const parsed = JSON.parse(wine.vintages);
                vintages = Array.isArray(parsed) ? parsed.join(', ') : wine.vintages;
            } catch {
                vintages = wine.vintages;
            }
        }

        const ratingDisplay = wine.avg_rating
            ? `${'★'.repeat(Math.round(wine.avg_rating))}${'☆'.repeat(5 - Math.round(wine.avg_rating))} ${wine.avg_rating.toFixed(1)} (${wine.rating_count} ratings)`
            : 'No ratings';

        document.getElementById('xwines-detail').innerHTML = `
            <div class="xwines-detail-layout">
                <div class="xwines-detail-header">
                    <h3>${escapeHtml(wine.name)}</h3>
                    ${wine.winery_name ? `<div class="xwines-detail-winery">${escapeHtml(wine.winery_name)}</div>` : ''}
                    ${wine.wine_type ? `<span class="xwines-type-tag xwines-type-${wine.wine_type.toLowerCase().replace(/[éè]/g, 'e')}">${escapeHtml(wine.wine_type)}</span>` : ''}
                    ${wine.elaborate ? `<span class="wine-tag">${escapeHtml(wine.elaborate)}</span>` : ''}
                </div>

                <div class="xwines-detail-rating">
                    <div class="xwines-detail-stars">${ratingDisplay}</div>
                    ${formatXWinesPrice(wine) ? `<div class="xwines-detail-price">${formatXWinesPrice(wine)}</div>` : ''}
                </div>

                <div class="xwines-detail-fields">
                    ${wine.country ? `
                        <div class="wine-detail-field">
                            <div class="label">Country</div>
                            <div class="value">${escapeHtml(wine.country)}</div>
                        </div>
                    ` : ''}
                    ${wine.region_name ? `
                        <div class="wine-detail-field">
                            <div class="label">Region</div>
                            <div class="value">${escapeHtml(wine.region_name)}</div>
                        </div>
                    ` : ''}
                    ${wine.abv ? `
                        <div class="wine-detail-field">
                            <div class="label">ABV</div>
                            <div class="value">${wine.abv}%</div>
                        </div>
                    ` : ''}
                    ${wine.body ? `
                        <div class="wine-detail-field">
                            <div class="label">Body</div>
                            <div class="value">${escapeHtml(wine.body)}</div>
                        </div>
                    ` : ''}
                    ${wine.acidity ? `
                        <div class="wine-detail-field">
                            <div class="label">Acidity</div>
                            <div class="value">${escapeHtml(wine.acidity)}</div>
                        </div>
                    ` : ''}
                    ${grapes ? `
                        <div class="wine-detail-field">
                            <div class="label">Grapes</div>
                            <div class="value">${escapeHtml(grapes)}</div>
                        </div>
                    ` : ''}
                    ${harmonize ? `
                        <div class="wine-detail-field">
                            <div class="label">Food Pairings</div>
                            <div class="value">${escapeHtml(harmonize)}</div>
                        </div>
                    ` : ''}
                    ${vintages ? `
                        <div class="wine-detail-field">
                            <div class="label">Vintages</div>
                            <div class="value">${escapeHtml(vintages)}</div>
                        </div>
                    ` : ''}
                    ${wine.website ? `
                        <div class="wine-detail-field">
                            <div class="label">Website</div>
                            <div class="value"><a href="${escapeHtml(wine.website)}" target="_blank" rel="noopener">${escapeHtml(wine.website)}</a></div>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;

        openModal('xwines-modal');
    } catch (error) {
        showToast('Failed to load wine details', 'error');
    }
}

// =============================================================================
// CUSTOM FIELDS
// =============================================================================

function initCustomFields() {
    const addBtn = document.getElementById('add-custom-field-btn');
    if (addBtn) {
        addBtn.addEventListener('click', () => {
            addCustomFieldRow(document.getElementById('custom-fields-container'));
        });
    }

    const confirmAddBtn = document.getElementById('confirm-add-custom-field-btn');
    if (confirmAddBtn) {
        confirmAddBtn.addEventListener('click', () => {
            addCustomFieldRow(document.getElementById('confirm-custom-fields-container'));
        });
    }
}

function addCustomFieldRow(container, name, value) {
    const row = document.createElement('div');
    row.className = 'custom-field-row';
    row.innerHTML = `
        <input type="text" class="custom-field-name" placeholder="Field name" value="${escapeHtml(name || '')}">
        <input type="text" class="custom-field-value" placeholder="Value" value="${escapeHtml(value || '')}">
        <button type="button" class="btn btn-small btn-danger custom-field-remove">&times;</button>
    `;
    row.querySelector('.custom-field-remove').addEventListener('click', () => row.remove());
    container.appendChild(row);
}

function collectCustomFields(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return null;
    const fields = {};
    container.querySelectorAll('.custom-field-row').forEach(row => {
        const name = row.querySelector('.custom-field-name').value.trim();
        const value = row.querySelector('.custom-field-value').value.trim();
        if (name && value) {
            fields[name] = value;
        }
    });
    return Object.keys(fields).length > 0 ? fields : null;
}

// =============================================================================
// IMPORT PAGE
// =============================================================================

let currentImportBatchId = null;
let currentImportData = null;
let pendingCsvRows = null;
let isUploadingRows = false;
let pendingCsvFile = null;  // Original file reference for checksum

function initImportPage() {
    const fileInput = document.getElementById('import-file-input');
    const dropZone = document.getElementById('import-drop-zone');

    if (!fileInput || !dropZone) return;

    fileInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files[0]) {
            handleImportFileSelect(e.target.files[0]);
        }
    });

    // Drag and drop
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('drag-over');
    });
    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('drag-over');
    });
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('drag-over');
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            handleImportFileSelect(e.dataTransfer.files[0]);
        }
    });

    // Buttons
    document.getElementById('import-confirm-mapping-btn').addEventListener('click', handleConfirmMapping);
    document.getElementById('import-back-to-upload-btn').addEventListener('click', resetImportPage);
    document.getElementById('import-use-different-file-btn').addEventListener('click', resetImportPage);
    document.getElementById('import-new-btn').addEventListener('click', resetImportPage);

    // Go to Cellar buttons (CSP-compliant) — navigate to Import sub-tab
    document.querySelectorAll('.import-go-to-cellar-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            currentCellarTab = 'import';
            navigateTo('cellar');
            // Also refresh dashboard analytics in background
            loadCellarAnalytics();
        });
    });

    // Case size prompt buttons
    document.querySelectorAll('.case-size-option').forEach(btn => {
        btn.addEventListener('click', () => {
            importDefaultCaseSize = parseInt(btn.dataset.size);
            document.querySelectorAll('.case-size-option').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            updateImportSummary();
        });
    });
    document.getElementById('import-custom-case-size-btn')?.addEventListener('click', () => {
        const val = parseInt(document.getElementById('import-custom-case-size').value);
        if (val > 0 && val <= 100) {
            importDefaultCaseSize = val;
            document.querySelectorAll('.case-size-option').forEach(b => b.classList.remove('active'));
            updateImportSummary();
        }
    });

    // Duplicate step buttons
    document.getElementById('import-duplicate-augment-btn')?.addEventListener('click', handleDuplicateAugment);
    document.getElementById('import-duplicate-reimport-btn')?.addEventListener('click', handleDuplicateReimport);
    document.getElementById('import-duplicate-cancel-btn')?.addEventListener('click', resetImportPage);

    // Augment step buttons
    document.getElementById('import-augment-confirm-btn')?.addEventListener('click', handleAugmentConfirm);
    document.getElementById('import-augment-cancel-btn')?.addEventListener('click', handleAugmentSkip);

    // Dashboard buttons
    document.getElementById('import-dashboard-new-btn')?.addEventListener('click', resetImportPage);
    document.getElementById('import-undo-btn')?.addEventListener('click', handleUndoImport);

    // Incomplete batch buttons
    document.getElementById('import-incomplete-undo-btn')?.addEventListener('click', handleIncompleteUndo);
    document.getElementById('import-incomplete-dismiss-btn')?.addEventListener('click', () => {
        document.getElementById('import-incomplete-notice').style.display = 'none';
    });

    // Check for incomplete batches on page load
    checkIncompleteBatches();

    // Warn before navigating away during row upload
    window.addEventListener('beforeunload', (e) => {
        if (isUploadingRows) {
            e.preventDefault();
        }
    });
}

async function handleImportFileSelect(file) {
    const ext = file.name.split('.').pop().toLowerCase();
    if (!['csv', 'xlsx'].includes(ext)) {
        showToast('Please select a CSV or XLSX file', 'error');
        return;
    }

    if (ext === 'csv') {
        await handleCsvImport(file);
    } else {
        await handleXlsxImport(file);
    }
}

/**
 * Compute SHA-256 hash of a File using the Web Crypto API.
 */
async function computeFileChecksum(file) {
    const buffer = await file.arrayBuffer();
    const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Parse CSV client-side with PapaParse streaming, then upload metadata to server.
 */
async function handleCsvImport(file) {
    try {
        showToast('Parsing CSV...', 'info');

        // Parse and compute checksum concurrently
        const [parsed, fileChecksum] = await Promise.all([
            parseCsvFile(file),
            computeFileChecksum(file),
        ]);

        if (parsed.errors.length > 0) {
            showToast(`CSV parse error: ${parsed.errors[0].message}`, 'error');
            return;
        }

        if (parsed.rows.length === 0) {
            showToast('CSV file has no data rows', 'error');
            return;
        }

        if (parsed.rows.length > 10000) {
            showToast('CSV exceeds maximum of 10,000 rows', 'error');
            return;
        }

        // Store rows for later upload after mapping
        pendingCsvRows = parsed.rows;
        pendingCsvFile = file;

        const useAiCheckbox = document.getElementById('import-use-ai-mapping');
        const useAiMapping = !useAiCheckbox || useAiCheckbox.checked;

        // Send headers + preview to server for mapping suggestion
        const response = await fetchWithAuth(`${API_BASE}/import/upload-parsed`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                filename: file.name,
                headers: parsed.headers,
                preview_rows: parsed.rows.slice(0, 5),
                row_count: parsed.rows.length,
                use_ai_mapping: useAiMapping,
                file_checksum: fileChecksum,
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Upload failed');
        }

        const data = await response.json();
        currentImportBatchId = data.batch_id;
        currentImportData = data;

        // Route based on duplicate/confidence/force-mapping
        routeAfterUpload(data);
    } catch (error) {
        showToast(error.message, 'error');
    }
}

/**
 * Upload XLSX file to server for server-side parsing (existing flow).
 */
async function handleXlsxImport(file) {
    const useAiCheckbox = document.getElementById('import-use-ai-mapping');
    const useAiMapping = !useAiCheckbox || useAiCheckbox.checked;
    const query = useAiMapping ? '' : '?use_ai_mapping=false';

    const formData = new FormData();
    formData.append('file', file);

    try {
        showToast('Uploading and parsing...', 'info');
        const response = await fetchWithAuth(`${API_BASE}/import/upload${query}`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Upload failed');
        }

        const data = await response.json();
        currentImportBatchId = data.batch_id;
        currentImportData = data;

        // Route based on duplicate/confidence/force-mapping
        routeAfterUpload(data);
    } catch (error) {
        showToast(error.message, 'error');
    }
}

/**
 * Parse a CSV file using PapaParse streaming mode.
 * Reads the file from disk in ~64 KB chunks (never loads entire file into memory).
 * Returns {headers, rows, errors}.
 */
function parseCsvFile(file) {
    return new Promise((resolve) => {
        const rows = [];
        let headers = null;
        const errors = [];

        Papa.parse(file, {
            header: true,
            skipEmptyLines: true,
            chunkSize: 64 * 1024,
            chunk: function(results) {
                if (!headers && results.meta.fields) {
                    headers = results.meta.fields;
                }
                for (const row of results.data) {
                    // Filter empty rows (all values blank)
                    const hasData = Object.values(row).some(v => v !== null && v !== undefined && String(v).trim() !== '');
                    if (hasData) {
                        rows.push(row);
                    }
                }
                if (results.errors.length > 0) {
                    errors.push(...results.errors);
                }
            },
            complete: function() {
                resolve({ headers: headers || [], rows, errors });
            },
            error: function(err) {
                resolve({ headers: headers || [], rows, errors: [err] });
            }
        });
    });
}

/**
 * Upload parsed rows to server in 500-row chunks.
 * First chunk uses ?clear=true for safe retry semantics.
 */
async function uploadRowChunks(batchId, rows) {
    const CHUNK_SIZE = 500;
    const total = rows.length;
    isUploadingRows = true;

    try {
        for (let i = 0; i < total; i += CHUNK_SIZE) {
            const chunk = rows.slice(i, i + CHUNK_SIZE);
            const isFirstChunk = (i === 0);
            const url = `${API_BASE}/import/${batchId}/rows${isFirstChunk ? '?clear=true' : ''}`;

            const response = await fetchWithAuth(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ rows: chunk })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to upload rows');
            }

            // Update progress bar during upload phase
            const uploaded = Math.min(i + CHUNK_SIZE, total);
            const pct = Math.round((uploaded / total) * 100);
            document.getElementById('import-progress-fill').style.width = pct + '%';
            document.getElementById('import-progress-text').textContent = `Uploading rows: ${uploaded} / ${total}`;
            document.getElementById('import-progress-percent').textContent = pct + '%';
        }
    } finally {
        isUploadingRows = false;
    }
}

/**
 * Route the user after upload based on duplicate detection, confidence, and settings.
 */
function routeAfterUpload(data) {
    const forceMapping = document.getElementById('import-force-mapping');
    const forceMappingChecked = forceMapping && forceMapping.checked;

    // Check for duplicate first
    if (data.duplicate_of) {
        showDuplicateScreen(data);
        return;
    }

    // Auto-import if eligible and user hasn't forced mapping
    if (data.auto_import_eligible && !forceMappingChecked) {
        handleAutoImport(data);
        return;
    }

    // Fall through to existing mapping UI
    renderMappingStep(data);
}

/**
 * Handle auto-import: silently set mapping, upload rows, process, then show dashboard.
 */
async function handleAutoImport(data) {
    try {
        // Show progress immediately
        _showImportStep('progress');

        // Reset progress UI
        document.getElementById('import-progress-fill').style.width = '0%';
        document.getElementById('import-progress-text').textContent = 'Auto-importing...';
        document.getElementById('import-progress-percent').textContent = '';
        document.getElementById('import-progress-created').textContent = '';
        document.getElementById('import-progress-skipped').textContent = '';

        // Set the suggested mapping directly
        const mapResponse = await fetchWithAuth(`${API_BASE}/import/${currentImportBatchId}/mapping`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mapping: data.suggested_mapping })
        });

        if (!mapResponse.ok) {
            const error = await mapResponse.json();
            throw new Error(error.detail || 'Failed to set mapping');
        }

        // If client-parsed CSV, upload rows in chunks
        if (pendingCsvRows) {
            await uploadRowChunks(currentImportBatchId, pendingCsvRows);
            pendingCsvRows = null;
        }

        // Reset progress for processing phase
        document.getElementById('import-progress-fill').style.width = '0%';
        document.getElementById('import-progress-text').textContent = '0 / 0 rows';
        document.getElementById('import-progress-percent').textContent = '0%';

        // Stream processing
        const processResponse = await fetchWithAuth(`${API_BASE}/import/${currentImportBatchId}/process-stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ skip_non_wine: true, default_quantity: 1, skip_enrichment: true, default_case_size: importDefaultCaseSize })
        });

        if (!processResponse.ok) {
            const error = await processResponse.json();
            throw new Error(error.detail || 'Processing failed');
        }

        const result = await readImportStream(processResponse);

        // Navigate to import dashboard (enrichment countdown handled there)
        showImportDashboard(currentImportBatchId, data.filename, result);
    } catch (error) {
        showToast(error.message, 'error');
        // Fall back to mapping step on error
        renderMappingStep(data);
    }
}

/**
 * Show the duplicate detection screen.
 */
function showDuplicateScreen(data) {
    _showImportStep('duplicate');

    let html = `<p style="font-size:1.05rem;margin-bottom:1rem;">
        This file was imported before as <strong>${escapeHtml(data.duplicate_filename || data.filename)}</strong>
        with <strong>${data.duplicate_wines_created} wines</strong> added to your cellar.</p>`;

    // Show the mapping that was used
    if (data.duplicate_mapping) {
        html += '<h4 style="margin-bottom:0.5rem;">Columns that were imported:</h4><ul style="margin-bottom:1rem;">';
        for (const [header, field] of Object.entries(data.duplicate_mapping)) {
            if (field !== 'skip' && !field.startsWith('custom:')) {
                html += `<li><strong>${escapeHtml(header)}</strong> &rarr; ${escapeHtml(field)}</li>`;
            }
        }
        html += '</ul>';
    }

    // Highlight unmapped columns
    if (data.duplicate_unmapped_headers && data.duplicate_unmapped_headers.length > 0) {
        html += '<h4 style="margin-bottom:0.5rem;color:var(--primary-color);">Columns that were not imported:</h4><ul>';
        for (const header of data.duplicate_unmapped_headers) {
            html += `<li>${escapeHtml(header)}</li>`;
        }
        html += '</ul>';
    }

    document.getElementById('import-duplicate-content').innerHTML = html;

    // Show/hide augment button based on unmapped headers
    const augmentBtn = document.getElementById('import-duplicate-augment-btn');
    if (augmentBtn) {
        augmentBtn.style.display = (data.duplicate_unmapped_headers && data.duplicate_unmapped_headers.length > 0) ? '' : 'none';
    }
}

/**
 * Handle "Add more details" from duplicate screen — show augment UI for the original batch.
 */
async function handleDuplicateAugment() {
    if (!currentImportData || !currentImportData.duplicate_of) return;
    showAugmentUI(currentImportData.duplicate_of);
}

/**
 * Handle "Import again anyway" from duplicate screen.
 */
function handleDuplicateReimport() {
    if (!currentImportData) return;

    // Check if auto-import eligible
    const forceMapping = document.getElementById('import-force-mapping');
    const forceMappingChecked = forceMapping && forceMapping.checked;

    if (currentImportData.auto_import_eligible && !forceMappingChecked) {
        handleAutoImport(currentImportData);
    } else {
        renderMappingStep(currentImportData);
    }
}

/**
 * Show the augment UI for unmapped columns of a completed batch.
 */
async function showAugmentUI(batchId) {
    try {
        const response = await fetchWithAuth(`${API_BASE}/import/${batchId}/unmapped-columns`);
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to fetch unmapped columns');
        }

        const data = await response.json();
        if (data.unmapped_headers.length === 0) {
            showToast('No unmapped columns to add', 'info');
            return;
        }

        _showImportStep('augment');

        // Store batch ID for the confirm handler
        document.getElementById('import-step-augment').dataset.batchId = batchId;

        // Field metadata (same as mapping step)
        const IMPORT_FIELD_META = {
            name:                { label: 'Wine Name', group: 'basics' },
            winery:              { label: 'Winery / Producer', group: 'basics' },
            vintage:             { label: 'Vintage Year', group: 'basics' },
            grape_variety:       { label: 'Grape', group: 'basics' },
            country:             { label: 'Country', group: 'basics' },
            region:              { label: 'Region', group: 'basics' },
            sub_region:          { label: 'Sub-Region', group: 'details' },
            appellation:         { label: 'Appellation', group: 'details' },
            wine_type_id:        { label: 'Wine Style', group: 'details' },
            classification:      { label: 'Classification', group: 'details' },
            alcohol_percentage:  { label: 'Alcohol (ABV)', group: 'details' },
            price_tier:          { label: 'Price Range', group: 'details' },
            quantity:            { label: 'Total Bottles', group: 'details' },
            num_cases:           { label: 'Number of Cases', group: 'details' },
            case_size:           { label: 'Bottles per Case', group: 'details' },
            purchase_date:       { label: 'Date Purchased', group: 'details' },
            notes:               { label: 'Tasting Notes', group: 'details' },
        };

        const basicsFields = Object.entries(IMPORT_FIELD_META).filter(([,m]) => m.group === 'basics');
        const detailsFields = Object.entries(IMPORT_FIELD_META).filter(([,m]) => m.group === 'details');

        let html = '<table class="import-mapping-table"><thead><tr><th>Unmapped Column</th><th>Example values</th><th></th><th>Map To</th></tr></thead><tbody>';

        for (const header of data.unmapped_headers) {
            const samples = data.preview_data.slice(0, 3)
                .map(r => String(r[header] || '').substring(0, 30))
                .filter(s => s)
                .join(', ');

            html += `<tr class="import-mapping-row" data-header="${escapeHtml(header)}">
                <td><strong>${escapeHtml(header)}</strong>
                    <span class="import-sample-cell">${escapeHtml(samples)}</span></td>
                <td class="import-arrow-cell">&#x2192;</td>
                <td>
                    <select class="import-mapping-select" data-header="${escapeHtml(header)}">
                        <option value="skip">Skip this column</option>
                        <optgroup label="The Basics">
                            ${basicsFields.map(([key, meta]) =>
                                `<option value="${key}">${meta.label}</option>`
                            ).join('')}
                        </optgroup>
                        <optgroup label="Extra Details">
                            ${detailsFields.map(([key, meta]) =>
                                `<option value="${key}">${meta.label}</option>`
                            ).join('')}
                        </optgroup>
                        <optgroup label="Custom">
                            <option value="custom:${escapeHtml(header)}">${escapeHtml(header)} (custom field)</option>
                        </optgroup>
                    </select>
                </td>
            </tr>`;
        }
        html += '</tbody></table>';

        document.getElementById('import-augment-mapping-container').innerHTML = html;
    } catch (error) {
        showToast(error.message, 'error');
    }
}

/**
 * Handle confirm button on augment UI.
 */
async function handleAugmentConfirm() {
    const stepEl = document.getElementById('import-step-augment');
    const batchId = stepEl.dataset.batchId;
    if (!batchId) return;

    // Collect mapping
    const mapping = {};
    stepEl.querySelectorAll('.import-mapping-select').forEach(sel => {
        mapping[sel.dataset.header] = sel.value;
    });

    // Remove skipped entries
    const filteredMapping = {};
    for (const [h, f] of Object.entries(mapping)) {
        if (f !== 'skip') {
            filteredMapping[h] = f;
        }
    }

    if (Object.keys(filteredMapping).length === 0) {
        showToast('No columns selected for mapping', 'info');
        return;
    }

    try {
        const response = await fetchWithAuth(`${API_BASE}/import/${batchId}/remap`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mapping: filteredMapping })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Remap failed');
        }

        const result = await response.json();
        showToast(`Updated ${result.wines_updated} wines with ${result.fields_added.join(', ')}`, 'success');

        // Navigate to cellar to see updated wines
        resetImportPage();
        navigateTo('cellar');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

/**
 * Handle skip button on augment UI.
 */
function handleAugmentSkip() {
    resetImportPage();
}

/**
 * Show the import dashboard for a completed batch.
 */
async function showImportDashboard(batchId, filename, importResult) {
    _showImportStep('dashboard');

    try {
        const response = await fetchWithAuth(`${API_BASE}/import/${batchId}/wines`);
        if (!response.ok) {
            // Fall back to basic results if dashboard endpoint fails
            showImportResults(importResult);
            return;
        }

        const data = await response.json();
        const summary = data.summary;

        // Title
        const caseText = summary.total_cases > 0
            ? ` (${summary.total_cases} case${summary.total_cases !== 1 ? 's' : ''})`
            : '';
        document.getElementById('import-dashboard-title').textContent =
            `You just added ${summary.wines_created} wines${caseText} from ${escapeHtml(filename)}`;

        // Summary cards
        let summaryHtml = `
            <div class="stat-card">
                <div class="stat-value">${summary.total_bottles}</div>
                <div class="stat-label">Bottles Added</div>
            </div>`;

        if (summary.total_cases > 0) {
            summaryHtml += `
            <div class="stat-card">
                <div class="stat-value">${summary.total_cases}</div>
                <div class="stat-label">Cases</div>
            </div>`;
        }

        summaryHtml += `
            <div class="stat-card">
                <div class="stat-value">${summary.wines_created}</div>
                <div class="stat-label">Unique Wines</div>
            </div>`;

        // Wine type breakdown
        const typeEntries = Object.entries(summary.by_wine_type);
        if (typeEntries.length > 0) {
            const typeText = typeEntries.map(([t, c]) => `${c} ${t}`).join(', ');
            summaryHtml += `
                <div class="stat-card">
                    <div class="stat-value">${typeEntries.length}</div>
                    <div class="stat-label">Wine Styles (${typeText})</div>
                </div>`;
        }

        document.getElementById('import-dashboard-summary').innerHTML = summaryHtml;

        // Unmapped columns notice
        const unmappedNotice = document.getElementById('import-dashboard-unmapped-notice');
        if (data.unmapped_headers && data.unmapped_headers.length > 0) {
            unmappedNotice.style.display = 'block';
            unmappedNotice.innerHTML = `
                <div style="padding:1rem;background:rgba(139,26,74,0.05);border:1px solid var(--border-color);border-radius:var(--radius);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:0.5rem;">
                    <span>Some columns weren't imported: <strong>${data.unmapped_headers.map(h => escapeHtml(h)).join(', ')}</strong></span>
                    <button type="button" class="btn btn-small btn-primary import-augment-btn" data-batch-id="${escapeHtml(batchId)}">Add these details</button>
                </div>`;
            unmappedNotice.querySelector('.import-augment-btn').addEventListener('click', (e) => {
                showAugmentUI(e.target.dataset.batchId);
            });
        } else {
            unmappedNotice.style.display = 'none';
        }

        // Start enrichment countdown if background enrichment was triggered
        if (importResult && importResult.enrichment_started) {
            startDashboardEnrichmentProgress(batchId);
        }

    } catch (error) {
        console.error('Failed to load import dashboard:', error);
        showImportResults(importResult);
    }
}

/**
 * Render mini charts on the import dashboard.
 */
function _renderImportDashboardCharts(summary) {
    // Wine type chart
    const typeCanvas = document.getElementById('import-chart-wine-type');
    if (typeCanvas && summary.by_wine_type && Object.keys(summary.by_wine_type).length > 0) {
        const entries = Object.entries(summary.by_wine_type).sort((a, b) => b[1] - a[1]);
        const labels = entries.map(([k]) => (WINE_TYPE_LABELS && WINE_TYPE_LABELS[k]) || k);
        const values = entries.map(([, v]) => v);
        const colors = entries.map(([k], i) => (WINE_TYPE_COLORS && WINE_TYPE_COLORS[k]) || CHART_COLORS[i % CHART_COLORS.length]);

        new Chart(typeCanvas, {
            type: 'doughnut',
            data: { labels, datasets: [{ data: values, backgroundColor: colors, borderWidth: 2, borderColor: '#fff' }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } },
        });
    }

    // Country chart
    const countryCanvas = document.getElementById('import-chart-country');
    if (countryCanvas && summary.by_country && Object.keys(summary.by_country).length > 0) {
        const entries = Object.entries(summary.by_country).sort((a, b) => b[1] - a[1]).slice(0, 8);
        const labels = entries.map(([k]) => k);
        const values = entries.map(([, v]) => v);

        new Chart(countryCanvas, {
            type: 'bar',
            data: { labels, datasets: [{ data: values, backgroundColor: CHART_COLORS[0], borderRadius: 4 }] },
            options: {
                responsive: true, maintainAspectRatio: false, indexAxis: 'y',
                plugins: { legend: { display: false } },
                scales: { x: { beginAtZero: true, ticks: { stepSize: 1 } } },
            },
        });
    }
}

/**
 * Helper to show only the specified import step.
 */
function _showImportStep(step) {
    const steps = ['upload', 'map', 'progress', 'results', 'duplicate', 'augment', 'dashboard'];
    for (const s of steps) {
        const el = document.getElementById(`import-step-${s}`);
        if (el) el.style.display = (s === step) ? 'block' : 'none';
    }
}

function renderMappingStep(data) {
    // Show step 2
    document.getElementById('import-step-upload').style.display = 'none';
    document.getElementById('import-step-map').style.display = 'block';
    document.getElementById('import-step-results').style.display = 'none';

    document.getElementById('import-file-info').textContent =
        `${data.filename} - ${data.row_count} rows`;

    // Field metadata with friendly labels and hints
    const IMPORT_FIELD_META = {
        name:                { label: 'Wine Name (required)', hint: 'The name on the label, e.g. "Cloudy Bay Sauvignon Blanc"', group: 'basics' },
        winery:              { label: 'Winery / Producer',    hint: 'Who made the wine, e.g. "Chateau Margaux"', group: 'basics' },
        vintage:             { label: 'Vintage Year',         hint: 'The year the grapes were harvested, e.g. "2019"', group: 'basics' },
        grape_variety:       { label: 'Grape',                hint: 'The grape or blend, e.g. "Pinot Noir", "Cabernet/Merlot"', group: 'basics' },
        country:             { label: 'Country',              hint: 'Where the wine is from, e.g. "France", "Australia"', group: 'basics' },
        region:              { label: 'Region',               hint: 'The wine region, e.g. "Bordeaux", "Napa Valley"', group: 'basics' },
        sub_region:          { label: 'Sub-Region',           hint: 'A smaller area within the region, e.g. "Pauillac" within Bordeaux', group: 'details' },
        appellation:         { label: 'Appellation',          hint: 'The official wine-growing designation, e.g. "AOC Saint-Émilion"', group: 'details' },
        wine_type_id:        { label: 'Wine Style',           hint: 'Red, White, Rosé, Sparkling, Dessert, etc.', group: 'details' },
        classification:      { label: 'Classification',       hint: 'Quality ranking, e.g. "Grand Cru", "Reserva", "First Growth"', group: 'details' },
        alcohol_percentage:  { label: 'Alcohol (ABV)',        hint: 'Alcohol by volume as a number, e.g. "13.5"', group: 'details' },
        price_tier:          { label: 'Price Range',          hint: 'Budget, Mid-range, Premium, or Luxury', group: 'details' },
        quantity:            { label: 'Total Bottles',         hint: 'The total number of bottles (not cases)', group: 'details' },
        num_cases:           { label: 'Number of Cases',      hint: 'How many cases — we\'ll calculate bottles from case size', group: 'details' },
        case_size:           { label: 'Bottles per Case',     hint: 'How many bottles in each case (usually 6 or 12)', group: 'details' },
        purchase_date:       { label: 'Date Purchased',      hint: 'When you bought the wine (e.g. 2024-03-15)', group: 'details' },
        notes:               { label: 'Tasting Notes',       hint: 'Your personal notes about the wine', group: 'details' },
    };

    const basicsFields = Object.entries(IMPORT_FIELD_META).filter(([,m]) => m.group === 'basics');
    const detailsFields = Object.entries(IMPORT_FIELD_META).filter(([,m]) => m.group === 'details');

    // Collect initially-matched fields to mark them in dropdowns
    const usedFields = new Set();
    for (const header of data.headers) {
        const suggested = data.suggested_mapping[header] || `custom:${header}`;
        if (!suggested.startsWith('custom:') && suggested !== 'skip' && IMPORT_FIELD_META[suggested]) {
            usedFields.add(suggested);
        }
    }

    // Helper to build option text with "already matched" indicator
    function optionLabel(key, meta, currentSelectValue) {
        const inUse = usedFields.has(key) && currentSelectValue !== key;
        return inUse ? `${meta.label}  \u2713 already matched` : meta.label;
    }

    // Build mapping table: file columns on left, arrow, app fields on right
    let tableHtml = '<table class="import-mapping-table"><thead><tr><th>Your Column</th><th>Example values</th><th></th><th>Maps To</th></tr></thead><tbody>';

    for (let colIndex = 0; colIndex < data.headers.length; colIndex++) {
        const header = data.headers[colIndex];
        const suggested = data.suggested_mapping[header] || `custom:${header}`;

        // Show 2-3 sample values from preview rows
        const samples = data.preview_rows.slice(0, 3)
            .map(r => String(r[header] || '').substring(0, 30))
            .filter(s => s)
            .join(', ');

        // Detect custom field suggestions (e.g. "custom:Cellar Location")
        const isCustom = suggested.startsWith('custom:');
        const customName = isCustom ? suggested.substring(7) : '';
        // For custom fields, select value will be the custom:name option we add to the dropdown
        const selectValue = isCustom ? `custom:${customName}` : suggested;

        const isSkipped = selectValue === 'skip';
        const isAutoMatched = !isCustom && !isSkipped && IMPORT_FIELD_META[selectValue];

        // Determine initial hint text
        let initialHint = '';
        if (isAutoMatched) {
            initialHint = IMPORT_FIELD_META[selectValue].hint;
        } else if (isCustom) {
            initialHint = `"${customName}" will be saved as a custom field on each wine`;
        }

        // Build match badge
        let badgeHtml = '';
        if (isAutoMatched) {
            badgeHtml = '<span class="import-match-badge auto-matched">Auto-matched</span>';
        } else if (!isSkipped) {
            badgeHtml = '<span class="import-match-badge needs-input">Needs your input</span>';
        }

        tableHtml += `<tr class="import-mapping-row ${isSkipped ? 'skipped' : ''}" data-header="${escapeHtml(header)}" data-col-index="${colIndex}">
            <td>
                <span class="import-column-name"><strong>${escapeHtml(header)}</strong></span>
                <span class="import-sample-cell">${escapeHtml(samples)}</span>
            </td>
            <td class="import-arrow-cell">&#x2192;</td>
            <td>
                <div class="import-mapping-controls">
                    <select class="import-mapping-select" data-header="${escapeHtml(header)}" ${isSkipped ? 'disabled' : ''}>
                        <optgroup label="The Basics">
                            ${basicsFields.map(([key, meta]) =>
                                `<option value="${key}" ${selectValue === key ? 'selected' : ''}>${optionLabel(key, meta, selectValue)}</option>`
                            ).join('')}
                        </optgroup>
                        <optgroup label="Extra Details">
                            ${detailsFields.map(([key, meta]) =>
                                `<option value="${key}" ${selectValue === key ? 'selected' : ''}>${optionLabel(key, meta, selectValue)}</option>`
                            ).join('')}
                        </optgroup>
                        ${isCustom ? `<optgroup label="Custom"><option value="custom:${escapeHtml(customName)}" selected>${escapeHtml(customName)}</option></optgroup>` : ''}
                    </select>
                    ${badgeHtml}
                    <button type="button" class="btn btn-small import-skip-btn ${isSkipped ? 'active' : ''}" data-header="${escapeHtml(header)}">Ignore</button>
                </div>
                <span class="import-field-hint" data-header="${escapeHtml(header)}">${initialHint}</span>
            </td>
        </tr>`;
    }
    tableHtml += '</tbody></table>';
    document.getElementById('import-mapping-table-container').innerHTML = tableHtml;

    // Update "already matched" indicators and ignored field states across all dropdowns
    function updateMatchedIndicators() {
        // Collect fields that are actively matched (not ignored)
        const currentUsed = new Set();
        // Collect custom values from ignored rows so they can be disabled in other selects
        const ignoredCustomValues = new Set();
        document.querySelectorAll('.import-mapping-select').forEach(sel => {
            const row = sel.closest('.import-mapping-row');
            const skipBtn = row.querySelector('.import-skip-btn');
            const isIgnored = skipBtn.classList.contains('active');
            if (isIgnored) {
                // Track ignored custom values to disable them elsewhere
                if (sel.value.startsWith('custom:')) {
                    ignoredCustomValues.add(sel.value);
                }
            } else if (IMPORT_FIELD_META[sel.value]) {
                currentUsed.add(sel.value);
            }
        });
        document.querySelectorAll('.import-mapping-select').forEach(sel => {
            const selectedVal = sel.value;
            const row = sel.closest('.import-mapping-row');
            const isThisIgnored = row.querySelector('.import-skip-btn').classList.contains('active');
            sel.querySelectorAll('option').forEach(opt => {
                const key = opt.value;
                const meta = IMPORT_FIELD_META[key];
                if (!meta && !key.startsWith('custom:')) return;

                if (meta) {
                    const inUse = currentUsed.has(key) && selectedVal !== key;
                    opt.textContent = inUse ? `${meta.label}  \u2713 already matched` : meta.label;
                    opt.disabled = inUse;
                }
                // Disable custom options from ignored rows in other selects
                if (key.startsWith('custom:') && ignoredCustomValues.has(key) && !isThisIgnored) {
                    opt.disabled = true;
                }
            });
        });
    }

    // Update hint text on selection change
    document.querySelectorAll('.import-mapping-select').forEach(select => {
        select.addEventListener('change', (e) => {
            const header = e.target.dataset.header;
            const row = document.querySelector(`.import-mapping-row[data-header="${header}"]`);
            const hintEl = row.querySelector('.import-field-hint');
            const badge = row.querySelector('.import-match-badge');

            // Update hint text
            const val = e.target.value;
            if (val.startsWith('custom:')) {
                const name = val.substring(7);
                hintEl.textContent = `"${name}" will be saved as a custom field on each wine`;
            } else {
                const meta = IMPORT_FIELD_META[val];
                hintEl.textContent = meta ? meta.hint : '';
            }

            // Remove badge on manual change
            if (badge) badge.remove();

            // Refresh matched indicators across all dropdowns
            updateMatchedIndicators();
            updateQuantityNotice();
        });
    });

    // Ignore button toggle
    document.querySelectorAll('.import-skip-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const header = e.target.dataset.header;
            const row = document.querySelector(`.import-mapping-row[data-header="${header}"]`);
            const select = row.querySelector('.import-mapping-select');
            const isActive = btn.classList.toggle('active');
            row.classList.toggle('skipped', isActive);
            select.disabled = isActive;
            updateMatchedIndicators();
            updateQuantityNotice();
        });
    });

    // Build preview table with data-col-index attributes for highlight
    if (data.preview_rows.length > 0) {
        let previewHtml = '<table class="import-preview-table"><thead><tr>';
        for (let i = 0; i < data.headers.length; i++) {
            previewHtml += `<th data-col-index="${i}">${escapeHtml(data.headers[i])}</th>`;
        }
        previewHtml += '</tr></thead><tbody>';
        for (const row of data.preview_rows) {
            previewHtml += '<tr>';
            for (let i = 0; i < data.headers.length; i++) {
                previewHtml += `<td data-col-index="${i}">${escapeHtml(String(row[data.headers[i]] || '').substring(0, 40))}</td>`;
            }
            previewHtml += '</tr>';
        }
        previewHtml += '</tbody></table>';
        document.getElementById('import-preview-container').innerHTML = previewHtml;
    }

    // Show/hide quantity notice based on current mappings
    updateQuantityNotice();

    // Column highlight on mapping row hover
    document.querySelectorAll('.import-mapping-row').forEach(row => {
        row.addEventListener('mouseenter', () => {
            const colIndex = row.dataset.colIndex;
            document.querySelectorAll(`.import-preview-table [data-col-index="${colIndex}"]`).forEach(cell => {
                cell.classList.add('import-preview-highlight');
            });
        });
        row.addEventListener('mouseleave', () => {
            const colIndex = row.dataset.colIndex;
            document.querySelectorAll(`.import-preview-table [data-col-index="${colIndex}"]`).forEach(cell => {
                cell.classList.remove('import-preview-highlight');
            });
        });
    });
}

let _incompleteBatchId = null;

async function checkIncompleteBatches() {
    try {
        const response = await fetchWithAuth(`${API_BASE}/import/batches`);
        if (!response.ok) return;
        const batches = await response.json();
        const incomplete = batches.find(b => b.status === 'processing');
        if (!incomplete) return;

        _incompleteBatchId = incomplete.id;
        const notice = document.getElementById('import-incomplete-notice');
        const text = document.getElementById('import-incomplete-text');
        text.textContent = `You have an incomplete import of "${incomplete.filename}" (${incomplete.wines_created} of ${incomplete.row_count} wines imported). You can remove the partial import or re-upload the file — duplicates will be skipped automatically.`;
        notice.style.display = 'block';
    } catch (err) {
        // Silently ignore — not critical
    }
}

async function handleIncompleteUndo() {
    if (!_incompleteBatchId) return;
    const confirmed = confirm('This will remove all wines from the incomplete import. Are you sure?');
    if (!confirmed) return;

    try {
        const response = await fetchWithAuth(`${API_BASE}/import/batches/${_incompleteBatchId}/wines`, {
            method: 'DELETE',
        });
        if (!response.ok) {
            const error = await response.json();
            showToast(error.detail || 'Failed to remove partial import', 'error');
            return;
        }
        const result = await response.json();
        showToast(`Removed ${result.wines_deleted} wines from incomplete import`, 'success');
        document.getElementById('import-incomplete-notice').style.display = 'none';
        _incompleteBatchId = null;
    } catch (err) {
        showToast('Failed to remove partial import: ' + err.message, 'error');
    }
}

async function handleUndoImport() {
    if (!currentImportBatchId) return;

    const wineCount = document.getElementById('import-dashboard-title')?.textContent?.match(/\d+/)?.[0] || 'these';
    const confirmed = confirm(`This will remove all ${wineCount} wines from this import. This cannot be undone.\n\nAre you sure?`);
    if (!confirmed) return;

    try {
        const response = await fetchWithAuth(`${API_BASE}/import/batches/${currentImportBatchId}/wines`, {
            method: 'DELETE',
        });

        if (!response.ok) {
            const error = await response.json();
            showToast(error.detail || 'Failed to undo import', 'error');
            return;
        }

        const result = await response.json();
        showToast(`Removed ${result.wines_deleted} wines from your cellar`, 'success');
        resetImportPage();
    } catch (err) {
        showToast('Failed to undo import: ' + err.message, 'error');
    }
}

// Module-level default case size (set by user via prompt)
let importDefaultCaseSize = null;

function updateImportSummary() {
    const panel = document.getElementById('import-summary-panel');
    const textEl = document.getElementById('import-summary-text');
    const caseSizePrompt = document.getElementById('import-case-size-prompt');
    if (!panel || !textEl) return;

    // Collect current mapping
    const mapping = {};
    document.querySelectorAll('.import-mapping-row').forEach(row => {
        const skipBtn = row.querySelector('.import-skip-btn');
        if (skipBtn && skipBtn.classList.contains('active')) return;
        const sel = row.querySelector('.import-mapping-select');
        if (sel && sel.value) mapping[row.dataset.header] = sel.value;
    });

    // Determine which quantity-related fields are mapped
    const hasQuantity = Object.values(mapping).includes('quantity');
    const hasNumCases = Object.values(mapping).includes('num_cases');
    const hasCaseSize = Object.values(mapping).includes('case_size');

    // Get the mapped column headers for each field
    const quantityHeader = Object.entries(mapping).find(([,v]) => v === 'quantity')?.[0];
    const numCasesHeader = Object.entries(mapping).find(([,v]) => v === 'num_cases')?.[0];
    const caseSizeHeader = Object.entries(mapping).find(([,v]) => v === 'case_size')?.[0];

    // Compute totals from ALL available rows (pendingCsvRows or currentImportData)
    const rows = pendingCsvRows || (currentImportData && currentImportData.rows) || [];
    const previewRows = (currentImportData && currentImportData.preview_rows) || [];
    const dataRows = rows.length > 0 ? rows : previewRows;
    const wineCount = dataRows.length || (currentImportData && currentImportData.row_count) || 0;

    let totalBottles = 0;
    let totalCases = 0;
    let looseBottles = 0;

    for (const row of dataRows) {
        const qty = quantityHeader ? parseInt(row[quantityHeader]) || 0 : 0;
        const cases = numCasesHeader ? parseInt(row[numCasesHeader]) || 0 : 0;
        const cs = caseSizeHeader ? parseInt(row[caseSizeHeader]) || 0 : (importDefaultCaseSize || 0);

        if (hasNumCases && cs > 0) {
            // Mode 1: Cases × case_size
            totalCases += cases;
            totalBottles += cases * cs;
        } else if (hasNumCases && cs === 0) {
            // Cases without case_size — can't compute yet
            totalCases += cases;
        } else if (hasQuantity && cs > 0 && qty >= cs) {
            // Mode 2: Bottles ÷ case_size
            const numC = Math.floor(qty / cs);
            const loose = qty % cs;
            totalCases += numC;
            totalBottles += qty;
            looseBottles += loose;
        } else if (hasQuantity) {
            // Mode 3: Just bottles
            totalBottles += qty || 1;
        } else {
            totalBottles += 1;
        }
    }

    // Build summary text
    panel.style.display = 'block';
    caseSizePrompt.style.display = 'none';

    if (hasNumCases && hasCaseSize) {
        textEl.innerHTML = `Your spreadsheet has case counts and case sizes. We'll create <strong>${totalCases} cases</strong> containing <strong>${totalBottles} bottles</strong> across <strong>${wineCount} wines</strong>.`;
    } else if (hasNumCases && !hasCaseSize) {
        if (importDefaultCaseSize) {
            const bottles = totalCases * importDefaultCaseSize;
            textEl.innerHTML = `Your spreadsheet has case counts. Using <strong>${importDefaultCaseSize} bottles per case</strong>, we'll create <strong>${totalCases} cases</strong> containing <strong>${bottles} bottles</strong>.`;
        } else {
            textEl.innerHTML = `Your spreadsheet has a case count but no case size column.`;
            caseSizePrompt.style.display = 'block';
        }
    } else if (hasQuantity && hasCaseSize) {
        const casedBottles = totalBottles - looseBottles;
        let msg = `Your spreadsheet has bottle counts and case sizes. We'll organise <strong>${totalBottles} bottles</strong> into <strong>${totalCases} cases</strong>`;
        if (looseBottles > 0) msg += ` with <strong>${looseBottles} loose bottles</strong>`;
        msg += ` across <strong>${wineCount} wines</strong>.`;
        textEl.innerHTML = msg;
    } else if (hasQuantity) {
        textEl.innerHTML = `Your spreadsheet has a bottle count per wine. We'll add <strong>${totalBottles} bottles</strong> across <strong>${wineCount} wines</strong> — all as individual bottles (no cases).`;
    } else {
        textEl.innerHTML = `No quantity columns matched — each wine will be added as <strong>1 bottle</strong>. Total: <strong>${wineCount} bottles</strong>.`;
    }
}

// Legacy alias — called from existing code
function updateQuantityNotice() {
    updateImportSummary();
}

async function handleConfirmMapping() {
    if (!currentImportBatchId) return;

    // Collect mapping from dropdowns
    const mapping = {};
    document.querySelectorAll('.import-mapping-row').forEach(row => {
        const header = row.dataset.header;
        const skipBtn = row.querySelector('.import-skip-btn');
        if (skipBtn.classList.contains('active')) {
            mapping[header] = 'skip';
            return;
        }
        mapping[header] = row.querySelector('.import-mapping-select').value;
    });

    // Validate at least one name mapping
    if (!Object.values(mapping).includes('name')) {
        showToast('At least one column must be mapped to "Wine Name"', 'error');
        return;
    }

    try {
        // Show progress bar immediately so user gets instant feedback
        _showImportStep('progress');

        // Reset progress UI
        document.getElementById('import-progress-fill').style.width = '0%';
        document.getElementById('import-progress-text').textContent = 'Saving mapping...';
        document.getElementById('import-progress-percent').textContent = '';
        document.getElementById('import-progress-created').textContent = '';
        document.getElementById('import-progress-skipped').textContent = '';

        // Set mapping
        const mapResponse = await fetchWithAuth(`${API_BASE}/import/${currentImportBatchId}/mapping`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mapping: mapping })
        });

        if (!mapResponse.ok) {
            const error = await mapResponse.json();
            throw new Error(error.detail || 'Failed to set mapping');
        }

        // If client-parsed CSV, upload rows in chunks first
        if (pendingCsvRows) {
            await uploadRowChunks(currentImportBatchId, pendingCsvRows);
            pendingCsvRows = null;
        }

        // Reset progress for processing phase
        document.getElementById('import-progress-fill').style.width = '0%';
        document.getElementById('import-progress-text').textContent = '0 / 0 rows';
        document.getElementById('import-progress-percent').textContent = '0%';

        // Stream processing with progress (enrichment always runs in background after)
        const processResponse = await fetchWithAuth(`${API_BASE}/import/${currentImportBatchId}/process-stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ skip_non_wine: true, default_quantity: 1, skip_enrichment: true, default_case_size: importDefaultCaseSize })
        });

        if (!processResponse.ok) {
            const error = await processResponse.json();
            throw new Error(error.detail || 'Processing failed');
        }

        const result = await readImportStream(processResponse);

        // Show import dashboard (enrichment countdown handled there)
        const filename = currentImportData ? currentImportData.filename : 'your file';
        showImportDashboard(currentImportBatchId, filename, result);
    } catch (error) {
        showToast(error.message, 'error');
        // Restore mapping step if progress was shown prematurely
        _showImportStep('map');
    }
}

async function readImportStream(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let lastEvent = null;

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Parse SSE events (separated by double newlines)
        const parts = buffer.split('\n\n');
        buffer = parts.pop(); // keep incomplete last chunk

        for (const part of parts) {
            const trimmed = part.trim();
            if (!trimmed.startsWith('data: ')) continue;

            try {
                const data = JSON.parse(trimmed.slice(6));
                lastEvent = data;

                // Update progress bar
                const pct = data.total > 0 ? Math.round((data.processed / data.total) * 100) : 0;
                document.getElementById('import-progress-fill').style.width = pct + '%';
                document.getElementById('import-progress-text').textContent = `${data.processed} / ${data.total} rows`;
                document.getElementById('import-progress-percent').textContent = pct + '%';
                document.getElementById('import-progress-created').textContent = `${data.wines_created} wines created`;
                document.getElementById('import-progress-skipped').textContent = `${data.rows_skipped} rows skipped`;
            } catch (e) {
                // Skip malformed events
            }
        }
    }

    // Return the final event as the result
    if (lastEvent && lastEvent.done) {
        return lastEvent;
    }

    // Fallback: construct result from last progress event
    return lastEvent || { wines_created: 0, rows_skipped: 0, errors: [], status: 'completed' };
}

function showImportResults(result) {
    _showImportStep('results');

    // Store skipped rows for modal access
    window._lastSkippedRows = result.skipped_rows || [];

    const skippedValue = (result.rows_skipped > 0 && window._lastSkippedRows.length > 0)
        ? `<a href="#" class="skipped-rows-link" style="color:var(--primary-color);text-decoration:underline;">${result.rows_skipped}</a>`
        : `${result.rows_skipped}`;

    let html = `
        <div class="stats-grid" style="margin-bottom:1.5rem;">
            <div class="stat-card">
                <div class="stat-value">${result.wines_created}</div>
                <div class="stat-label">Wines Created</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">${skippedValue}</div>
                <div class="stat-label">Rows Skipped</div>
            </div>
        </div>
    `;

    if (result.errors && result.errors.length > 0) {
        html += '<div style="margin-top:1rem;"><strong>Errors:</strong><ul>';
        for (const err of result.errors.slice(0, 20)) {
            html += `<li style="color:var(--error-color);font-size:0.9rem;">${escapeHtml(err)}</li>`;
        }
        if (result.errors.length > 20) {
            html += `<li>... and ${result.errors.length - 20} more</li>`;
        }
        html += '</ul></div>';
    }

    document.getElementById('import-results-content').innerHTML = html;

    // Wire up skipped rows link (CSP-compliant)
    document.querySelector('.skipped-rows-link')?.addEventListener('click', (e) => {
        e.preventDefault();
        showSkippedRows();
    });

    if (result.wines_created > 0) {
        showToast(`Successfully imported ${result.wines_created} wines!`, 'success');
    }

    // Start enrichment progress tracking if background enrichment was triggered
    if (result.enrichment_started) {
        startEnrichmentProgress();
    }
}

// ---------------------------------------------------------------------------
// Background enrichment progress (toast-based SSE)
// ---------------------------------------------------------------------------

function startEnrichmentProgress() {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = 'toast info';
    toast.id = 'enrichment-toast';
    toast.textContent = 'Enriching wines with reference data...';
    container.appendChild(toast);

    const token = localStorage.getItem('winebox_token') || sessionStorage.getItem('winebox_token');

    // Use fetch + ReadableStream for SSE since EventSource doesn't support auth headers
    fetch(`${API_BASE}/wines/enrichment-progress`, {
        headers: { 'Authorization': `Bearer ${token}` },
    }).then(response => {
        if (!response.ok) {
            toast.remove();
            return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        function read() {
            reader.read().then(({ done, value }) => {
                if (done) {
                    // Stream ended without done event — clean up
                    setTimeout(() => toast.remove(), 3000);
                    return;
                }

                buffer += decoder.decode(value, { stream: true });
                const parts = buffer.split('\n\n');
                buffer = parts.pop();

                for (const part of parts) {
                    const trimmed = part.trim();
                    if (!trimmed.startsWith('data: ')) continue;

                    try {
                        const data = JSON.parse(trimmed.slice(6));

                        if (data.phase === 'done') {
                            toast.className = 'toast success';
                            toast.textContent = `${data.enriched} wines augmented`;
                            setTimeout(() => toast.remove(), 5000);
                            // Refresh cellar to show enriched data
                            loadCellar();
                            return;
                        } else if (data.phase === 'enriching') {
                            toast.textContent = `Enriching wines: ${data.enriched}/${data.total}...`;
                        } else if (data.phase === 'idle') {
                            toast.remove();
                            return;
                        }
                    } catch (e) {
                        // Ignore parse errors
                    }
                }

                read();
            }).catch(() => {
                setTimeout(() => toast.remove(), 3000);
            });
        }

        read();
    }).catch(() => {
        toast.remove();
    });
}

function startDashboardEnrichmentProgress(batchId) {
    const container = document.getElementById('import-dashboard-enrichment');
    const textEl = document.getElementById('import-dashboard-enrichment-text');
    const statusDiv = container?.querySelector('.enrichment-status');
    if (!container || !textEl) return;

    container.style.display = 'block';

    const token = localStorage.getItem('winebox_token') || sessionStorage.getItem('winebox_token');

    fetch(`${API_BASE}/wines/enrichment-progress`, {
        headers: { 'Authorization': `Bearer ${token}` },
    }).then(response => {
        if (!response.ok) {
            container.style.display = 'none';
            return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        function read() {
            reader.read().then(({ done, value }) => {
                if (done) {
                    container.style.display = 'none';
                    return;
                }

                buffer += decoder.decode(value, { stream: true });
                const parts = buffer.split('\n\n');
                buffer = parts.pop();

                for (const part of parts) {
                    const trimmed = part.trim();
                    if (!trimmed.startsWith('data: ')) continue;

                    try {
                        const data = JSON.parse(trimmed.slice(6));

                        if (data.phase === 'done') {
                            if (statusDiv) statusDiv.classList.add('done');
                            textEl.textContent = `${data.enriched} wines augmented \u2713`;
                            // Refresh dashboard wine cards with enriched data
                            return;
                        } else if (data.phase === 'enriching') {
                            const remaining = data.total - data.enriched;
                            textEl.textContent = `Enriching wine details: ${remaining} remaining...`;
                        } else if (data.phase === 'idle') {
                            container.style.display = 'none';
                            return;
                        }
                    } catch (e) {
                        // Ignore parse errors
                    }
                }

                read();
            }).catch(() => {
                container.style.display = 'none';
            });
        }

        read();
    }).catch(() => {
        container.style.display = 'none';
    });
}

function showSkippedRows() {
    const skippedRows = window._lastSkippedRows || [];
    if (skippedRows.length === 0) return;

    let html = '';
    for (const sr of skippedRows) {
        const entries = Object.entries(sr.data || {}).filter(([, v]) => v != null && String(v).trim() !== '');
        html += `<div style="background:var(--card-background);border:1px solid var(--border-color);border-radius:8px;padding:1rem;margin-bottom:0.75rem;">
            <div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.75rem;">
                <span style="background:var(--background-color);border-radius:4px;padding:0.25rem 0.6rem;font-weight:600;font-size:0.85rem;">Row ${sr.row}</span>
                <span style="color:var(--error-color);font-size:0.9rem;">${escapeHtml(sr.reason)}</span>
            </div>
            <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:0.5rem;">
                ${entries.map(([k, v]) => `
                    <div>
                        <div style="font-size:0.7rem;text-transform:uppercase;color:var(--text-muted);letter-spacing:0.05em;">${escapeHtml(k)}</div>
                        <div style="font-size:0.875rem;">${escapeHtml(String(v))}</div>
                    </div>
                `).join('')}
            </div>
        </div>`;
    }

    document.getElementById('skipped-rows-content').innerHTML = html;
    openModal('skipped-rows-modal');
}

function resetImportPage() {
    _showImportStep('upload');
    document.getElementById('import-file-input').value = '';
    currentImportBatchId = null;
    currentImportData = null;
    pendingCsvRows = null;
    pendingCsvFile = null;
    isUploadingRows = false;
}

// ==================== Wines I've Met ====================

function initMetPage() {
    const searchInput = document.getElementById('met-search');
    if (searchInput) {
        searchInput.addEventListener('input', debounce(filterMetWines, 300));
    }
    document.getElementById('met-view-cards')?.addEventListener('click', () => setMetViewMode('cards'));
    document.getElementById('met-view-table')?.addEventListener('click', () => setMetViewMode('table'));
    document.getElementById('met-record-wine-btn')?.addEventListener('click', () => {
        currentCheckinMode = 'met';
        navigateTo('checkin');
        // Update checkin page heading for met mode
        const heading = document.querySelector('#page-checkin h2');
        const subtitle = document.querySelector('#page-checkin .page-subtitle');
        if (heading) heading.textContent = 'Record a Wine';
        if (subtitle) subtitle.textContent = 'Scan a label to record a wine you\'ve encountered';
    });
}

async function loadMet() {
    try {
        const response = await fetchWithAuth(`${API_BASE}/met`);
        metLastWines = await response.json();
        renderMetView();
    } catch (error) {
        console.error('Failed to load met wines:', error);
    }
}

function filterMetWines() {
    const search = (document.getElementById('met-search')?.value || '').toLowerCase();
    if (!search) {
        renderMetView();
        return;
    }
    const filtered = metLastWines.filter(w =>
        w.name.toLowerCase().includes(search) ||
        (w.winery && w.winery.toLowerCase().includes(search)) ||
        (w.country && w.country.toLowerCase().includes(search))
    );
    renderMetViewWith(filtered);
}

function setMetViewMode(mode) {
    metViewMode = mode;
    document.getElementById('met-view-cards')?.classList.toggle('active', mode === 'cards');
    document.getElementById('met-view-table')?.classList.toggle('active', mode === 'table');
    const metList = document.getElementById('met-list');
    if (mode === 'table') {
        metList.classList.remove('wine-grid');
    } else {
        metList.classList.add('wine-grid');
    }
    if (metLastWines.length > 0) renderMetView();
}

function renderMetView() {
    renderMetViewWith(metLastWines);
}

function renderMetViewWith(wines) {
    if (metViewMode === 'table') {
        renderMetTable('met-list', wines);
    } else {
        renderMetGrid('met-list', wines);
    }
}

function renderMetGrid(containerId, wines) {
    const container = document.getElementById(containerId);
    if (!wines || wines.length === 0) {
        container.innerHTML = '<div class="empty-state"><h3>No wines recorded yet</h3><p>Use Add Wine to scan a label</p></div>';
        return;
    }

    container.innerHTML = wines.map(wine => {
        const ef = wine.enriched_fields || [];
        const inCellarBadge = wine.added_to_cellar
            ? '<span class="in-cellar-badge">In Cellar</span>'
            : '';

        return `
            <div class="wine-card" data-wine-id="${wine.id}">
                <div class="wine-card-image">
                    ${wine.front_label_image_path
                        ? `<img src="/api/images/${wine.front_label_image_path}" alt="${escapeHtml(wine.name)}">`
                        : '<span style="color: white; opacity: 0.6;">No Image</span>'
                    }
                    ${inCellarBadge}
                </div>
                <div class="wine-card-content">
                    <div class="wine-card-title">${escapeHtml(wine.name)}</div>
                    <div class="wine-card-subtitle">
                        ${wine.winery ? `<span class="${ef.includes('winery') ? 'enriched' : ''}">${escapeHtml(wine.winery)}</span>` : ''}
                        ${wine.vintage ? ` - ${wine.vintage}` : ''}
                    </div>
                    <div class="wine-card-fields">
                        <div class="wine-card-field">
                            <span class="wine-card-field-label">Country</span>
                            <span class="wine-card-field-value${ef.includes('country') ? ' enriched' : ''}">${wine.country ? escapeHtml(wine.country) : '\u2014'}</span>
                        </div>
                        <div class="wine-card-field">
                            <span class="wine-card-field-label">Region</span>
                            <span class="wine-card-field-value${ef.includes('region') ? ' enriched' : ''}">${wine.region ? escapeHtml(wine.region) : '\u2014'}</span>
                        </div>
                    </div>
                    <div class="wine-card-footer">
                        ${wine.added_to_cellar
                            ? '<span class="wine-quantity">Already in cellar</span>'
                            : `<button class="btn btn-small btn-primary add-to-cellar-btn" data-wine-id="${wine.id}">Add to Cellar</button>`
                        }
                    </div>
                </div>
            </div>
        `;
    }).join('');

    // Click handlers for cards
    container.querySelectorAll('.wine-card').forEach(card => {
        card.addEventListener('click', (e) => {
            if (!e.target.classList.contains('add-to-cellar-btn')) {
                showWineDetail(card.dataset.wineId);
            }
        });
    });

    container.querySelectorAll('.add-to-cellar-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            goToAddFromMet(btn.dataset.wineId);
        });
    });
}

function renderMetTable(containerId, wines) {
    const container = document.getElementById(containerId);
    if (!wines || wines.length === 0) {
        container.innerHTML = '<div class="empty-state"><h3>No wines recorded yet</h3><p>Use Add Wine to scan a label</p></div>';
        return;
    }

    const rows = wines.map(wine => {
        const ef = wine.enriched_fields || [];
        return `
            <tr class="wine-table-row" data-wine-id="${wine.id}">
                <td class="wine-table-name">${escapeHtml(wine.name)}</td>
                <td>${wine.winery ? `<span class="${ef.includes('winery') ? 'enriched' : ''}">${escapeHtml(wine.winery)}</span>` : '-'}</td>
                <td>${wine.vintage || '-'}</td>
                <td class="wine-table-hide-mobile">${wine.country ? `<span class="${ef.includes('country') ? 'enriched' : ''}">${escapeHtml(wine.country)}</span>` : '-'}</td>
                <td>${wine.added_to_cellar ? '<span class="in-cellar-badge">In Cellar</span>' : `<button class="btn btn-small btn-primary add-to-cellar-btn" data-wine-id="${wine.id}">Add to Cellar</button>`}</td>
            </tr>
        `;
    }).join('');

    container.innerHTML = `
        <div class="wine-table-wrapper">
            <table class="wine-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Winery</th>
                        <th>Vintage</th>
                        <th class="wine-table-hide-mobile">Country</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
    `;

    container.querySelectorAll('.wine-table-row').forEach(row => {
        row.addEventListener('click', (e) => {
            if (!e.target.classList.contains('add-to-cellar-btn')) {
                showWineDetail(row.dataset.wineId);
            }
        });
    });

    container.querySelectorAll('.add-to-cellar-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            goToAddFromMet(btn.dataset.wineId);
        });
    });

    // Make table sortable by column headers
    const metTable = container.querySelector('.wine-table');
    if (metTable) makeTableSortable(metTable);
}

function goToAddFromMet(wineId) {
    navigateTo('add-to-cellar');
    // Auto-select "from-met" path and pre-select the wine
    setTimeout(() => {
        selectEntryPath('from-met');
        selectMetWineForCellar(wineId);
    }, 50);
}

// ==================== Add to Cellar Wizard ====================

// Path labels for breadcrumbs
const ENTRY_PATH_LABELS = {
    'scan': 'Scan a Label',
    'manual': 'Enter Details Manually',
    'from-met': 'From a Wine I\'ve Met',
    'import': 'Import from File',
};

function initAddToCellarPage() {
    // Entry path card clicks
    document.querySelectorAll('.entry-path-card').forEach(card => {
        card.addEventListener('click', () => {
            selectEntryPath(card.dataset.path);
        });
    });

    // Breadcrumb root link
    document.getElementById('breadcrumb-root')?.addEventListener('click', (e) => {
        e.preventDefault();
        resetAddToCellarWizard();
    });

    // Manual entry form
    const manualForm = document.getElementById('manual-cellar-form');
    if (manualForm) {
        manualForm.addEventListener('submit', handleManualCellarSubmit);
    }

    // Back buttons
    document.getElementById('manual-back-btn')?.addEventListener('click', () => resetAddToCellarWizard());
    document.getElementById('scan-back-btn')?.addEventListener('click', () => resetAddToCellarWizard());
    document.getElementById('from-met-back-btn')?.addEventListener('click', () => resetAddToCellarWizard());
    document.getElementById('met-picker-back-btn')?.addEventListener('click', () => {
        document.getElementById('met-picker-selected').style.display = 'none';
        document.getElementById('met-picker-list').style.display = '';
        document.getElementById('met-picker-back-container').style.display = '';
        selectedMetWineId = null;
    });
    document.getElementById('import-back-btn')?.addEventListener('click', () => resetAddToCellarWizard());

    // Met picker search
    document.getElementById('met-picker-search')?.addEventListener('input', debounce(filterMetPicker, 300));

    // Quantity presets
    document.querySelectorAll('.qty-preset').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.qty-preset').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById('met-picker-quantity').value = btn.dataset.qty;
        });
    });

    // Add to cellar from met button
    document.getElementById('met-add-to-cellar-btn')?.addEventListener('click', handleAddMetToCellar);

    // Scan sub-wizard
    initScanCellarSubwizard();

    // Cases toggle for scan and manual quantity fields
    function setupCaseToggle(unitSelectId, caseSizeId) {
        const unitSelect = document.getElementById(unitSelectId);
        const caseSizeInput = document.getElementById(caseSizeId);
        if (!unitSelect || !caseSizeInput) return;
        unitSelect.addEventListener('change', () => {
            caseSizeInput.style.display = unitSelect.value === 'cases' ? '' : 'none';
        });
    }
    setupCaseToggle('scan-quantity-unit', 'scan-case-size');
    setupCaseToggle('manual-quantity-unit', 'manual-case-size');
}

function resetAddToCellarWizard() {
    // Show cards, hide all sub-wizards
    document.getElementById('entry-path-cards').style.display = '';
    document.querySelectorAll('.add-cellar-subwizard').forEach(el => el.style.display = 'none');
    document.querySelectorAll('.entry-path-card').forEach(c => c.classList.remove('active'));
    selectedMetWineId = null;

    // Hide step breadcrumb, show subtitle
    document.querySelectorAll('.breadcrumb-step-sep').forEach(el => el.style.display = 'none');
    document.getElementById('breadcrumb-current').textContent = '';
    document.getElementById('add-cellar-subtitle').style.display = '';
}

function selectEntryPath(path) {
    // Hide cards, show selected sub-wizard
    document.getElementById('entry-path-cards').style.display = 'none';
    document.querySelectorAll('.add-cellar-subwizard').forEach(el => el.style.display = 'none');

    document.querySelectorAll('.entry-path-card').forEach(c => {
        c.classList.toggle('active', c.dataset.path === path);
    });

    // Show step in breadcrumb, hide subtitle
    document.querySelectorAll('.breadcrumb-step-sep').forEach(el => el.style.display = '');
    document.getElementById('breadcrumb-current').textContent = ENTRY_PATH_LABELS[path] || path;
    document.getElementById('add-cellar-subtitle').style.display = 'none';

    if (path === 'scan') {
        document.getElementById('add-cellar-scan').style.display = 'block';
    } else if (path === 'manual') {
        document.getElementById('add-cellar-manual').style.display = 'block';
    } else if (path === 'from-met') {
        document.getElementById('add-cellar-from-met').style.display = 'block';
        loadMetPickerList();
    } else if (path === 'import') {
        document.getElementById('add-cellar-import').style.display = 'block';
    }
}

// Scan-to-cellar sub-wizard
let scanCellarResult = null;

function initScanCellarSubwizard() {
    const frontInput = document.getElementById('scan-front-label');
    const backInput = document.getElementById('scan-back-label');
    const frontPreview = document.getElementById('scan-front-preview');
    const backPreview = document.getElementById('scan-back-preview');

    if (!frontInput) return;

    frontInput.addEventListener('change', (e) => {
        previewImage(e.target, 'scan-front-preview');
        scanCellarLabels();
    });
    backInput.addEventListener('change', (e) => {
        previewImage(e.target, 'scan-back-preview');
        scanCellarLabels();
    });

    frontPreview.addEventListener('click', () => frontInput.click());
    backPreview.addEventListener('click', () => backInput.click());

    document.getElementById('scan-add-to-cellar-btn')?.addEventListener('click', handleScanCellarSubmit);
}

async function scanCellarLabels() {
    const frontInput = document.getElementById('scan-front-label');
    if (!frontInput.files || !frontInput.files[0]) return;

    const backInput = document.getElementById('scan-back-label');
    const formData = new FormData();
    formData.append('front_label', frontInput.files[0]);
    if (backInput.files && backInput.files[0]) {
        formData.append('back_label', backInput.files[0]);
    }

    // Show scanning indicator
    document.getElementById('scan-cellar-scanning').style.display = 'flex';
    document.getElementById('scan-cellar-fields').style.display = 'none';

    try {
        const response = await fetchWithAuth(`${API_BASE}/wines/scan`, {
            method: 'POST',
            body: formData
        });
        if (!response.ok) throw new Error('Scan failed');

        const result = await response.json();
        scanCellarResult = result;

        // Populate fields
        const parsed = result.parsed;
        const fields = {
            'scan-wine-name': parsed.name,
            'scan-winery': parsed.winery,
            'scan-vintage': parsed.vintage,
            'scan-grape-variety': parsed.grape_variety,
            'scan-region': parsed.region,
            'scan-country': parsed.country,
        };
        for (const [id, value] of Object.entries(fields)) {
            const el = document.getElementById(id);
            if (el && value != null) el.value = value;
        }
        if (parsed.wine_type) {
            const sel = document.getElementById('scan-wine-type');
            if (sel) sel.value = parsed.wine_type.toLowerCase();
        }

        document.getElementById('scan-cellar-fields').style.display = 'block';
        showToast('Label scanned successfully', 'success');
    } catch (error) {
        showToast(`Scan failed: ${error.message}`, 'error');
    } finally {
        document.getElementById('scan-cellar-scanning').style.display = 'none';
    }
}

async function handleScanCellarSubmit() {
    const frontInput = document.getElementById('scan-front-label');
    if (!frontInput.files || !frontInput.files[0]) {
        showToast('Please scan a label first', 'error');
        return;
    }

    const formData = new FormData();
    formData.append('front_label', frontInput.files[0]);

    const backInput = document.getElementById('scan-back-label');
    if (backInput.files && backInput.files[0]) {
        formData.append('back_label', backInput.files[0]);
    }

    formData.append('name', document.getElementById('scan-wine-name').value);
    const winery = document.getElementById('scan-winery').value;
    if (winery) formData.append('winery', winery);
    const vintage = document.getElementById('scan-vintage').value;
    if (vintage) formData.append('vintage', vintage);
    const grape = document.getElementById('scan-grape-variety').value;
    if (grape) formData.append('grape_variety', grape);
    const region = document.getElementById('scan-region').value;
    if (region) formData.append('region', region);
    const country = document.getElementById('scan-country').value;
    if (country) formData.append('country', country);
    const wineType = document.getElementById('scan-wine-type').value;
    if (wineType) formData.append('wine_type_id', wineType);
    let scanQty = parseInt(document.getElementById('scan-quantity').value) || 1;
    const scanUnit = document.getElementById('scan-quantity-unit').value;
    if (scanUnit === 'cases') {
        const caseSize = parseInt(document.getElementById('scan-case-size').value) || 12;
        formData.append('quantity', String(scanQty * caseSize));
        formData.append('case_size', String(caseSize));
    } else {
        formData.append('quantity', String(scanQty));
    }

    // Pass pre-scanned text to avoid re-scanning
    if (scanCellarResult?.ocr?.front_label_text) {
        formData.append('front_label_text', scanCellarResult.ocr.front_label_text);
    }
    if (scanCellarResult?.ocr?.back_label_text) {
        formData.append('back_label_text', scanCellarResult.ocr.back_label_text);
    }

    try {
        const response = await fetchWithAuth(`${API_BASE}/wines/checkin`, {
            method: 'POST',
            body: formData
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to add wine');
        }
        const wine = await response.json();
        showToast(`Added to cellar: ${wine.name}`, 'success');
        // Reset scan form
        scanCellarResult = null;
        document.getElementById('scan-front-label').value = '';
        document.getElementById('scan-back-label').value = '';
        document.getElementById('scan-front-preview').innerHTML = 'Tap to take photo or select image';
        document.getElementById('scan-back-preview').innerHTML = 'Tap to take photo or select image';
        document.getElementById('scan-cellar-fields').style.display = 'none';
        navigateTo('cellar');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function handleManualCellarSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const formData = new FormData();

    // We need a front_label image for the checkin endpoint — create a minimal placeholder
    const placeholder = new Blob([new Uint8Array([
        0x89,0x50,0x4E,0x47,0x0D,0x0A,0x1A,0x0A,
        0x00,0x00,0x00,0x0D,0x49,0x48,0x44,0x52,
        0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x01,
        0x08,0x02,0x00,0x00,0x00,0x90,0x77,0x53,
        0xDE,0x00,0x00,0x00,0x0C,0x49,0x44,0x41,
        0x54,0x08,0xD7,0x63,0xF8,0xFF,0xFF,0x3F,
        0x00,0x05,0xFE,0x02,0xFE,0xA3,0x1A,0x8D,
        0xEB,0x00,0x00,0x00,0x00,0x49,0x45,0x4E,
        0x44,0xAE,0x42,0x60,0x82
    ])], { type: 'image/png' });
    formData.append('front_label', placeholder, 'placeholder.png');

    formData.append('name', document.getElementById('manual-wine-name').value);
    const winery = document.getElementById('manual-winery').value;
    if (winery) formData.append('winery', winery);
    const vintage = document.getElementById('manual-vintage').value;
    if (vintage) formData.append('vintage', vintage);
    const grape = document.getElementById('manual-grape-variety').value;
    if (grape) formData.append('grape_variety', grape);
    const region = document.getElementById('manual-region').value;
    if (region) formData.append('region', region);
    const country = document.getElementById('manual-country').value;
    if (country) formData.append('country', country);
    const wineType = document.getElementById('manual-wine-type').value;
    if (wineType) formData.append('wine_type_id', wineType);
    let manualQty = parseInt(document.getElementById('manual-quantity').value) || 1;
    const manualUnit = document.getElementById('manual-quantity-unit').value;
    if (manualUnit === 'cases') {
        const caseSize = parseInt(document.getElementById('manual-case-size').value) || 12;
        formData.append('quantity', String(manualQty * caseSize));
        formData.append('case_size', String(caseSize));
    } else {
        formData.append('quantity', String(manualQty));
    }

    try {
        const response = await fetchWithAuth(`${API_BASE}/wines/checkin`, {
            method: 'POST',
            body: formData
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to add wine');
        }
        const wine = await response.json();
        showToast(`Added to cellar: ${wine.name}`, 'success');
        form.reset();
        navigateTo('cellar');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function loadMetPickerList() {
    try {
        const response = await fetchWithAuth(`${API_BASE}/met`);
        const wines = await response.json();
        // Filter out wines already in cellar
        const available = wines.filter(w => !w.added_to_cellar);
        renderMetPickerList(available);
    } catch (error) {
        console.error('Failed to load met wines for picker:', error);
    }
}

function renderMetPickerList(wines) {
    const container = document.getElementById('met-picker-list');
    if (!wines || wines.length === 0) {
        container.innerHTML = '<div class="empty-state"><p>No wines available to add. Record a wine first!</p></div>';
        return;
    }

    container.innerHTML = wines.map(wine => `
        <div class="met-picker-item" data-wine-id="${wine.id}">
            <div class="met-picker-item-image">
                ${wine.front_label_image_path
                    ? `<img src="/api/images/${wine.front_label_image_path}" alt="${escapeHtml(wine.name)}">`
                    : '<span>No Image</span>'
                }
            </div>
            <div class="met-picker-item-info">
                <div class="met-picker-item-name">${escapeHtml(wine.name)}</div>
                <div class="met-picker-item-details">
                    ${wine.winery ? escapeHtml(wine.winery) : ''}
                    ${wine.vintage ? ` - ${wine.vintage}` : ''}
                    ${wine.country ? ` · ${escapeHtml(wine.country)}` : ''}
                </div>
            </div>
        </div>
    `).join('');

    container.querySelectorAll('.met-picker-item').forEach(item => {
        item.addEventListener('click', () => {
            selectMetWineForCellar(item.dataset.wineId);
        });
    });
}

function filterMetPicker() {
    const search = (document.getElementById('met-picker-search')?.value || '').toLowerCase();
    const items = document.querySelectorAll('.met-picker-item');
    items.forEach(item => {
        const text = item.textContent.toLowerCase();
        item.style.display = text.includes(search) ? '' : 'none';
    });
}

async function selectMetWineForCellar(wineId) {
    selectedMetWineId = wineId;

    // Find the wine in metLastWines or fetch it
    let wine = metLastWines.find(w => w.id === wineId);
    if (!wine) {
        try {
            const response = await fetchWithAuth(`${API_BASE}/wines/${wineId}`);
            wine = await response.json();
        } catch {
            showToast('Could not load wine details', 'error');
            return;
        }
    }

    document.getElementById('met-picker-wine-name').textContent = wine.name;
    document.getElementById('met-picker-wine-details').textContent = [
        wine.winery, wine.vintage, wine.country
    ].filter(Boolean).join(' · ');

    document.getElementById('met-picker-list').style.display = 'none';
    document.getElementById('met-picker-back-container').style.display = 'none';
    document.getElementById('met-picker-selected').style.display = 'block';
    document.getElementById('met-picker-quantity').value = 1;
    document.querySelectorAll('.qty-preset').forEach(b => b.classList.remove('active'));
}

async function handleAddMetToCellar() {
    if (!selectedMetWineId) return;

    const quantity = document.getElementById('met-picker-quantity').value || '1';
    const formData = new FormData();
    formData.append('quantity', quantity);

    try {
        const response = await fetchWithAuth(`${API_BASE}/wines/${selectedMetWineId}/add-to-cellar`, {
            method: 'POST',
            body: formData
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to add to cellar');
        }
        const wine = await response.json();
        showToast(`Added ${quantity} bottle${quantity > 1 ? 's' : ''} of ${wine.name} to cellar`, 'success');
        navigateTo('cellar');
    } catch (error) {
        showToast(error.message, 'error');
    }
}


// =============================================================================
// Demo / Sample Data
// =============================================================================

async function installDemoData() {
    try {
        const btn = document.getElementById('cellar-demo-install-btn') || document.getElementById('demo-install-btn');
        if (btn) btn.disabled = true;

        // Save original welcome content and replace with progress bar
        const welcome = document.getElementById('cellar-welcome-panel') || document.getElementById('demo-welcome');
        const savedWelcomeHtml = welcome ? welcome.innerHTML : null;
        if (welcome) {
            welcome.innerHTML = `
                <div class="demo-welcome-content">
                    <h3>Loading sample wines...</h3>
                    <div class="demo-progress-container">
                        <div class="demo-progress-bar" id="demo-progress-bar"></div>
                    </div>
                    <p class="demo-progress-text" id="demo-progress-text">Preparing wines...</p>
                </div>
            `;
        }

        // Start the install (returns immediately)
        const response = await fetchWithAuth(`${API_BASE}/demo/install`, {
            method: 'POST'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to load sample wines');
        }

        const result = await response.json();
        const total = result.total;

        // Follow progress via SSE
        const token = localStorage.getItem('winebox_token') || sessionStorage.getItem('winebox_token');
        const progressResponse = await fetch(`${API_BASE}/demo/install/progress`, {
            headers: { 'Authorization': `Bearer ${token}` },
        });

        if (!progressResponse.ok) {
            // Fallback: just wait and reload
            await new Promise(r => setTimeout(r, 5000));
            loadCellar();
            return;
        }

        const reader = progressResponse.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        function readProgress() {
            reader.read().then(({ done, value }) => {
                if (done) {
                    loadCellar();
                    return;
                }

                buffer += decoder.decode(value, { stream: true });
                const parts = buffer.split('\n\n');
                buffer = parts.pop();

                for (const part of parts) {
                    const trimmed = part.trim();
                    if (!trimmed.startsWith('data: ')) continue;

                    try {
                        const data = JSON.parse(trimmed.slice(6));
                        const bar = document.getElementById('demo-progress-bar');
                        const text = document.getElementById('demo-progress-text');

                        if (data.phase === 'done') {
                            showToast(
                                `Loaded ${data.created} sample wines (${data.bottles} bottles) from ${data.countries} countries`,
                                'success'
                            );
                            // Restore welcome panel and reload cellar
                            if (welcome && savedWelcomeHtml) welcome.innerHTML = savedWelcomeHtml;
                            loadCellar();
                            return;
                        } else if (data.phase === 'loading' && data.total > 0) {
                            const pct = Math.round((data.created / data.total) * 100);
                            if (bar) bar.style.width = pct + '%';
                            if (text) text.textContent = `Adding wines: ${data.created} of ${data.total}`;
                        } else if (data.phase === 'idle') {
                            if (welcome && savedWelcomeHtml) welcome.innerHTML = savedWelcomeHtml;
                            loadCellar();
                            return;
                        }
                    } catch (e) {
                        // Ignore parse errors
                    }
                }

                readProgress();
            }).catch(() => {
                loadCellar();
            });
        }

        readProgress();
    } catch (error) {
        showToast(error.message, 'error');
        loadCellar();
    }
}

async function removeDemoData() {
    try {
        const btn = document.getElementById('cellar-demo-remove-btn');
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Removing...';
        }

        const response = await fetchWithAuth(`${API_BASE}/demo/remove`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            throw new Error('Failed to remove sample wines');
        }

        const result = await response.json();
        showToast(`Removed ${result.wines_removed} sample wines`, 'success');
        loadCellar();
    } catch (error) {
        showToast(error.message, 'error');
        const btn = document.getElementById('cellar-demo-remove-btn');
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Remove sample wines';
        }
    }
}
