/**
 * WineBox - Wine Cellar Management Application
 * Frontend JavaScript
 */

const API_BASE = '/api';

// State
let currentPage = 'dashboard';
let authToken = localStorage.getItem('winebox_token');
let currentUser = null;
let lastScanResult = null;  // Store last scan result to avoid rescanning on checkin

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initForms();
    initModals();
    initAuth();
    initAutocomplete();
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
    document.getElementById('grape-variety').value = wine.region || '';  // Use region as a hint for now
    document.getElementById('country').value = wine.country || '';

    // Fill alcohol percentage if available
    const alcoholInput = document.getElementById('alcohol');
    if (wine.abv && alcoholInput) {
        alcoholInput.value = wine.abv;
    }

    // Add visual indicator that fields were auto-filled
    const autoFilledFields = ['wine-name', 'winery', 'country', 'alcohol'];
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
        showMainApp();
    } catch (error) {
        localStorage.removeItem('winebox_token');
        authToken = null;
        showLoginPage();
    }
}

function showLoginPage() {
    document.body.classList.add('logged-out');
    document.getElementById('page-login').classList.add('active');
    document.getElementById('user-info').style.display = 'none';
}

function showMainApp() {
    document.body.classList.remove('logged-out');
    document.getElementById('page-login').classList.remove('active');
    document.getElementById('user-info').style.display = 'flex';
    document.getElementById('username-display').textContent = currentUser.email;
    loadDashboard();
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
        localStorage.setItem('winebox_token', authToken);

        form.reset();
        checkAuth();
    } catch (error) {
        errorDiv.textContent = error.message;
        errorDiv.style.display = 'block';
    }
}

function handleLogout() {
    localStorage.removeItem('winebox_token');
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
            e.preventDefault();
            const page = link.dataset.page;
            navigateTo(page);
        });
    });
}

function navigateTo(page) {
    // Update nav links
    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.toggle('active', link.dataset.page === page);
    });

    // Update pages
    document.querySelectorAll('.page').forEach(p => {
        p.classList.toggle('active', p.id === `page-${page}`);
    });

    currentPage = page;

    // Load page data
    switch (page) {
        case 'dashboard':
            loadDashboard();
            break;
        case 'cellar':
            loadCellar();
            break;
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

    // Checkout form
    document.getElementById('checkout-form').addEventListener('submit', handleCheckout);

    // Cellar filter
    document.getElementById('cellar-filter').addEventListener('change', loadCellar);
    document.getElementById('cellar-search').addEventListener('input', debounce(loadCellar, 300));

    // History filter
    document.getElementById('history-filter').addEventListener('change', loadHistory);

    // Settings forms
    document.getElementById('password-form').addEventListener('submit', handlePasswordChange);
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
        'country': parsed.country,
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
            submitBtn.textContent = submitBtn.dataset.originalText || 'Check In Wine';
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
        country: document.getElementById('country').value,
        alcohol: document.getElementById('alcohol').value,
        quantity: document.getElementById('quantity').value || '1',
        notes: document.getElementById('notes').value,
        frontLabelText: lastScanResult?.ocr?.front_label_text || '',
        backLabelText: lastScanResult?.ocr?.back_label_text || ''
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
    document.getElementById('confirm-country').value = data.country || '';
    document.getElementById('confirm-alcohol').value = data.alcohol || '';
    document.getElementById('confirm-quantity').value = data.quantity || '1';
    document.getElementById('confirm-notes').value = data.notes || '';

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
    formData.append('country', document.getElementById('confirm-country').value);
    const alcohol = document.getElementById('confirm-alcohol').value;
    if (alcohol) formData.append('alcohol_percentage', alcohol);
    formData.append('quantity', document.getElementById('confirm-quantity').value || '1');
    formData.append('notes', document.getElementById('confirm-notes').value);

    // Include pre-scanned OCR text to avoid rescanning (saves API costs)
    if (data.frontLabelText) {
        formData.append('front_label_text', data.frontLabelText);
    }
    if (data.backLabelText) {
        formData.append('back_label_text', data.backLabelText);
    }

    try {
        const response = await fetchWithAuth(`${API_BASE}/wines/checkin`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Check-in failed');
        }

        const wine = await response.json();
        showToast(`Successfully checked in: ${wine.name}`, 'success');

        // Close modal and reset form
        modal.classList.remove('active');
        document.getElementById('checkin-form').reset();
        document.getElementById('front-preview').innerHTML = 'Tap to take photo or select image';
        document.getElementById('back-preview').innerHTML = 'Tap to take photo or select image';
        clearRawLabelText();
        lastScanResult = null;
        pendingCheckinData = null;

        // Navigate to cellar
        navigateTo('cellar');
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

async function handleCheckout(e) {
    e.preventDefault();
    const wineId = document.getElementById('checkout-wine-id').value;
    const formData = new FormData(e.target);

    try {
        const response = await fetchWithAuth(`${API_BASE}/wines/${wineId}/checkout`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Check-out failed');
        }

        const wine = await response.json();
        showToast(`Successfully checked out: ${wine.name}`, 'success');
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

        // Render breakdowns
        renderChartList('by-country', summary.by_country);
        renderChartList('by-grape', summary.by_grape_variety);
        renderChartList('by-vintage', summary.by_vintage);

        // Load recent transactions
        const transResponse = await fetchWithAuth(`${API_BASE}/transactions?limit=10`);
        const transactions = await transResponse.json();
        renderActivityList(transactions);
    } catch (error) {
        console.error('Failed to load dashboard:', error);
    }
}

function renderChartList(containerId, data) {
    const container = document.getElementById(containerId);
    if (!data || Object.keys(data).length === 0) {
        container.innerHTML = '<div class="empty-state">No data yet</div>';
        return;
    }

    container.innerHTML = Object.entries(data)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 5)
        .map(([label, value]) => `
            <div class="chart-item">
                <span class="label">${label}</span>
                <span class="value">${value}</span>
            </div>
        `).join('');
}

function renderActivityList(transactions) {
    const container = document.getElementById('recent-activity');
    if (!transactions || transactions.length === 0) {
        container.innerHTML = '<div class="empty-state">No recent activity</div>';
        return;
    }

    container.innerHTML = transactions.map(t => `
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
                    ${formatDate(t.transaction_date)}
                </div>
            </div>
        </div>
    `).join('');
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

        renderWineGrid('cellar-list', wines);
    } catch (error) {
        console.error('Failed to load cellar:', error);
    }
}

function renderWineGrid(containerId, wines) {
    const container = document.getElementById(containerId);
    if (!wines || wines.length === 0) {
        container.innerHTML = '<div class="empty-state"><h3>No wines found</h3><p>Try adjusting your filters</p></div>';
        return;
    }

    container.innerHTML = wines.map(wine => {
        const quantity = wine.inventory ? wine.inventory.quantity : 0;
        const inStock = quantity > 0;

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
                        ${wine.winery ? wine.winery : ''}
                        ${wine.vintage ? ` - ${wine.vintage}` : ''}
                    </div>
                    <div class="wine-card-details">
                        ${wine.grape_variety ? `<span class="wine-tag">${wine.grape_variety}</span>` : ''}
                        ${wine.region ? `<span class="wine-tag">${wine.region}</span>` : ''}
                        ${wine.country ? `<span class="wine-tag">${wine.country}</span>` : ''}
                    </div>
                    <div class="wine-card-footer">
                        <span class="wine-quantity ${inStock ? '' : 'out-of-stock'}">
                            ${inStock ? `${quantity} bottle${quantity > 1 ? 's' : ''}` : 'Out of stock'}
                        </span>
                        ${inStock ? `<button class="btn btn-small btn-primary checkout-btn" data-wine-id="${wine.id}" data-quantity="${quantity}">Check Out</button>` : ''}
                    </div>
                </div>
            </div>
        `;
    }).join('');

    // Add click handlers
    container.querySelectorAll('.wine-card').forEach(card => {
        card.addEventListener('click', (e) => {
            if (!e.target.classList.contains('checkout-btn')) {
                showWineDetail(card.dataset.wineId);
            }
        });
    });

    container.querySelectorAll('.checkout-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            openCheckoutModal(btn.dataset.wineId, btn.dataset.quantity);
        });
    });
}

async function showWineDetail(wineId) {
    try {
        const response = await fetchWithAuth(`${API_BASE}/wines/${wineId}`);
        const wine = await response.json();

        const quantity = wine.inventory ? wine.inventory.quantity : 0;

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
                    ${wine.winery ? wine.winery : ''}
                    ${wine.vintage ? ` - ${wine.vintage}` : ''}
                </div>

                <div class="wine-detail-field">
                    <div class="label">In Stock</div>
                    <div class="value">${quantity} bottle${quantity !== 1 ? 's' : ''}</div>
                </div>

                ${wine.grape_variety ? `
                    <div class="wine-detail-field">
                        <div class="label">Grape Variety</div>
                        <div class="value">${wine.grape_variety}</div>
                    </div>
                ` : ''}

                ${wine.region ? `
                    <div class="wine-detail-field">
                        <div class="label">Region</div>
                        <div class="value">${wine.region}</div>
                    </div>
                ` : ''}

                ${wine.country ? `
                    <div class="wine-detail-field">
                        <div class="label">Country</div>
                        <div class="value">${wine.country}</div>
                    </div>
                ` : ''}

                ${wine.alcohol_percentage ? `
                    <div class="wine-detail-field">
                        <div class="label">Alcohol</div>
                        <div class="value">${wine.alcohol_percentage}%</div>
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
                    ${quantity > 0 ? `<button class="btn btn-primary" onclick="openCheckoutModal('${wine.id}', ${quantity})">Check Out</button>` : ''}
                    <button class="btn btn-danger" onclick="deleteWine('${wine.id}')">Delete Wine</button>
                </div>
            </div>

            ${wine.transactions && wine.transactions.length > 0 ? `
                <div class="wine-detail-transactions">
                    <h3>Transaction History</h3>
                    <div class="transaction-list">
                        ${wine.transactions.map(t => `
                            <div class="transaction-item">
                                <span class="transaction-type ${t.transaction_type === 'CHECK_IN' ? 'check-in' : 'check-out'}">
                                    ${t.transaction_type === 'CHECK_IN' ? 'In' : 'Out'}
                                </span>
                                <span class="transaction-quantity">${t.quantity} bottle${t.quantity > 1 ? 's' : ''}</span>
                                <span class="transaction-date">${formatDate(t.transaction_date)}</span>
                                ${t.notes ? `<span>${t.notes}</span>` : ''}
                            </div>
                        `).join('')}
                    </div>
                </div>
            ` : ''}
        `;

        openModal('wine-modal');
    } catch (error) {
        showToast('Failed to load wine details', 'error');
    }
}

function openCheckoutModal(wineId, availableQuantity) {
    document.getElementById('checkout-wine-id').value = wineId;
    document.getElementById('checkout-quantity').max = availableQuantity;
    document.getElementById('checkout-quantity').value = 1;
    document.getElementById('checkout-available').textContent = `(${availableQuantity} available)`;
    document.getElementById('checkout-notes').value = '';
    openModal('checkout-modal');
}

async function deleteWine(wineId) {
    if (!confirm('Are you sure you want to delete this wine and all its history?')) {
        return;
    }

    try {
        const response = await fetchWithAuth(`${API_BASE}/wines/${wineId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            throw new Error('Delete failed');
        }

        showToast('Wine deleted', 'success');
        closeModals();
        loadCellar();
        loadDashboard();
    } catch (error) {
        showToast('Failed to delete wine', 'error');
    }
}

// History
async function loadHistory() {
    const filter = document.getElementById('history-filter').value;
    let url = `${API_BASE}/transactions?limit=100`;
    if (filter !== 'all') {
        url += `&transaction_type=${filter}`;
    }

    try {
        const response = await fetchWithAuth(url);
        const transactions = await response.json();
        renderTransactionList(transactions);
    } catch (error) {
        console.error('Failed to load history:', error);
    }
}

function renderTransactionList(transactions) {
    const container = document.getElementById('history-list');
    if (!transactions || transactions.length === 0) {
        container.innerHTML = '<div class="empty-state"><h3>No transactions yet</h3><p>Check in some wine to get started</p></div>';
        return;
    }

    container.innerHTML = transactions.map(t => `
        <div class="transaction-item">
            <span class="transaction-type ${t.transaction_type === 'CHECK_IN' ? 'check-in' : 'check-out'}">
                ${t.transaction_type === 'CHECK_IN' ? 'In' : 'Out'}
            </span>
            <span class="transaction-wine">
                ${t.wine ? t.wine.name : 'Unknown Wine'}
                ${t.wine && t.wine.vintage ? `<span class="vintage">(${t.wine.vintage})</span>` : ''}
            </span>
            <span class="transaction-quantity">${t.quantity} bottle${t.quantity > 1 ? 's' : ''}</span>
            <span class="transaction-date">${formatDate(t.transaction_date)}</span>
        </div>
    `).join('');
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

// X-Wines Search
let xwinesFiltersLoaded = false;

async function loadXWinesFilters() {
    if (xwinesFiltersLoaded) return;

    try {
        const [typesRes, countriesRes] = await Promise.all([
            fetchWithAuth(`${API_BASE}/xwines/types`),
            fetchWithAuth(`${API_BASE}/xwines/countries`)
        ]);

        if (typesRes.ok) {
            const types = await typesRes.json();
            const typeSelect = document.getElementById('xwines-type');
            types.forEach(t => {
                const opt = document.createElement('option');
                opt.value = t;
                opt.textContent = t;
                typeSelect.appendChild(opt);
            });
        }

        if (countriesRes.ok) {
            const countries = await countriesRes.json();
            const countrySelect = document.getElementById('xwines-country');
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
    }
}

async function handleXWinesSearch(e) {
    e.preventDefault();
    const params = new URLSearchParams();
    const q = document.getElementById('xwines-q').value.trim();
    if (q.length < 2) {
        showToast('Please enter at least 2 characters', 'error');
        return;
    }
    params.append('q', q);

    const wineType = document.getElementById('xwines-type').value;
    if (wineType) params.append('wine_type', wineType);

    const country = document.getElementById('xwines-country').value;
    if (country) params.append('country', country);

    const limit = document.getElementById('xwines-limit').value;
    params.append('limit', limit);

    try {
        const response = await fetchWithAuth(`${API_BASE}/xwines/search?${params}`);
        if (!response.ok) throw new Error('Search failed');
        const data = await response.json();
        renderXWinesGrid('xwines-results', data.results, data.total);

        // Update filter dropdowns with facet counts if available
        if (data.facets) {
            updateFilterCounts(data.facets);
        }
    } catch (error) {
        showToast('X-Wines search failed', 'error');
    }
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
        const ratingDisplay = wine.avg_rating
            ? `<span class="xwines-rating">${'★'.repeat(Math.round(wine.avg_rating))}${'☆'.repeat(5 - Math.round(wine.avg_rating))} ${wine.avg_rating.toFixed(1)}</span><span class="xwines-rating-count">(${wine.rating_count})</span>`
            : '<span class="xwines-rating xwines-no-rating">No ratings</span>';

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
                    ${ratingDisplay}
                </div>
            </div>
        `;
    }).join('');

    container.querySelectorAll('.xwines-card').forEach(card => {
        card.addEventListener('click', () => {
            showXWinesDetail(card.dataset.xwineId);
        });
    });
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
