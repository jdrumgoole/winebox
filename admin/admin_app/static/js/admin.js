/**
 * WineBox Admin Panel JavaScript (Standalone)
 */

// ---------------------------------------------------------------------------
// Auth helpers
// ---------------------------------------------------------------------------

function getAuthToken() {
    return localStorage.getItem('winebox_admin_token');
}

function showAdminPanel() {
    document.getElementById('login-section').style.display = 'none';
    document.getElementById('admin-content').style.display = 'block';
    loadInfo();
    refreshData();
}

function showLoginForm() {
    localStorage.removeItem('winebox_admin_token');
    document.getElementById('login-section').style.display = 'block';
    document.getElementById('admin-content').style.display = 'none';
}

async function checkAuth() {
    const token = getAuthToken();
    if (!token) { showLoginForm(); return false; }
    return true;
}

async function apiRequest(endpoint, options = {}) {
    const token = getAuthToken();
    const headers = { 'Authorization': `Bearer ${token}`, ...options.headers };
    const response = await fetch(endpoint, { ...options, headers });
    if (response.status === 401 || response.status === 403) {
        showLoginForm();
        throw new Error('Not authorized');
    }
    return response;
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function formatDate(dateString) {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit'
    });
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Server info
// ---------------------------------------------------------------------------

async function loadInfo() {
    try {
        const response = await apiRequest('/api/info');
        if (!response.ok) throw new Error('Failed to load info');
        const data = await response.json();
        document.getElementById('info-database').textContent = data.database;
        document.getElementById('info-db-server').textContent = data.db_server;
        document.getElementById('info-app-url').textContent = data.app_url;
    } catch (error) {
        console.error('Error loading info:', error);
    }
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------

async function loadStats() {
    try {
        const response = await apiRequest('/api/stats');
        if (!response.ok) throw new Error('Failed to load stats');
        const data = await response.json();
        document.getElementById('stat-total-users').textContent = data.users.total;
        document.getElementById('stat-active-users').textContent = data.users.active;
        document.getElementById('stat-verified-users').textContent = data.users.verified;
        document.getElementById('stat-total-wines').textContent = data.wines.in_stock;
        document.getElementById('stat-total-bottles').textContent = data.wines.total_bottles;
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

// ---------------------------------------------------------------------------
// Users — read-only tab
// ---------------------------------------------------------------------------

function renderReadonlyTable(users) {
    if (users.length === 0) return '<p>No users found.</p>';
    return `
        <table class="users-table">
            <thead>
                <tr>
                    <th>Email</th>
                    <th>Status</th>
                    <th>Role</th>
                    <th>Created</th>
                    <th>Last Login</th>
                    <th>Cellar</th>
                </tr>
            </thead>
            <tbody>
                ${users.map(user => `
                    <tr>
                        <td>
                            <strong>${escapeHtml(user.email)}</strong>
                            ${user.full_name ? `<br><span class="timestamp">${escapeHtml(user.full_name)}</span>` : ''}
                        </td>
                        <td>
                            ${user.is_active
                                ? '<span class="badge badge-success">Active</span>'
                                : '<span class="badge badge-danger">Inactive</span>'}
                            ${user.is_verified
                                ? '<span class="badge badge-success">Verified</span>'
                                : '<span class="badge badge-warning">Unverified</span>'}
                        </td>
                        <td>
                            ${user.is_superuser
                                ? '<span class="badge badge-primary">Admin</span>'
                                : '<span class="badge">User</span>'}
                        </td>
                        <td class="timestamp">${formatDate(user.created_at)}</td>
                        <td class="timestamp">${formatDate(user.last_login)}</td>
                        <td class="cellar-size">${user.cellar_size} bottles</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
}

// ---------------------------------------------------------------------------
// Users — manage tab
// ---------------------------------------------------------------------------

function renderManageTable(users) {
    if (users.length === 0) return '<p>No users found.</p>';
    return `
        <table class="users-table">
            <thead>
                <tr>
                    <th>Email</th>
                    <th>Status</th>
                    <th>Role</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                ${users.map(user => `
                    <tr>
                        <td><strong>${escapeHtml(user.email)}</strong></td>
                        <td>
                            ${user.is_active
                                ? '<span class="badge badge-success">Active</span>'
                                : '<span class="badge badge-danger">Inactive</span>'}
                            ${user.is_verified
                                ? '<span class="badge badge-success">Verified</span>'
                                : '<span class="badge badge-warning">Unverified</span>'}
                        </td>
                        <td>
                            ${user.is_superuser
                                ? '<span class="badge badge-primary">Admin</span>'
                                : '<span class="badge">User</span>'}
                        </td>
                        <td class="actions-cell">
                            <button class="actions-menu-btn" data-toggle="actions-menu">Actions</button>
                            <div class="actions-dropdown">
                                ${user.is_active
                                    ? `<button data-action="deactivate" data-user-id="${user.id}">Disable Account</button>`
                                    : `<button data-action="activate" data-user-id="${user.id}">Enable Account</button>`}
                                ${user.is_superuser
                                    ? `<button data-action="remove-admin" data-user-id="${user.id}">Remove Admin</button>`
                                    : `<button data-action="make-admin" data-user-id="${user.id}">Make Admin</button>`}
                                ${!user.is_verified
                                    ? `<button data-action="verify" data-user-id="${user.id}">Verify Email</button>`
                                    : ''}
                                <div class="dropdown-divider"></div>
                                <button class="action-danger" data-action="delete" data-user-id="${user.id}" data-user-email="${escapeHtml(user.email)}">Delete User</button>
                            </div>
                        </td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
}

// ---------------------------------------------------------------------------
// Load users into both tabs
// ---------------------------------------------------------------------------

let _cachedUsers = [];
let _manageListenersAttached = false;

async function loadUsers() {
    const readonlyContainer = document.getElementById('users-readonly-container');
    const manageContainer = document.getElementById('users-manage-container');

    try {
        const response = await apiRequest('/api/users');
        if (!response.ok) throw new Error('Failed to load users');
        const data = await response.json();
        _cachedUsers = data.users;

        readonlyContainer.innerHTML = renderReadonlyTable(_cachedUsers);

        // Skip manage table re-render if a dropdown is currently open
        const hasOpenDropdown = manageContainer.querySelector('.actions-dropdown.open');
        if (!hasOpenDropdown) {
            manageContainer.innerHTML = renderManageTable(_cachedUsers);
        }

        // Attach delegated listeners once (they survive innerHTML changes via delegation)
        if (!_manageListenersAttached) {
            _manageListenersAttached = true;

            manageContainer.addEventListener('click', handleAdminAction);

            manageContainer.addEventListener('click', function(e) {
                const toggleBtn = e.target.closest('[data-toggle="actions-menu"]');
                if (!toggleBtn) return;
                e.stopPropagation();
                const dropdown = toggleBtn.nextElementSibling;
                document.querySelectorAll('.actions-dropdown.open').forEach(d => {
                    if (d !== dropdown) d.classList.remove('open');
                });
                dropdown.classList.toggle('open');
            });
        }
    } catch (error) {
        console.error('Error loading users:', error);
        const errHtml = '<div class="error-message">Failed to load users.</div>';
        readonlyContainer.innerHTML = errHtml;
        manageContainer.innerHTML = errHtml;
    }
}

async function refreshData() {
    await Promise.all([loadStats(), loadUsers()]);
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

function setupTabs() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            // Deactivate all
            tabBtns.forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
            // Activate clicked
            btn.classList.add('active');
            document.getElementById(btn.dataset.tab).classList.add('active');
        });
    });
}

// ---------------------------------------------------------------------------
// Toast & Confirm
// ---------------------------------------------------------------------------

function showAdminToast(message, type = 'success') {
    let container = document.getElementById('admin-toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'admin-toast-container';
        container.style.cssText = 'position:fixed;top:1rem;right:1rem;z-index:10000;display:flex;flex-direction:column;gap:0.5rem;';
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.textContent = message;
    const bg = type === 'error' ? '#dc3545' : type === 'success' ? '#28a745' : '#6c757d';
    toast.style.cssText = `padding:0.75rem 1.5rem;border-radius:6px;color:#fff;font-size:0.9rem;max-width:400px;box-shadow:0 2px 8px rgba(0,0,0,0.2);background:${bg};`;
    container.appendChild(toast);
    setTimeout(() => { toast.remove(); }, 4000);
}

function showAdminConfirm(message, onConfirm) {
    let overlay = document.getElementById('admin-confirm-overlay');
    if (overlay) overlay.remove();

    overlay = document.createElement('div');
    overlay.id = 'admin-confirm-overlay';
    overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center;';

    const dialog = document.createElement('div');
    dialog.style.cssText = 'background:#fff;border-radius:8px;padding:2rem;max-width:420px;width:90%;box-shadow:0 4px 20px rgba(0,0,0,0.3);';
    dialog.innerHTML = `
        <h3 style="margin:0 0 1rem;color:#dc3545;font-family:Playfair Display,serif;">Confirm Action</h3>
        <p style="margin:0 0 1.5rem;line-height:1.5;">${escapeHtml(message)}</p>
        <div style="display:flex;gap:0.75rem;justify-content:flex-end;">
            <button class="btn-admin btn-admin-outline" id="admin-confirm-no">Cancel</button>
            <button class="btn-admin btn-admin-danger" id="admin-confirm-yes">Confirm</button>
        </div>
    `;
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    document.getElementById('admin-confirm-yes').addEventListener('click', () => { overlay.remove(); onConfirm(); });
    document.getElementById('admin-confirm-no').addEventListener('click', () => { overlay.remove(); });
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
}

// ---------------------------------------------------------------------------
// Admin actions (manage tab)
// ---------------------------------------------------------------------------

async function handleAdminAction(e) {
    const btn = e.target.closest('button[data-action]');
    if (!btn) return;

    const action = btn.dataset.action;
    const userId = btn.dataset.userId;
    const email = btn.dataset.userEmail || '';

    if (action === 'delete') {
        showAdminConfirm(`Delete user ${email} and ALL their data?\n\nThis cannot be undone.`, async () => {
            try {
                const resp = await apiRequest(`/api/users/${userId}`, { method: 'DELETE' });
                if (!resp.ok) {
                    const err = await resp.json();
                    showAdminToast(err.detail || 'Failed to delete user', 'error');
                    return;
                }
                const result = await resp.json();
                showAdminToast(`Deleted ${email}: ${result.wines_deleted} wines, ${result.transactions_deleted} transactions removed.`);
            } catch (e) {
                showAdminToast('Error deleting user', 'error');
            }
            await refreshData();
        });
        return;
    }

    try {
        const resp = await apiRequest(`/api/users/${userId}/${action}`, { method: 'PATCH' });
        if (!resp.ok) {
            const err = await resp.json();
            showAdminToast(err.detail || `Failed: ${action}`, 'error');
            return;
        }
        const labels = {
            'activate': 'User enabled',
            'deactivate': 'User disabled',
            'make-admin': 'Admin role granted',
            'remove-admin': 'Admin role removed',
            'verify': 'User verified',
        };
        showAdminToast(labels[action] || `Action ${action} completed`);
    } catch (e) {
        showAdminToast(`Error: ${action}`, 'error');
        return;
    }
    await refreshData();
}

// ---------------------------------------------------------------------------
// Add User form
// ---------------------------------------------------------------------------

function setupAddUserForm() {
    const form = document.getElementById('add-user-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const errorEl = document.getElementById('add-user-error');
        const successEl = document.getElementById('add-user-success');
        errorEl.style.display = 'none';
        successEl.style.display = 'none';

        const email = document.getElementById('new-user-email').value.trim();
        const password = document.getElementById('new-user-password').value;
        const isAdmin = document.getElementById('new-user-admin').checked;

        try {
            const resp = await apiRequest('/api/users', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password, is_admin: isAdmin }),
            });

            if (!resp.ok) {
                const err = await resp.json();
                errorEl.textContent = err.detail || 'Failed to create user';
                errorEl.style.display = 'block';
                return;
            }

            const result = await resp.json();
            successEl.textContent = `User ${result.email} created successfully.`;
            successEl.style.display = 'block';
            form.reset();
            showAdminToast(`User ${result.email} created`);
            await refreshData();
        } catch (err) {
            errorEl.textContent = 'Network error. Please try again.';
            errorEl.style.display = 'block';
        }
    });
}

// ---------------------------------------------------------------------------
// Login
// ---------------------------------------------------------------------------

function setupLoginForm() {
    const loginForm = document.getElementById('login-form');
    if (!loginForm) return;

    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('login-email').value;
        const password = document.getElementById('login-password').value;
        const errorEl = document.getElementById('login-error');

        try {
            const formData = new URLSearchParams();
            formData.append('username', email);
            formData.append('password', password);

            const resp = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: formData,
            });

            if (!resp.ok) {
                const data = await resp.json();
                errorEl.textContent = data.detail || 'Login failed';
                errorEl.style.display = 'block';
                return;
            }

            const data = await resp.json();
            localStorage.setItem('winebox_admin_token', data.access_token);
            errorEl.style.display = 'none';
            showAdminPanel();
        } catch (err) {
            errorEl.textContent = 'Network error. Please try again.';
            errorEl.style.display = 'block';
        }
    });
}

// ---------------------------------------------------------------------------
// Nav handlers
// ---------------------------------------------------------------------------

function setupNavHandlers() {
    const refreshLink = document.getElementById('refresh-link');
    if (refreshLink) {
        refreshLink.addEventListener('click', (e) => { e.preventDefault(); refreshData(); });
    }

    const logoutLink = document.getElementById('logout-link');
    if (logoutLink) {
        logoutLink.addEventListener('click', async (e) => {
            e.preventDefault();
            try { await apiRequest('/api/auth/logout', { method: 'POST' }); } catch (err) { /* ignore */ }
            showLoginForm();
        });
    }
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

async function init() {
    setupLoginForm();
    setupNavHandlers();
    setupTabs();
    setupAddUserForm();

    // Close dropdowns when clicking outside
    document.addEventListener('click', function() {
        document.querySelectorAll('.actions-dropdown.open').forEach(d => d.classList.remove('open'));
    });

    const isAuth = await checkAuth();
    if (!isAuth) return;

    showAdminPanel();
    setInterval(refreshData, 30000);
}

document.addEventListener('DOMContentLoaded', init);
