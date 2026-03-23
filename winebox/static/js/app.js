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
let authToken = localStorage.getItem('winebox_token') || sessionStorage.getItem('winebox_token');
let currentUser = null;
let lastScanResult = null;  // Store last scan result to avoid rescanning on checkin
let cellarViewMode = 'cards';
let cellarLastWines = [];
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

async function showMainApp() {
    document.body.classList.remove('logged-out');
    document.getElementById('page-login').classList.remove('active');
    document.getElementById('user-info').style.display = 'flex';
    document.getElementById('username-display').textContent = currentUser.email;

    const adminLink = document.getElementById('admin-link');
    if (adminLink) {
        adminLink.style.display = currentUser.is_admin ? '' : 'none';
    }

    // Identify user for analytics
    analytics.identify(currentUser.id, { email: currentUser.email });

    // Check if URL hash specifies a valid app page
    const hashPage = window.location.hash.slice(1).split('?')[0];
    if (hashPage && APP_PAGES.includes(hashPage)) {
        navigateTo(hashPage);
        return;
    }

    // Always start on Dashboard — empty cellar state has a call-to-action

    // Only navigate to dashboard if user hasn't navigated elsewhere
    const finalHash = window.location.hash.slice(1).split('?')[0];
    if (!finalHash || !APP_PAGES.includes(finalHash)) {
        navigateTo('dashboard');
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
    const hashPage = window.location.hash.slice(1).split('?')[0];

    // If it's a valid app page and user is logged in, navigate to it
    if (hashPage && APP_PAGES.includes(hashPage) && authToken && currentUser) {
        navigateTo(hashPage);
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
    // Update nav links
    document.querySelectorAll('.nav-link').forEach(link => {
        const isActive = link.dataset.page === page;
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
    if (window.location.hash !== `#${page}`) {
        history.replaceState(null, '', `#${page}`);
    }

    // Track page view
    analytics.capture('page_view', { page: page });

    // Load page data
    switch (page) {
        case 'dashboard':
            loadDashboard();
            break;
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
        case 'history':
            loadHistory();
            break;
        case 'search':
            // Search results loaded on form submit
            break;
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

    // Search form
    document.getElementById('search-form').addEventListener('submit', handleSearch);

    // X-Wines search form
    document.getElementById('xwines-search-form').addEventListener('submit', handleXWinesSearch);

    // Remove form
    document.getElementById('remove-form').addEventListener('submit', handleRemoval);

    // Reason picker cards
    document.querySelectorAll('.reason-card').forEach(card => {
        card.addEventListener('click', () => selectRemovalReason(card.dataset.reason));
    });

    // Back button in remove modal
    document.getElementById('remove-back-btn').addEventListener('click', resetRemovalPicker);

    // Cellar filter
    document.getElementById('cellar-filter').addEventListener('change', loadCellar);
    document.getElementById('cellar-search').addEventListener('input', debounce(loadCellar, 300));

    // Cellar view toggle
    document.getElementById('cellar-view-cards')?.addEventListener('click', () => setCellarViewMode('cards'));
    document.getElementById('cellar-view-table')?.addEventListener('click', () => setCellarViewMode('table'));

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

    try {
        const response = await fetchWithAuth(`${API_BASE}/wines/met`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to record wine');
        }

        const wine = await response.json();
        showToast(`Recorded: ${wine.name}`, 'success');

        // Track record event
        analytics.capture('frontend_wine_met_recorded', {
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

        // Navigate to met wines
        navigateTo('met');
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
    const fieldMap = { DRINK: 'drink', SELL: 'sell', GIFT: 'gift', OTHER: 'other' };
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
    const btnLabels = { DRINK: 'Record', SELL: 'Record Sale', GIFT: 'Record Gift', OTHER: 'Record' };
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
        const reasonLabels = { DRINK: 'Recorded', SELL: 'Sale recorded', GIFT: 'Gift recorded', OTHER: 'Removal recorded' };
        showToast(`${reasonLabels[reason] || 'Removed'}: ${wine.name}`, 'success');
        closeModals();
        loadCellar();
        loadDashboard();
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

// Dashboard
async function loadDashboard() {
    try {
        // Load summary
        const summaryResponse = await fetchWithAuth(`${API_BASE}/cellar/summary`);
        const summary = await summaryResponse.json();

        document.getElementById('stat-total-bottles').textContent = summary.total_bottles;
        document.getElementById('stat-unique-wines').textContent = summary.unique_wines;
        document.getElementById('stat-total-tracked').textContent = summary.total_wines_tracked;

        // Check demo data status and show appropriate UI
        await updateDemoBanner(summary.total_bottles);

        // Render charts
        renderDashboardCharts(summary);

        // Load met summary
        try {
            const metResponse = await fetchWithAuth(`${API_BASE}/met/summary`);
            const metSummary = await metResponse.json();
            document.getElementById('stat-wines-met').textContent = metSummary.total_met;
        } catch {
            document.getElementById('stat-wines-met').textContent = '0';
        }

        // Load recent transactions
        const transResponse = await fetchWithAuth(`${API_BASE}/transactions?limit=10`);
        const transactions = await transResponse.json();
        renderActivityList(transactions);
    } catch (error) {
        console.error('Failed to load dashboard:', error);
    }
}

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
    const filter = document.getElementById('cellar-filter').value;
    const search = document.getElementById('cellar-search').value;

    let url = `${API_BASE}/wines?`;
    if (filter === 'in-stock') {
        url += 'in_stock=true&';
    } else if (filter === 'out-of-stock') {
        url += 'in_stock=false&';
    }

    try {
        const response = await fetchWithAuth(url);
        let wines = await response.json();

        // Client-side search filter
        if (search) {
            const searchLower = search.toLowerCase();
            wines = wines.filter(w =>
                w.name.toLowerCase().includes(searchLower) ||
                (w.winery && w.winery.toLowerCase().includes(searchLower)) ||
                (w.grape_variety && w.grape_variety.toLowerCase().includes(searchLower))
            );
        }

        cellarLastWines = wines;
        renderCellarView();
    } catch (error) {
        console.error('Failed to load cellar:', error);
    }
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

function setCellarViewMode(mode) {
    cellarViewMode = mode;

    document.getElementById('cellar-view-cards').classList.toggle('active', mode === 'cards');
    document.getElementById('cellar-view-table').classList.toggle('active', mode === 'table');

    // Toggle wine-grid class: cards need the grid layout, table needs full width
    const cellarList = document.getElementById('cellar-list');
    if (mode === 'table') {
        cellarList.classList.remove('wine-grid');
    } else {
        cellarList.classList.add('wine-grid');
    }

    if (cellarLastWines.length > 0) {
        renderCellarView();
    }
}

function renderCellarTable(containerId, wines) {
    const container = document.getElementById(containerId);
    if (!wines || wines.length === 0) {
        const hasFilters = document.getElementById('cellar-filter').value !== 'all' ||
                          document.getElementById('cellar-search').value.trim() !== '';
        if (hasFilters) {
            container.innerHTML = '<div class="empty-state"><h3>No wines found</h3><p>Try adjusting your filters</p></div>';
        } else {
            container.innerHTML = '<div class="empty-state"><h3>Your cellar is empty</h3><p>Add your first wine to get started!</p><a href="#" data-page="checkin" class="btn btn-primary" style="margin-top:1rem">Add Wine</a></div>';
        }
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
        const hasFilters = document.getElementById('cellar-filter').value !== 'all' ||
                          document.getElementById('cellar-search').value.trim() !== '';
        if (hasFilters) {
            container.innerHTML = '<div class="empty-state"><h3>No wines found</h3><p>Try adjusting your filters</p></div>';
        } else {
            container.innerHTML = '<div class="empty-state"><h3>Your cellar is empty</h3><p>Add your first wine to get started!</p><a href="#" data-page="checkin" class="btn btn-primary" style="margin-top:1rem">Add Wine</a></div>';
        }
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
                        <div class="collapsible-header" onclick="toggleWineDetailLabelText(this)">
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
                    ${quantity > 0 ? `<button class="btn btn-primary" onclick="openRemoveModal('${wine.id}', ${quantity})">Remove</button>` : ''}
                    <button class="btn btn-danger" onclick="deleteWine('${wine.id}')">Delete Wine</button>
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
            loadDashboard();
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
        loadDashboard();
        resetImportPage();
    } catch (error) {
        btn.disabled = false;
        btn.textContent = 'Delete Everything';
        showToast(error.message, 'error');
    }
}

// Export Dropdowns
function initExportDropdowns() {
    // Initialize cellar export dropdown
    initExportDropdown('cellar-export-dropdown', 'cellar-export-btn');

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
 * Parse CSV client-side with PapaParse streaming, then upload metadata to server.
 */
async function handleCsvImport(file) {
    try {
        showToast('Parsing CSV...', 'info');
        const parsed = await parseCsvFile(file);

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
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Upload failed');
        }

        const data = await response.json();
        currentImportBatchId = data.batch_id;
        currentImportData = data;

        renderMappingStep(data);
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

        renderMappingStep(data);
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
        quantity:            { label: 'Bottles',              hint: 'How many bottles you have of this wine', group: 'details' },
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
                <span class="import-not-mapped" style="display:${isSkipped ? 'block' : 'none'}">Won't be imported</span>
            </td>
            <td class="import-arrow-cell">&#x2192;</td>
            <td>
                <div class="import-mapping-controls">
                    ${badgeHtml}
                    <select class="import-mapping-select" data-header="${escapeHtml(header)}">
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
                    <button type="button" class="btn btn-small import-skip-btn ${isSkipped ? 'active' : ''}" data-header="${escapeHtml(header)}">Ignore</button>
                </div>
                <span class="import-field-hint" data-header="${escapeHtml(header)}">${initialHint}</span>
            </td>
        </tr>`;
    }
    tableHtml += '</tbody></table>';
    document.getElementById('import-mapping-table-container').innerHTML = tableHtml;

    // Update "already matched" indicators across all dropdowns
    function updateMatchedIndicators() {
        const currentUsed = new Set();
        document.querySelectorAll('.import-mapping-select').forEach(sel => {
            const row = sel.closest('.import-mapping-row');
            const skipBtn = row.querySelector('.import-skip-btn');
            if (!skipBtn.classList.contains('active') && IMPORT_FIELD_META[sel.value]) {
                currentUsed.add(sel.value);
            }
        });
        document.querySelectorAll('.import-mapping-select').forEach(sel => {
            const selectedVal = sel.value;
            sel.querySelectorAll('option').forEach(opt => {
                const key = opt.value;
                const meta = IMPORT_FIELD_META[key];
                if (!meta) return;
                const inUse = currentUsed.has(key) && selectedVal !== key;
                opt.textContent = inUse ? `${meta.label}  \u2713 already matched` : meta.label;
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
        });
    });

    // Ignore button toggle
    document.querySelectorAll('.import-skip-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const header = e.target.dataset.header;
            const row = document.querySelector(`.import-mapping-row[data-header="${header}"]`);
            const notMapped = row.querySelector('.import-not-mapped');
            const isActive = btn.classList.toggle('active');
            row.classList.toggle('skipped', isActive);
            notMapped.style.display = isActive ? 'block' : 'none';
            updateMatchedIndicators();
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
        document.getElementById('import-step-upload').style.display = 'none';
        document.getElementById('import-step-map').style.display = 'none';
        document.getElementById('import-step-progress').style.display = 'block';
        document.getElementById('import-step-results').style.display = 'none';

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

        const skipEnrichmentCheckbox = document.getElementById('import-skip-enrichment');
        const skipEnrichment = !!skipEnrichmentCheckbox && skipEnrichmentCheckbox.checked;

        // Stream processing with progress
        const processResponse = await fetchWithAuth(`${API_BASE}/import/${currentImportBatchId}/process-stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ skip_non_wine: true, default_quantity: 1, skip_enrichment: skipEnrichment })
        });

        if (!processResponse.ok) {
            const error = await processResponse.json();
            throw new Error(error.detail || 'Processing failed');
        }

        const result = await readImportStream(processResponse);
        showImportResults(result);
    } catch (error) {
        showToast(error.message, 'error');
        // Restore mapping step if progress was shown prematurely
        document.getElementById('import-step-progress').style.display = 'none';
        document.getElementById('import-step-map').style.display = 'block';
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
    document.getElementById('import-step-upload').style.display = 'none';
    document.getElementById('import-step-map').style.display = 'none';
    document.getElementById('import-step-progress').style.display = 'none';
    document.getElementById('import-step-results').style.display = 'block';

    // Store skipped rows for modal access
    window._lastSkippedRows = result.skipped_rows || [];

    const skippedValue = (result.rows_skipped > 0 && window._lastSkippedRows.length > 0)
        ? `<a href="#" onclick="showSkippedRows(); return false;" style="color:var(--primary-color);text-decoration:underline;">${result.rows_skipped}</a>`
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
                            toast.textContent = `Enrichment complete: ${data.enriched}/${data.total} wines matched`;
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
    document.getElementById('import-step-upload').style.display = 'block';
    document.getElementById('import-step-map').style.display = 'none';
    document.getElementById('import-step-progress').style.display = 'none';
    document.getElementById('import-step-results').style.display = 'none';
    document.getElementById('import-file-input').value = '';
    currentImportBatchId = null;
    currentImportData = null;
    pendingCsvRows = null;
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
}

function resetAddToCellarWizard() {
    // Show cards, hide all sub-wizards
    document.getElementById('entry-path-cards').style.display = '';
    document.querySelectorAll('.add-cellar-subwizard').forEach(el => el.style.display = 'none');
    document.querySelectorAll('.entry-path-card').forEach(c => c.classList.remove('active'));
    selectedMetWineId = null;

    // Hide breadcrumb, show subtitle
    document.getElementById('add-cellar-breadcrumb').style.display = 'none';
    document.getElementById('add-cellar-subtitle').style.display = '';
}

function selectEntryPath(path) {
    // Hide cards, show selected sub-wizard
    document.getElementById('entry-path-cards').style.display = 'none';
    document.querySelectorAll('.add-cellar-subwizard').forEach(el => el.style.display = 'none');

    document.querySelectorAll('.entry-path-card').forEach(c => {
        c.classList.toggle('active', c.dataset.path === path);
    });

    // Show breadcrumb, hide subtitle
    const breadcrumb = document.getElementById('add-cellar-breadcrumb');
    breadcrumb.style.display = '';
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
    formData.append('quantity', document.getElementById('scan-quantity').value || '1');

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
    formData.append('quantity', document.getElementById('manual-quantity').value || '1');

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

async function updateDemoBanner(totalBottles) {
    const existingBanner = document.getElementById('demo-banner');
    if (existingBanner) existingBanner.remove();

    const existingWelcome = document.getElementById('demo-welcome');
    if (existingWelcome) existingWelcome.remove();

    try {
        const response = await fetchWithAuth(`${API_BASE}/demo/status`);
        const status = await response.json();

        if (totalBottles === 0 && !status.installed) {
            // Empty cellar, no demo data — show welcome prompt
            showDemoWelcome();
        } else if (status.installed) {
            // Demo data present — show removable banner
            showDemoBanner(status.wine_count, status.bottle_count);
        }
    } catch {
        // Demo endpoint not available — skip silently
    }
}

function showDemoWelcome() {
    const dashboard = document.getElementById('page-dashboard');
    const statsGrid = document.getElementById('stats-grid');

    const welcome = document.createElement('div');
    welcome.id = 'demo-welcome';
    welcome.className = 'demo-welcome';
    welcome.innerHTML = `
        <div class="demo-welcome-content">
            <h3>Welcome to WineBox</h3>
            <p>Your cellar is empty. Load some sample wines to explore what WineBox can do, or add your first wine by scanning a label.</p>
            <div class="demo-welcome-actions">
                <button class="btn btn-primary" id="demo-install-btn">
                    Load sample wines
                </button>
                <a href="#" data-page="checkin" class="btn btn-secondary">
                    Add my own wine
                </a>
            </div>
            <p class="demo-hint">Sample wines can be removed at any time without affecting your own wines.</p>
        </div>
    `;

    dashboard.insertBefore(welcome, statsGrid.nextSibling);
    document.getElementById('demo-install-btn').addEventListener('click', installDemoData);
}

function showDemoBanner(wineCount, bottleCount) {
    const header = document.getElementById('dashboard-header');

    const banner = document.createElement('div');
    banner.id = 'demo-banner';
    banner.className = 'demo-banner';
    banner.innerHTML = `
        <span>Sample wines (${wineCount} wines, ${bottleCount} bottles)</span>
        <button class="btn btn-sm btn-outline" id="demo-remove-btn">Remove</button>
    `;

    header.appendChild(banner);
    document.getElementById('demo-remove-btn').addEventListener('click', removeDemoData);
}

async function installDemoData() {
    try {
        const btn = document.getElementById('demo-install-btn');
        if (btn) btn.disabled = true;

        // Replace the welcome content with a progress bar
        const welcome = document.getElementById('demo-welcome');
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
            loadDashboard();
            return;
        }

        const reader = progressResponse.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        function readProgress() {
            reader.read().then(({ done, value }) => {
                if (done) {
                    loadDashboard();
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
                            if (bar) bar.style.width = '100%';
                            if (text) text.textContent = `Done! ${data.created} wines loaded.`;
                            showToast(
                                `Loaded ${data.created} sample wines (${data.bottles} bottles) from ${data.countries} countries`,
                                'success'
                            );
                            setTimeout(() => loadDashboard(), 500);
                            return;
                        } else if (data.phase === 'loading' && data.total > 0) {
                            const pct = Math.round((data.created / data.total) * 100);
                            if (bar) bar.style.width = pct + '%';
                            if (text) text.textContent = `Adding wines: ${data.created} of ${data.total}`;
                        } else if (data.phase === 'idle') {
                            loadDashboard();
                            return;
                        }
                    } catch (e) {
                        // Ignore parse errors
                    }
                }

                readProgress();
            }).catch(() => {
                loadDashboard();
            });
        }

        readProgress();
    } catch (error) {
        showToast(error.message, 'error');
        loadDashboard();
    }
}

async function removeDemoData() {
    try {
        const btn = document.querySelector('.demo-banner .btn-outline');
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
        loadDashboard();
    } catch (error) {
        showToast(error.message, 'error');
        const btn = document.querySelector('.demo-banner .btn-outline');
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Remove sample wines';
        }
    }
}
