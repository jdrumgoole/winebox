/**
 * WineBox Admin Panel JavaScript
 */

// Get auth token from localStorage
function getAuthToken() {
    return localStorage.getItem('winebox_token');
}

// Check if user is authenticated
async function checkAuth() {
    const token = getAuthToken();
    if (!token) {
        window.location.href = '/';
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
        // Not authenticated or not admin
        window.location.href = '/';
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
        const response = await apiRequest('/admin/api/stats');
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
        const response = await apiRequest('/admin/api/users');
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

// Delegated click handler for user management actions (CSP-compliant)
async function handleAdminAction(e) {
    const btn = e.target.closest('button[data-action]');
    if (!btn) return;

    const action = btn.dataset.action;
    const userId = btn.dataset.userId;
    const email = btn.dataset.userEmail || '';

    if (action === 'delete') {
        if (!confirm(`Delete user ${email} and ALL their data?\n\nThis cannot be undone.`)) return;
        try {
            const resp = await apiRequest(`/admin/api/users/${userId}`, { method: 'DELETE' });
            if (!resp.ok) {
                const err = await resp.json();
                alert(err.detail || 'Failed to delete user');
                return;
            }
            const result = await resp.json();
            alert(`Deleted ${email}: ${result.wines_deleted} wines, ${result.transactions_deleted} transactions removed.`);
        } catch (e) { console.error(e); return; }
    } else {
        // activate, deactivate, make-admin, remove-admin, verify
        try {
            const resp = await apiRequest(`/admin/api/users/${userId}/${action}`, { method: 'PATCH' });
            if (!resp.ok) {
                const err = await resp.json();
                alert(err.detail || `Failed: ${action}`);
                return;
            }
        } catch (e) { console.error(e); return; }
    }

    await refreshData();
}

// Initialize admin panel
async function init() {
    // Check authentication
    const isAuth = await checkAuth();
    if (!isAuth) return;

    // Load data
    await refreshData();

    // Auto-refresh every 30 seconds so cellar sizes stay current
    setInterval(refreshData, 30000);
}

// Run on page load
document.addEventListener('DOMContentLoaded', init);
