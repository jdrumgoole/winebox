/**
 * WineBox Admin Panel JavaScript (Standalone)
 */

// Get auth token from localStorage
function getAuthToken() {
    return localStorage.getItem('winebox_admin_token');
}

// Show admin panel, hide login
function showAdminPanel() {
    document.getElementById('login-section').style.display = 'none';
    document.getElementById('admin-content').style.display = 'block';
    refreshData();
}

// Show login form, hide admin panel
function showLoginForm() {
    localStorage.removeItem('winebox_admin_token');
    document.getElementById('login-section').style.display = 'block';
    document.getElementById('admin-content').style.display = 'none';
}

// Check if user is authenticated
async function checkAuth() {
    const token = getAuthToken();
    if (!token) {
        showLoginForm();
        return false;
    }
    return true;
}

// Make authenticated API request
async function apiRequest(endpoint, options = {}) {
    const token = getAuthToken();
    const headers = {
        'Authorization': `Bearer ${token}`,
        ...options.headers
    };

    const response = await fetch(endpoint, {
        ...options,
        headers
    });

    if (response.status === 401 || response.status === 403) {
        showLoginForm();
        throw new Error('Not authorized');
    }

    return response;
}

// Format date for display
function formatDate(dateString) {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// Load admin stats
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

// Load users list
async function loadUsers() {
    const container = document.getElementById('users-container');

    try {
        const response = await apiRequest('/api/users');
        if (!response.ok) throw new Error('Failed to load users');

        const data = await response.json();
        const users = data.users;

        if (users.length === 0) {
            container.innerHTML = '<p>No users found.</p>';
            return;
        }

        const tableHtml = `
            <table class="users-table">
                <thead>
                    <tr>
                        <th>Email</th>
                        <th>Status</th>
                        <th>Role</th>
                        <th>Created</th>
                        <th>Last Login</th>
                        <th>Cellar Size</th>
                        <th>Actions</th>
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
                            <td class="actions-cell">
                                ${user.is_active
                                    ? `<button class="btn-admin btn-admin-outline" data-action="deactivate" data-user-id="${user.id}">Disable</button>`
                                    : `<button class="btn-admin btn-admin-success" data-action="activate" data-user-id="${user.id}">Enable</button>`}
                                ${user.is_superuser
                                    ? `<button class="btn-admin btn-admin-outline" data-action="remove-admin" data-user-id="${user.id}">Remove Admin</button>`
                                    : `<button class="btn-admin btn-admin-outline" data-action="make-admin" data-user-id="${user.id}">Make Admin</button>`}
                                ${!user.is_verified
                                    ? `<button class="btn-admin btn-admin-success" data-action="verify" data-user-id="${user.id}">Verify</button>`
                                    : ''}
                                <button class="btn-admin btn-admin-danger" data-action="delete" data-user-id="${user.id}" data-user-email="${escapeHtml(user.email)}">Delete</button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;

        container.innerHTML = tableHtml;

        // Attach click handlers via delegation (CSP blocks inline onclick)
        container.addEventListener('click', handleAdminAction);
    } catch (error) {
        console.error('Error loading users:', error);
        container.innerHTML = `
            <div class="error-message">
                Failed to load users. Make sure you have admin privileges.
            </div>
        `;
    }
}

// Escape HTML to prevent XSS
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Refresh all admin data (stats + users)
async function refreshData() {
    await Promise.all([
        loadStats(),
        loadUsers()
    ]);
}

// Show admin toast notification
function showAdminToast(message, type = 'success') {
    let container = document.getElementById('admin-toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'admin-toast-container';
        container.style.cssText = 'position:fixed;top:1rem;right:1rem;z-index:10000;display:flex;flex-direction:column;gap:0.5rem;';
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = `admin-toast admin-toast-${type}`;
    toast.textContent = message;
    toast.style.cssText = `padding:0.75rem 1.5rem;border-radius:6px;color:#fff;font-size:0.9rem;max-width:400px;box-shadow:0 2px 8px rgba(0,0,0,0.2);animation:fadeIn 0.3s;background:${type === 'error' ? '#dc3545' : type === 'success' ? '#28a745' : '#6c757d'};`;
    container.appendChild(toast);
    setTimeout(() => { toast.remove(); }, 4000);
}

// Show confirm modal (replaces browser confirm())
function showAdminConfirm(message, onConfirm) {
    let overlay = document.getElementById('admin-confirm-overlay');
    if (overlay) overlay.remove();

    overlay = document.createElement('div');
    overlay.id = 'admin-confirm-overlay';
    overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center;';

    const dialog = document.createElement('div');
    dialog.style.cssText = 'background:#fff;border-radius:8px;padding:2rem;max-width:420px;width:90%;box-shadow:0 4px 20px rgba(0,0,0,0.3);';
    dialog.innerHTML = `
        <h3 style="margin:0 0 1rem;color:#dc3545;">Confirm Action</h3>
        <p style="margin:0 0 1.5rem;line-height:1.5;">${escapeHtml(message)}</p>
        <div style="display:flex;gap:0.75rem;justify-content:flex-end;">
            <button class="btn-admin btn-admin-danger" id="admin-confirm-yes">Confirm</button>
            <button class="btn-admin btn-admin-outline" id="admin-confirm-no">Cancel</button>
        </div>
    `;
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    document.getElementById('admin-confirm-yes').addEventListener('click', () => {
        overlay.remove();
        onConfirm();
    });
    document.getElementById('admin-confirm-no').addEventListener('click', () => {
        overlay.remove();
    });
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.remove();
    });
}

// Delegated click handler for user management actions (CSP-compliant)
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
                console.error(e);
                showAdminToast('Error deleting user', 'error');
            }
            await refreshData();
        });
        return;  // Don't refreshData here — the confirm callback handles it
    } else {
        // activate, deactivate, make-admin, remove-admin, verify
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
            console.error(e);
            showAdminToast(`Error: ${action}`, 'error');
            return;
        }
    }

    await refreshData();
}

// Login form handler
function setupLoginForm() {
    const loginForm = document.getElementById('login-form');
    if (loginForm) {
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
}

// Setup nav event handlers
function setupNavHandlers() {
    const refreshLink = document.getElementById('refresh-link');
    if (refreshLink) {
        refreshLink.addEventListener('click', (e) => {
            e.preventDefault();
            refreshData();
        });
    }

    const logoutLink = document.getElementById('logout-link');
    if (logoutLink) {
        logoutLink.addEventListener('click', async (e) => {
            e.preventDefault();
            try {
                await apiRequest('/api/auth/logout', { method: 'POST' });
            } catch (err) {
                // Ignore errors on logout — we clear the token regardless
            }
            showLoginForm();
        });
    }
}

// Initialize admin panel
async function init() {
    setupLoginForm();
    setupNavHandlers();

    // Check authentication
    const isAuth = await checkAuth();
    if (!isAuth) return;

    // Load data
    showAdminPanel();

    // Auto-refresh every 30 seconds so cellar sizes stay current
    setInterval(refreshData, 30000);
}

// Run on page load
document.addEventListener('DOMContentLoaded', init);
