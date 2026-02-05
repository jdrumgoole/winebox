/**
 * WineBox - Wine Cellar Management Application
 * Frontend JavaScript
 */

const API_BASE = '/api';

// State
let currentPage = 'dashboard';
let authToken = localStorage.getItem('winebox_token');
let currentUser = null;

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initForms();
    initModals();
    initAuth();
    checkAuth();
});

// Authentication
function initAuth() {
    // Login form
    document.getElementById('login-form').addEventListener('submit', handleLogin);

    // Logout button
    document.getElementById('logout-btn').addEventListener('click', handleLogout);

    // Password toggle
    const passwordToggle = document.querySelector('.password-toggle');
    if (passwordToggle) {
        passwordToggle.addEventListener('click', function() {
            const passwordInput = document.getElementById('login-password');
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
    }
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
    document.getElementById('username-display').textContent = currentUser.username;
    loadDashboard();
}

async function handleLogin(e) {
    e.preventDefault();
    const form = e.target;
    const username = document.getElementById('login-username').value;
    const password = document.getElementById('login-password').value;
    const errorDiv = document.getElementById('login-error');

    errorDiv.style.display = 'none';

    try {
        const formData = new URLSearchParams();
        formData.append('username', username);
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
            throw new Error(error.detail || 'Login failed');
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

    // Search form
    document.getElementById('search-form').addEventListener('submit', handleSearch);

    // Checkout form
    document.getElementById('checkout-form').addEventListener('submit', handleCheckout);

    // Cellar filter
    document.getElementById('cellar-filter').addEventListener('change', loadCellar);
    document.getElementById('cellar-search').addEventListener('input', debounce(loadCellar, 300));

    // History filter
    document.getElementById('history-filter').addEventListener('change', loadHistory);
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
        populateFormFromScan(result);
        showToast('Label scanned successfully', 'success');
    } catch (error) {
        showToast(`Scan failed: ${error.message}`, 'error');
    } finally {
        showScanningIndicator(false);
    }
}

function populateFormFromScan(result) {
    const parsed = result.parsed;

    // Only fill in fields that are currently empty
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
            // Only update if the field is empty
            if (!input.value) {
                input.value = value;
                // Add visual indicator that field was auto-filled
                input.classList.add('auto-filled');
                setTimeout(() => input.classList.remove('auto-filled'), 2000);
            }
        }
    }
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
            formNote.textContent = 'Scanning label with OCR...';
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

async function handleCheckin(e) {
    e.preventDefault();
    const form = e.target;
    const formData = new FormData(form);

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
        showCheckinConfirmation(wine);
        form.reset();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

function showCheckinConfirmation(wine) {
    const modal = document.getElementById('checkin-confirm-modal');

    // Set wine name
    document.getElementById('checkin-confirm-name').textContent = wine.name;

    // Set image
    const imageContainer = document.getElementById('checkin-confirm-image');
    if (wine.front_label_image_path) {
        imageContainer.innerHTML = `<img src="${API_BASE}/images/${wine.front_label_image_path}" alt="Wine label">`;
    } else {
        imageContainer.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted);">No image</div>';
    }

    // Set parsed fields
    const fieldsContainer = document.getElementById('checkin-confirm-fields');
    const fields = [
        { label: 'Winery', value: wine.winery },
        { label: 'Vintage', value: wine.vintage },
        { label: 'Grape Variety', value: wine.grape_variety },
        { label: 'Region', value: wine.region },
        { label: 'Country', value: wine.country },
        { label: 'Alcohol %', value: wine.alcohol_percentage ? `${wine.alcohol_percentage}%` : null },
        { label: 'Quantity', value: wine.inventory?.quantity || 1 }
    ];

    fieldsContainer.innerHTML = fields.map(field => `
        <div class="checkin-confirm-field">
            <div class="label">${field.label}</div>
            <div class="value ${field.value ? '' : 'empty'}">${field.value || 'Not detected'}</div>
        </div>
    `).join('');

    // Set OCR text
    document.getElementById('checkin-confirm-front-ocr').textContent = wine.front_label_text || 'No text extracted';

    const backOcrSection = document.getElementById('checkin-confirm-back-ocr-section');
    if (wine.back_label_text) {
        backOcrSection.style.display = 'block';
        document.getElementById('checkin-confirm-back-ocr').textContent = wine.back_label_text;
    } else {
        backOcrSection.style.display = 'none';
    }

    // Show modal
    modal.classList.add('active');

    // Set up button handlers
    document.getElementById('checkin-confirm-done').onclick = () => {
        modal.classList.remove('active');
        navigateTo('cellar');
    };

    document.getElementById('checkin-confirm-another').onclick = () => {
        modal.classList.remove('active');
        // Reset form previews
        document.getElementById('front-preview').innerHTML = 'Tap to take photo or select image';
        document.getElementById('back-preview').innerHTML = 'Tap to take photo or select image';
    };
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
                    <div class="wine-detail-field">
                        <div class="label">OCR Text (Front Label)</div>
                        <div class="wine-detail-ocr">${wine.front_label_text}</div>
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
