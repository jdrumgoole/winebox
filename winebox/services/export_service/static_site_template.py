"""HTML template for the static cellar website export.

The template is a single self-contained HTML page with inlined CSS and JS.
Wine data is loaded from a separate ``data.json`` file in the same directory.
Chart.js is loaded from ``chart.min.js`` in the same directory.

All styling reuses WineBox brand colours and component patterns.
"""

from __future__ import annotations

from datetime import datetime, timezone


def render_html(
    *,
    wine_count: int,
    bottle_count: int,
    filters_applied: dict[str, str],
    export_date: str | None = None,
) -> str:
    """Return the complete HTML page for the static cellar export.

    Wine data is NOT embedded here -- it's loaded at runtime from ``data.json``
    via a synchronous ``<script>`` tag so the HTML template stays small.
    """
    if export_date is None:
        export_date = datetime.now(timezone.utc).strftime("%d %B %Y")

    filters_summary = ""
    if filters_applied:
        parts = [f"{k}: {v}" for k, v in filters_applied.items() if v]
        if parts:
            filters_summary = f'<p class="export-filters">Filtered by: {", ".join(parts)}</p>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>My Wine Cellar - WineBox Export</title>
<script src="chart.min.js"></script>
<script src="data.json"></script>
<style>
{_CSS}
</style>
</head>
<body>

<header class="export-header">
    <div class="export-header-inner">
        <div class="export-brand">
            <svg width="32" height="32" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect width="100" height="100" rx="16" fill="#5C0A2D"/>
                <path d="M50 20 C50 20, 65 40, 65 55 C65 63.28 58.28 70 50 70 C41.72 70 35 63.28 35 55 C35 40 50 20 50 20Z" fill="#C49A3C"/>
                <rect x="47" y="68" width="6" height="14" rx="2" fill="#C49A3C"/>
                <rect x="40" y="80" width="20" height="4" rx="2" fill="#C49A3C"/>
            </svg>
            <span class="export-brand-name">WineBox</span>
        </div>
        <div class="export-meta">
            <span class="export-date">Exported {export_date}</span>
            <span class="export-count">{wine_count} wines &middot; {bottle_count} bottles</span>
        </div>
    </div>
    {filters_summary}
</header>

<main>
    <div class="tab-bar">
        <button class="tab-btn active" data-tab="dashboard">Dashboard</button>
        <button class="tab-btn" data-tab="browse">Browse</button>
    </div>

    <!-- Dashboard -->
    <section id="panel-dashboard" class="panel active">
        <div class="stats-grid" id="stats-grid"></div>
        <div class="chart-grid" id="chart-grid"></div>
    </section>

    <!-- Browse -->
    <section id="panel-browse" class="panel">
        <div class="filter-bar" id="filter-bar"></div>
        <div class="wine-grid" id="wine-grid"></div>
        <div class="no-results" id="no-results" style="display:none;">
            No wines match your filters.
        </div>
    </section>
</main>

<!-- Wine Detail Modal -->
<div class="modal" id="wine-modal">
    <div class="modal-content modal-large">
        <span class="modal-close" id="modal-close">&times;</span>
        <div id="wine-detail"></div>
    </div>
</div>

<footer class="export-footer">
    <span>Exported from <strong>WineBox</strong></span>
</footer>

<script>
{_JS}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Inlined CSS
# ---------------------------------------------------------------------------
_CSS = """\
/* Reset */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
    --burgundy: #5C0A2D;
    --burgundy-light: #8B1A4A;
    --bottle: #B82860;
    --gold: #C49A3C;
    --gold-light: #F0D78C;
    --cream: #FAF7F2;
    --primary-color: var(--burgundy-light);
    --primary-light: var(--bottle);
    --primary-dark: var(--burgundy);
    --secondary-color: var(--gold);
    --background-color: var(--cream);
    --card-background: #ffffff;
    --text-color: #2D1A22;
    --text-muted: #8A7A80;
    --border-color: #E8E0D8;
    --success-color: #4a7c59;
    --shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
    --shadow-hover: 0 4px 16px rgba(0, 0, 0, 0.12);
    --radius: 8px;
    --radius-lg: 12px;
}

body {
    font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--background-color);
    color: var(--text-color);
    line-height: 1.6;
}

h1, h2, h3 {
    font-family: 'Playfair Display', Georgia, 'Times New Roman', serif;
}

/* Header */
.export-header {
    background: linear-gradient(135deg, var(--burgundy) 0%, var(--burgundy-light) 100%);
    color: white;
    padding: 1.5rem 2rem;
}
.export-header-inner {
    display: flex;
    justify-content: space-between;
    align-items: center;
    max-width: 1400px;
    margin: 0 auto;
    flex-wrap: wrap;
    gap: 1rem;
}
.export-brand {
    display: flex;
    align-items: center;
    gap: 0.75rem;
}
.export-brand-name {
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 1.5rem;
    font-weight: 700;
}
.export-meta {
    display: flex;
    gap: 1.5rem;
    font-size: 0.9rem;
    opacity: 0.9;
}
.export-filters {
    max-width: 1400px;
    margin: 0.75rem auto 0;
    font-size: 0.85rem;
    opacity: 0.8;
    font-style: italic;
}

/* Tabs */
.tab-bar {
    max-width: 1400px;
    margin: 0 auto;
    padding: 1.5rem 2rem 0;
    display: flex;
    gap: 0.25rem;
    border-bottom: 2px solid var(--border-color);
}
.tab-btn {
    padding: 0.75rem 1.5rem;
    border: none;
    background: none;
    cursor: pointer;
    font-size: 1rem;
    font-weight: 500;
    color: var(--text-muted);
    border-bottom: 3px solid transparent;
    margin-bottom: -2px;
    transition: color 0.2s, border-color 0.2s;
}
.tab-btn:hover { color: var(--text-color); }
.tab-btn.active {
    color: var(--primary-color);
    border-bottom-color: var(--primary-color);
}

/* Panels */
.panel { display: none; max-width: 1400px; margin: 0 auto; padding: 1.5rem 2rem; }
.panel.active { display: block; }

/* Stats */
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
}
.stat-card {
    background: var(--card-background);
    border-radius: var(--radius-lg);
    padding: 0.75rem 1rem;
    text-align: center;
    box-shadow: var(--shadow);
    border: 1px solid var(--border-color);
}
.stat-value {
    font-size: 1.6rem;
    font-weight: 700;
    color: var(--primary-color);
    line-height: 1.2;
}
.stat-label {
    color: var(--text-muted);
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

/* Charts */
.chart-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 1.5rem;
    margin-bottom: 2rem;
}
.chart-card {
    background: var(--card-background);
    border-radius: var(--radius-lg);
    padding: 1.5rem;
    box-shadow: var(--shadow);
    border: 1px solid var(--border-color);
}
.chart-card h3 {
    margin: 0 0 1rem;
    font-size: 1rem;
    color: var(--text-muted);
}
.chart-wrapper { position: relative; height: 250px; }

/* Filter bar */
.filter-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    align-items: flex-end;
    margin-bottom: 1.5rem;
    padding: 1rem 1.25rem;
    background: var(--card-background);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow);
    border: 1px solid var(--border-color);
}
.filter-group { display: flex; flex-direction: column; gap: 0.3rem; }
.filter-group label {
    font-size: 0.75rem;
    font-weight: 500;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.filter-group input, .filter-group select {
    padding: 0.5rem 0.75rem;
    border: 1px solid var(--border-color);
    border-radius: var(--radius);
    font-size: 0.9rem;
    min-width: 140px;
}
.filter-group input:focus, .filter-group select:focus {
    outline: none;
    border-color: var(--primary-color);
    box-shadow: 0 0 0 3px rgba(139, 26, 74, 0.1);
}
.filter-group.search-group { flex: 1; min-width: 200px; }
.filter-group.search-group input { width: 100%; }
.filter-group.checkbox-group {
    flex-direction: row;
    align-items: center;
    gap: 0.4rem;
    padding-bottom: 0.5rem;
}
.filter-group.checkbox-group input { min-width: auto; width: auto; }
.btn-clear-filters {
    padding: 0.5rem 1rem;
    border: 1px solid var(--border-color);
    border-radius: var(--radius);
    background: var(--card-background);
    cursor: pointer;
    font-size: 0.85rem;
    color: var(--text-muted);
}
.btn-clear-filters:hover { background: var(--background-color); }

/* Wine grid */
.wine-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 1.5rem;
}
.wine-card {
    display: flex;
    flex-direction: column;
    background: var(--card-background);
    border-radius: var(--radius-lg);
    overflow: hidden;
    box-shadow: var(--shadow);
    border: 1px solid var(--border-color);
    transition: transform 0.2s, box-shadow 0.2s;
    cursor: pointer;
}
.wine-card:hover {
    transform: translateY(-2px);
    box-shadow: var(--shadow-hover);
}
.wine-card-image {
    height: 180px;
    background: linear-gradient(135deg, var(--primary-light) 0%, var(--primary-color) 100%);
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    color: rgba(255,255,255,0.5);
    font-size: 0.9rem;
}
.wine-card-image img {
    max-width: 100%;
    max-height: 100%;
    object-fit: cover;
}
.wine-card-content {
    padding: 1.25rem;
    flex: 1;
    display: flex;
    flex-direction: column;
}
.wine-card-title {
    font-size: 1.1rem;
    font-weight: 600;
    margin-bottom: 0.5rem;
    color: var(--text-color);
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    min-height: 1.4em;
}
.wine-card-subtitle {
    color: var(--text-muted);
    font-size: 0.9rem;
    margin-bottom: 0.75rem;
}
.wine-card-fields {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    margin-bottom: 0.75rem;
}
.wine-card-field {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    font-size: 0.85rem;
}
.wine-card-field-label {
    color: var(--text-muted);
    font-size: 0.8rem;
    flex-shrink: 0;
    margin-right: 0.5rem;
}
.wine-card-field-value { color: var(--text-color); text-align: right; }
.enriched { color: #2e7d32; }
.wine-card-expand-btn {
    font-size: 0.8rem;
    color: var(--primary-color);
    cursor: pointer;
    margin-top: 0.5rem;
}
.wine-card-expand-btn:hover { text-decoration: underline; }
.wine-card-extra {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-top: 0.5rem;
}
.wine-card-footer {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 0.5rem;
    padding: 0.75rem 1.25rem;
    border-top: 1px solid var(--border-color);
    margin-top: auto;
}

/* Inventory chips */
.inventory-breakdown {
    display: inline-flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    align-items: center;
    font-size: 0.85rem;
    font-weight: 500;
}
.inventory-breakdown.out-of-stock {
    color: var(--text-muted);
    font-style: italic;
    font-weight: 400;
}
.case-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.2rem 0.55rem;
    border: 1px solid var(--primary-color);
    border-radius: 999px;
    background: color-mix(in srgb, var(--primary-color) 8%, transparent);
    color: var(--primary-color);
    white-space: nowrap;
    line-height: 1.2;
}
.loose-pill {
    display: inline-flex;
    align-items: center;
    padding: 0.2rem 0.55rem;
    border-radius: 999px;
    background: #f3efe7;
    color: var(--text-muted);
    white-space: nowrap;
    line-height: 1.2;
}

/* No results */
.no-results {
    text-align: center;
    padding: 3rem;
    color: var(--text-muted);
    font-size: 1.1rem;
}

/* Modal */
.modal {
    display: none;
    position: fixed;
    top: 0; left: 0;
    width: 100%; height: 100%;
    background: rgba(0, 0, 0, 0.5);
    z-index: 200;
    align-items: center;
    justify-content: center;
    padding: 2rem;
}
.modal.active { display: flex; }
.modal-content {
    background: var(--card-background);
    border-radius: var(--radius-lg);
    max-width: 900px;
    width: 100%;
    max-height: 90vh;
    overflow-y: auto;
    position: relative;
    padding: 2rem;
}
.modal-close {
    position: absolute;
    top: 1rem; right: 1rem;
    font-size: 1.5rem;
    cursor: pointer;
    color: var(--text-muted);
    transition: color 0.2s;
    background: none;
    border: none;
}
.modal-close:hover { color: var(--text-color); }

/* Wine detail */
.wine-detail-grid {
    display: grid;
    grid-template-columns: 1fr 2fr;
    gap: 2rem;
}
.wine-detail-images { display: flex; flex-direction: column; gap: 1rem; }
.wine-detail-image {
    border-radius: var(--radius);
    overflow: hidden;
    border: 1px solid var(--border-color);
}
.wine-detail-image img { width: 100%; height: auto; }
.wine-detail-info h3 {
    font-size: 1.5rem;
    color: var(--primary-color);
    margin-bottom: 0.5rem;
}
.wine-detail-meta {
    color: var(--text-muted);
    margin-bottom: 1.5rem;
}
.wine-detail-fields {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 0.5rem;
    margin-bottom: 1rem;
}
.wine-detail-field {
    background: var(--background-color);
    padding: 0.5rem 0.75rem;
    border-radius: var(--radius);
}
.wine-detail-field .label {
    font-size: 0.75rem;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.wine-detail-field .value { font-size: 1rem; font-weight: 500; }
.wine-detail-field .value.enriched { color: #2e7d32; }
.wine-detail-field:has(.value.enriched) {
    background: #e8f5e9;
    border-left: 3px solid #4caf50;
}
.wine-detail-field:has(.value.enriched) .label::after {
    content: ' (augmented)';
    text-transform: none;
    font-style: italic;
    letter-spacing: normal;
    color: #4caf50;
}
.wine-detail-bottles {
    grid-column: 1 / -1;
    background: var(--background-color);
    padding: 0.75rem;
    border-radius: var(--radius);
    margin-bottom: 0.5rem;
}
.wine-detail-bottles > .label {
    font-size: 0.75rem;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 0.5rem;
}
.wine-detail-case-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.35rem 0;
    border-bottom: 1px solid var(--border-color);
    font-size: 0.9rem;
}
.wine-detail-case-row:last-child { border-bottom: none; }
.wine-detail-case-row .case-label { font-weight: 600; min-width: 80px; }
.wine-detail-case-row .case-count { color: var(--text-muted); }
.wine-detail-case-row .case-provenance { color: var(--text-muted); font-style: italic; }
.wine-detail-case-row .case-price { color: var(--text-muted); margin-left: auto; }

/* Scores */
.score-list { display: flex; flex-direction: column; gap: 0.4rem; margin-top: 0.5rem; }
.score-entry {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.35rem 0.75rem;
    background: var(--background-color);
    border-radius: var(--radius);
    font-size: 0.85rem;
}
.score-source { font-weight: 500; }
.score-value { color: var(--primary-color); font-weight: 600; }

/* Grape blends */
.blend-list { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.5rem; }
.blend-chip {
    padding: 0.2rem 0.55rem;
    border-radius: 999px;
    background: var(--background-color);
    font-size: 0.8rem;
    border: 1px solid var(--border-color);
}

/* Footer */
.export-footer {
    text-align: center;
    padding: 2rem;
    color: var(--text-muted);
    font-size: 0.85rem;
    border-top: 1px solid var(--border-color);
    margin-top: 2rem;
}

/* Responsive */
@media (max-width: 768px) {
    .wine-grid { grid-template-columns: 1fr; }
    .chart-grid { grid-template-columns: 1fr; }
    .wine-detail-grid { grid-template-columns: 1fr; }
    .export-header-inner { flex-direction: column; align-items: flex-start; }
    .filter-bar { flex-direction: column; }
    .filter-group { width: 100%; }
    .filter-group input, .filter-group select { width: 100%; }
}
"""


# ---------------------------------------------------------------------------
# Inlined JavaScript
# ---------------------------------------------------------------------------
_JS = """\
/* ---- Helpers ---- */
function escapeHtml(text) {
    if (text == null) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function formatDate(dateString) {
    if (!dateString) return '';
    const d = new Date(dateString);
    return d.toLocaleDateString('en-GB', { year: 'numeric', month: 'short', day: 'numeric' });
}

/* ---- Data (loaded from data.json via global CELLAR_DATA) ---- */
const wines = (typeof CELLAR_DATA !== 'undefined') ? CELLAR_DATA : [];

/* ---- Tabs ---- */
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('panel-' + btn.dataset.tab).classList.add('active');
    });
});

/* ---- Dashboard ---- */
function renderDashboard() {
    const totalBottles = wines.reduce((s, w) => s + (w.inventory?.quantity || 0), 0);
    const inStock = wines.filter(w => (w.inventory?.quantity || 0) > 0);
    const totalCases = wines.reduce((s, w) => s + (w.inventory?.cases?.length || 0), 0);

    document.getElementById('stats-grid').innerHTML = [
        { value: wines.length, label: 'Wines' },
        { value: totalBottles, label: 'Bottles' },
        { value: totalCases, label: 'Cases' },
        { value: inStock.length, label: 'In Stock' },
    ].map(s => `<div class="stat-card"><div class="stat-value">${s.value}</div><div class="stat-label">${s.label}</div></div>`).join('');

    /* Charts */
    const byType = {};
    const byCountry = {};
    wines.forEach(w => {
        const t = w.wine_type || 'Unknown';
        byType[t] = (byType[t] || 0) + (w.inventory?.quantity || 0);
        const c = w.country || 'Unknown';
        byCountry[c] = (byCountry[c] || 0) + (w.inventory?.quantity || 0);
    });

    const typeColors = {
        'red': '#722F37', 'white': '#F5E6C8', 'ros\\u00e9': '#E8A0BF',
        'sparkling': '#FFD700', 'fortified': '#8B4513', 'dessert': '#DAA520', 'Unknown': '#ccc'
    };

    const chartGrid = document.getElementById('chart-grid');
    chartGrid.innerHTML = `
        <div class="chart-card">
            <h3>Wine Types</h3>
            <div class="chart-wrapper"><canvas id="type-chart"></canvas></div>
        </div>
        <div class="chart-card">
            <h3>Top Countries</h3>
            <div class="chart-wrapper"><canvas id="country-chart"></canvas></div>
        </div>
    `;

    if (typeof Chart !== 'undefined') {
        const typeLabels = Object.keys(byType).sort((a, b) => byType[b] - byType[a]);
        new Chart(document.getElementById('type-chart'), {
            type: 'doughnut',
            data: {
                labels: typeLabels,
                datasets: [{ data: typeLabels.map(l => byType[l]),
                    backgroundColor: typeLabels.map(l => typeColors[l.toLowerCase()] || '#999') }]
            },
            options: { responsive: true, maintainAspectRatio: false,
                plugins: { legend: { position: 'bottom' } } }
        });

        const countryEntries = Object.entries(byCountry).sort((a, b) => b[1] - a[1]).slice(0, 10);
        new Chart(document.getElementById('country-chart'), {
            type: 'bar',
            data: {
                labels: countryEntries.map(e => e[0]),
                datasets: [{ data: countryEntries.map(e => e[1]),
                    backgroundColor: '#8B1A4A' }]
            },
            options: { responsive: true, maintainAspectRatio: false, indexAxis: 'y',
                plugins: { legend: { display: false } } }
        });
    }
}

/* ---- Filter bar ---- */
function buildFilterBar() {
    const distinct = (key) => [...new Set(wines.map(w => w[key]).filter(Boolean))].sort();

    const bar = document.getElementById('filter-bar');
    bar.innerHTML = `
        <div class="filter-group search-group">
            <label>Search</label>
            <input type="text" id="f-search" placeholder="Name, winery, region...">
        </div>
        ${makeSelect('Wine Type', 'f-wine-type', distinct('wine_type'))}
        ${makeSelect('Country', 'f-country', distinct('country'))}
        ${makeSelect('Region', 'f-region', distinct('region'))}
        ${makeSelect('Grape', 'f-grape', distinct('grape_variety'))}
        ${makeSelect('Price Tier', 'f-price-tier', distinct('price_tier'))}
        <div class="filter-group checkbox-group">
            <input type="checkbox" id="f-in-stock">
            <label for="f-in-stock">In Stock</label>
        </div>
        <button class="btn-clear-filters" id="clear-filters">Clear</button>
    `;

    bar.querySelectorAll('input, select').forEach(el =>
        el.addEventListener('input', applyFilters));
    document.getElementById('clear-filters').addEventListener('click', () => {
        bar.querySelectorAll('input[type=text]').forEach(i => { i.value = ''; });
        bar.querySelectorAll('select').forEach(s => { s.value = ''; });
        bar.querySelectorAll('input[type=checkbox]').forEach(c => { c.checked = false; });
        applyFilters();
    });
}

function makeSelect(label, id, options) {
    const opts = options.map(o => `<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join('');
    return `<div class="filter-group">
        <label>${label}</label>
        <select id="${id}"><option value="">All</option>${opts}</select>
    </div>`;
}

/* ---- Filtering ---- */
function applyFilters() {
    const q = (document.getElementById('f-search')?.value || '').toLowerCase();
    const wineType = document.getElementById('f-wine-type')?.value || '';
    const country = document.getElementById('f-country')?.value || '';
    const region = document.getElementById('f-region')?.value || '';
    const grape = document.getElementById('f-grape')?.value || '';
    const priceTier = document.getElementById('f-price-tier')?.value || '';
    const inStock = document.getElementById('f-in-stock')?.checked || false;

    const filtered = wines.filter(w => {
        if (q) {
            const haystack = [w.name, w.winery, w.region, w.country, w.grape_variety]
                .filter(Boolean).join(' ').toLowerCase();
            if (!haystack.includes(q)) return false;
        }
        if (wineType && w.wine_type !== wineType) return false;
        if (country && w.country !== country) return false;
        if (region && w.region !== region) return false;
        if (grape && w.grape_variety !== grape) return false;
        if (priceTier && w.price_tier !== priceTier) return false;
        if (inStock && (w.inventory?.quantity || 0) <= 0) return false;
        return true;
    });

    renderWineGrid(filtered);
}

/* ---- Wine cards ---- */
function caseChipHtml(c) {
    const remaining = c.bottles_remaining || 0;
    const provBit = c.provenance ? ' \\u00b7 ' + escapeHtml(c.provenance) : '';
    return `<span class="case-chip">Case of ${c.case_size} \\u00b7 ${remaining} left${provBit}</span>`;
}

function loosePillHtml(n) {
    return `<span class="loose-pill">${n} loose bottle${n !== 1 ? 's' : ''}</span>`;
}

function inventoryHtml(inv) {
    if (!inv || (inv.quantity || 0) === 0)
        return '<span class="inventory-breakdown out-of-stock">Out of stock</span>';
    const parts = (inv.cases || []).map(caseChipHtml);
    if ((inv.loose_bottles || 0) > 0) parts.push(loosePillHtml(inv.loose_bottles));
    if (parts.length === 0) parts.push(loosePillHtml(inv.quantity));
    return `<span class="inventory-breakdown">${parts.join('')}</span>`;
}

function renderWineGrid(list) {
    const grid = document.getElementById('wine-grid');
    const noResults = document.getElementById('no-results');

    if (list.length === 0) {
        grid.innerHTML = '';
        noResults.style.display = 'block';
        return;
    }
    noResults.style.display = 'none';

    grid.innerHTML = list.map(w => {
        const imgHtml = w.front_label_image
            ? `<img src="${escapeHtml(w.front_label_image)}" alt="${escapeHtml(w.name)}">`
            : 'No Image';
        const subtitle = [w.winery, w.vintage].filter(Boolean).join(' \\u2013 ');
        const enrichedFields = new Set(w.enriched_fields || []);
        const ec = (field) => enrichedFields.has(field) ? ' enriched' : '';

        const fields = [];
        if (w.country) fields.push({l: 'Country', v: w.country, e: ec('country')});
        if (w.region) fields.push({l: 'Region', v: w.region, e: ec('region')});
        const fieldsHtml = fields.map(f =>
            `<div class="wine-card-field"><span class="wine-card-field-label">${f.l}</span><span class="wine-card-field-value${f.e}">${escapeHtml(f.v)}</span></div>`
        ).join('');

        return `<div class="wine-card" data-wine-id="${w.id}">
            <div class="wine-card-image">${imgHtml}</div>
            <div class="wine-card-content">
                <div class="wine-card-title">${escapeHtml(w.name)}</div>
                <div class="wine-card-subtitle">${escapeHtml(subtitle)}</div>
                <div class="wine-card-fields">${fieldsHtml}</div>
                <div class="wine-card-footer">${inventoryHtml(w.inventory)}</div>
            </div>
        </div>`;
    }).join('');

    grid.querySelectorAll('.wine-card').forEach(card => {
        card.addEventListener('click', () => showDetail(card.dataset.wineId));
    });
}

/* ---- Wine detail modal ---- */
function showDetail(wineId) {
    const w = wines.find(x => x.id === wineId);
    if (!w) return;

    const enrichedFields = new Set(w.enriched_fields || []);
    const ec = (field) => enrichedFields.has(field) ? ' enriched' : '';

    const imagesHtml = [];
    if (w.front_label_image)
        imagesHtml.push(`<div class="wine-detail-image"><img src="${escapeHtml(w.front_label_image)}" alt="Front label"></div>`);
    if (w.back_label_image)
        imagesHtml.push(`<div class="wine-detail-image"><img src="${escapeHtml(w.back_label_image)}" alt="Back label"></div>`);
    if (imagesHtml.length === 0)
        imagesHtml.push('<div class="wine-detail-image" style="height:200px;background:linear-gradient(135deg,var(--primary-light),var(--primary-color));display:flex;align-items:center;justify-content:center;color:rgba(255,255,255,0.5);">No Image</div>');

    const detailFields = [
        w.grape_variety && { l: 'Grape Variety', v: w.grape_variety, e: ec('grape_variety') },
        w.region && { l: 'Region', v: w.region, e: ec('region') },
        w.sub_region && { l: 'Sub-Region', v: w.sub_region },
        w.appellation && { l: 'Appellation', v: w.appellation },
        w.country && { l: 'Country', v: w.country, e: ec('country') },
        w.classification && { l: 'Classification', v: w.classification },
        w.alcohol_percentage && { l: 'ABV', v: w.alcohol_percentage + '%', e: ec('alcohol_percentage') },
        w.wine_type && { l: 'Type', v: w.wine_type },
        w.price_tier && { l: 'Price Tier', v: w.price_tier.replace(/_/g, ' ') },
        w.estimated_price_low && w.estimated_price_high && { l: 'Est. Price', v: '$' + w.estimated_price_low + ' \\u2013 $' + w.estimated_price_high },
        w.drink_window_start && w.drink_window_end && { l: 'Drink Window', v: w.drink_window_start + ' \\u2013 ' + w.drink_window_end },
        w.producer_type && { l: 'Producer', v: w.producer_type },
    ].filter(Boolean);

    const fieldsHtml = detailFields.map(f =>
        `<div class="wine-detail-field"><div class="label">${f.l}</div><div class="value${f.e || ''}">${escapeHtml(f.v)}</div></div>`
    ).join('');

    /* Inventory breakdown */
    let inventorySection = '';
    const inv = w.inventory;
    if (inv && inv.quantity > 0) {
        const rows = [];
        (inv.cases || []).forEach(c => {
            const prov = c.provenance ? `<span class="case-provenance">from ${escapeHtml(c.provenance)}</span>` : '';
            const price = c.purchase_price ? `<span class="case-price">$${c.purchase_price.toFixed(2)}</span>` : '';
            rows.push(`<div class="wine-detail-case-row">
                <span class="case-label">Case of ${c.case_size}</span>
                <span class="case-count">${c.bottles_remaining} left</span>
                ${prov}${price}
            </div>`);
        });
        if ((inv.loose_bottles || 0) > 0) {
            rows.push(`<div class="wine-detail-case-row">
                <span class="case-label">Loose</span>
                <span class="case-count">${inv.loose_bottles} bottle${inv.loose_bottles !== 1 ? 's' : ''}</span>
            </div>`);
        }
        inventorySection = `<div class="wine-detail-bottles">
            <div class="label">In Stock: ${inv.quantity} bottle${inv.quantity !== 1 ? 's' : ''}</div>
            ${rows.join('')}
        </div>`;
    }

    /* Scores */
    let scoresHtml = '';
    if (w.scores && w.scores.length > 0) {
        const entries = w.scores.map(s =>
            `<div class="score-entry"><span class="score-source">${escapeHtml(s.source || 'Unknown')}</span><span class="score-value">${s.normalized_score || s.score}/100</span></div>`
        ).join('');
        scoresHtml = `<h4 style="margin-top:1rem;color:var(--text-muted);font-size:0.85rem;text-transform:uppercase;">Ratings</h4><div class="score-list">${entries}</div>`;
    }

    /* Grape blends */
    let blendsHtml = '';
    if (w.grape_blends && w.grape_blends.length > 0) {
        const chips = w.grape_blends.map(b =>
            `<span class="blend-chip">${escapeHtml(b.grape)} ${b.percentage ? b.percentage + '%' : ''}</span>`
        ).join('');
        blendsHtml = `<h4 style="margin-top:1rem;color:var(--text-muted);font-size:0.85rem;text-transform:uppercase;">Grape Blend</h4><div class="blend-list">${chips}</div>`;
    }

    /* Custom fields */
    let customHtml = '';
    if (w.custom_fields && Object.keys(w.custom_fields).length > 0) {
        const entries = Object.entries(w.custom_fields)
            .filter(([k]) => !k.startsWith('_'))
            .map(([k, v]) => `<div class="wine-detail-field"><div class="label">${escapeHtml(k)}</div><div class="value">${escapeHtml(v)}</div></div>`)
            .join('');
        if (entries) customHtml = `<h4 style="margin-top:1rem;color:var(--text-muted);font-size:0.85rem;text-transform:uppercase;">Custom Fields</h4><div class="wine-detail-fields">${entries}</div>`;
    }

    const qty = inv ? inv.quantity : 0;
    const detail = document.getElementById('wine-detail');
    detail.innerHTML = `<div class="wine-detail-grid">
        <div class="wine-detail-images">${imagesHtml.join('')}</div>
        <div class="wine-detail-info">
            <h3>${escapeHtml(w.name)}${qty > 0 ? ` <span style="font-size:0.9rem;color:var(--text-muted);">(${qty} bottle${qty !== 1 ? 's' : ''})</span>` : ''}</h3>
            <div class="wine-detail-meta">${escapeHtml([w.winery, w.vintage].filter(Boolean).join(' \\u2013 '))}</div>
            ${inventorySection}
            <div class="wine-detail-fields">${fieldsHtml}</div>
            ${scoresHtml}
            ${blendsHtml}
            ${customHtml}
        </div>
    </div>`;

    const modal = document.getElementById('wine-modal');
    modal.classList.add('active');
}

document.getElementById('modal-close').addEventListener('click', () => {
    document.getElementById('wine-modal').classList.remove('active');
});
document.getElementById('wine-modal').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) e.currentTarget.classList.remove('active');
});

/* ---- Init ---- */
renderDashboard();
buildFilterBar();
renderWineGrid(wines);
"""
