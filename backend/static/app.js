/**
 * VidyutSetu workbench frontend logic.
 * All numbers come from the API; nothing here invents analytics.
 */

let activeTab = 'overview';
let currentVendors = {};
let lastRun = null;
let lastRunWasSample = false;
let allIssues = [];
let diagnosticsExpanded = false;
let csrfToken = null;
let currentUser = null;
let authEnabled = true;
const DEFAULT_VISIBLE_DIAGNOSTICS = 3;

const STATUS_CLASS = {
  pass: 'pill pill-teal',
  warn: 'pill pill-amber',
  fail: 'pill pill-red',
  skipped: 'pill',
};

const nativeFetch = window.fetch.bind(window);
window.fetch = async (input, init = {}) => {
  const request = input instanceof Request ? input : null;
  const url = new URL(typeof input === 'string' ? input : input.url, window.location.href);
  const method = String(init.method || (request && request.method) || 'GET').toUpperCase();
  const headers = new Headers(init.headers || (request && request.headers) || undefined);
  if (authEnabled && url.origin === window.location.origin && url.pathname !== '/auth/login' &&
      !['GET', 'HEAD', 'OPTIONS'].includes(method) && csrfToken) {
    headers.set('X-CSRF-Token', csrfToken);
  }
  const response = await nativeFetch(input, { ...init, headers });
  if (authEnabled && response.status === 401 &&
      (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ml/'))) {
    showAuthScreen('Your session expired. Sign in again to continue.');
  }
  return response;
};

document.addEventListener('DOMContentLoaded', async () => {
  applyStoredTheme();
  applyGettingStartedPreference();
  if (window.lucide) lucide.createIcons();
  if (!await initializeAuthentication()) return;
  await loadWorkbench();
});

async function loadWorkbench() {
  await loadVendors();
  await refreshDashboard();
  await loadMlHealth();
  await renderHeatmap();
  handleEntryParams();
}

async function initializeAuthentication() {
  try {
    const response = await fetch('/auth/me');
    if (!response.ok) {
      showAuthScreen(response.status === 401 ? '' : 'The authentication service is unavailable. Try again shortly.');
      return false;
    }
    const data = await response.json();
    authEnabled = data.auth_enabled === true;
    csrfToken = data.csrf_token || null;
    currentUser = data.user || { username: 'Local development', role: 'admin' };
    showWorkbench();
    return true;
  } catch (error) {
    showAuthScreen(`Could not reach the sign-in service: ${error.message}`);
    return false;
  }
}

function showAuthScreen(message = '') {
  const shell = document.getElementById('workbench-shell');
  const screen = document.getElementById('auth-screen');
  if (shell) shell.hidden = true;
  if (screen) {
    screen.classList.remove('hidden');
    screen.classList.add('flex');
  }
  const error = document.getElementById('login-error');
  if (error) {
    error.textContent = message;
    error.classList.toggle('hidden', !message);
  }
}

function showWorkbench() {
  const shell = document.getElementById('workbench-shell');
  const screen = document.getElementById('auth-screen');
  if (shell) shell.hidden = false;
  if (screen) {
    screen.classList.add('hidden');
    screen.classList.remove('flex');
  }
  const userLabel = document.getElementById('current-user');
  const logoutButton = document.getElementById('logout-button');
  const adminButton = document.getElementById('manage-users');
  if (userLabel && authEnabled && currentUser) {
    userLabel.textContent = `${currentUser.username} · ${currentUser.role}`;
    userLabel.hidden = false;
  }
  if (logoutButton) logoutButton.hidden = !authEnabled;
  if (adminButton) adminButton.hidden = !authEnabled || !currentUser || currentUser.role !== 'admin';
  applyRoleVisibility();
}

function applyRoleVisibility() {
  const role = currentUser ? currentUser.role : 'admin';
  const levels = { viewer: 1, operator: 2, admin: 3 };
  document.querySelectorAll('[data-role-required]').forEach(element => {
    const required = element.getAttribute('data-role-required');
    element.hidden = (levels[role] || 0) < (levels[required] || 99);
  });
}

async function login(event) {
  event.preventDefault();
  const submit = document.getElementById('login-submit');
  const error = document.getElementById('login-error');
  const username = document.getElementById('login-username').value;
  const password = document.getElementById('login-password').value;
  submit.disabled = true;
  error.textContent = '';
  error.classList.add('hidden');
  try {
    const response = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `Sign in failed (${response.status}).`);
    authEnabled = data.auth_enabled === true;
    csrfToken = data.csrf_token || null;
    currentUser = data.user || { username: 'Local development', role: 'admin' };
    document.getElementById('login-password').value = '';
    showWorkbench();
    await loadWorkbench();
  } catch (loginError) {
    error.textContent = loginError.message;
    error.classList.remove('hidden');
  } finally {
    submit.disabled = false;
  }
}

async function logout() {
  try {
    await fetch('/auth/logout', { method: 'POST' });
  } catch (error) {
    console.error('Sign out request failed', error);
  }
  csrfToken = null;
  currentUser = null;
  showAuthScreen('You have signed out.');
  document.getElementById('login-password').value = '';
}

/** Deep links: /dashboard?sample=1 runs the synthetic sample straight away. */
function handleEntryParams() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('sample') !== '1') return;
  runSampleValidation();
}

function applyGettingStartedPreference() {
  const card = document.getElementById('getting-started');
  if (card && localStorage.getItem('vs-hide-getting-started') === '1') card.classList.add('hidden');
}

function dismissGettingStarted() {
  localStorage.setItem('vs-hide-getting-started', '1');
  const card = document.getElementById('getting-started');
  if (card) card.classList.add('hidden');
}

/* ---------- helpers ---------- */

function esc(value) {
  return String(value === null || value === undefined ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function pct(value) {
  return value === null || value === undefined ? '—' : Number(value).toFixed(1) + '%';
}

/* ---------- display-only formatting helpers (no data is changed) ---------- */

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "17 Nov 2026, 1:48 PM". Stored and API values keep their original format. */
function fmtDate(value) {
  if (!value) return '—';
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  const hours = d.getHours();
  const h12 = hours % 12 === 0 ? 12 : hours % 12;
  const minutes = String(d.getMinutes()).padStart(2, '0');
  return `${d.getDate()} ${MONTH_NAMES[d.getMonth()]} ${d.getFullYear()}, ${h12}:${minutes} ${hours < 12 ? 'AM' : 'PM'}`;
}

/** Grade badges stay text-identical; only the filled pill colour changes. */
function gradeClass(grade) {
  const g = String(grade === null || grade === undefined ? '' : grade).toUpperCase();
  if (g === 'A+') return 'grade grade-a-plus';
  if (g === 'A') return 'grade grade-a';
  if (g === 'B') return 'grade grade-b';
  return 'grade grade-c';
}

function scoreClass(score) {
  const s = Number(score);
  if (s >= 95) return 'score-good';
  if (s >= 80) return 'score-mid';
  return 'score-bad';
}

/** Score cell: value plus a small progress bar, colour driven by the same thresholds. */
function scoreCell(score) {
  const s = Number(score);
  const width = Math.max(0, Math.min(100, Number.isFinite(s) ? s : 0));
  return `<div class="score-cell ${scoreClass(score)}">
      <span class="score-val">${esc(score)}%</span>
      <span class="score-bar" aria-hidden="true"><span style="width:${width}%"></span></span>
    </div>`;
}

function emptyRow(colspan, icon, message) {
  return `<tr><td colspan="${colspan}">
      <div class="empty-state">
        <i data-lucide="${icon}" class="w-4 h-4" aria-hidden="true"></i>
        <span>${message}</span>
      </div>
    </td></tr>`;
}

function vendorInitials(name) {
  return String(name || '?')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(word => word[0].toUpperCase())
    .join('');
}

/** Whole vendor card is a click target, but inner buttons keep their own handler. */
function openVendorCard(event, vendorId) {
  if (event && event.target && event.target.closest('button, a')) return;
  runQuickDemo(vendorId, 'gamma-mdms');
}

function handleVendorCardKey(event, vendorId) {
  if (event.key !== 'Enter' && event.key !== ' ' && event.key !== 'Spacebar') return;
  event.preventDefault();
  runQuickDemo(vendorId, 'gamma-mdms');
}

/* ---------- theme ---------- */

function applyStoredTheme() {
  const stored = localStorage.getItem('vs-theme');
  const theme = stored === 'dark' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', theme);
  const button = document.getElementById('theme-toggle');
  if (button) button.textContent = theme === 'dark' ? 'Light theme' : 'Dark theme';
}

function toggleTheme() {
  const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('vs-theme', next);
  const button = document.getElementById('theme-toggle');
  if (button) button.textContent = next === 'dark' ? 'Light theme' : 'Dark theme';
}

/* ---------- tabs ---------- */

function switchTab(tabId) {
  if (authEnabled && currentUser && currentUser.role === 'viewer' &&
      ['workbench', 'compare', 'roundtrip'].includes(tabId)) return;
  activeTab = tabId;
  document.querySelectorAll('.tab-view').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.nav-tab[role="tab"]').forEach(el => el.setAttribute('aria-selected', 'false'));

  const activeView = document.getElementById(`view-${tabId}`);
  const activeBtn = document.getElementById(`tab-btn-${tabId}`);
  if (activeView) activeView.classList.remove('hidden');
  if (activeBtn) activeBtn.setAttribute('aria-selected', 'true');

  if (window.lucide) lucide.createIcons();

  if (tabId === 'overview') { refreshDashboard(); loadMlHealth(); renderHeatmap(); }
  if (tabId === 'mapping') renderMappingMatrix();
  if (tabId === 'compare') loadRunOptions();
  if (tabId === 'suites') loadSuites();
  if (tabId === 'vendors') renderVendorCards();
  if (tabId === 'history') loadHistoryRuns();
}

/* ---------- vendors ---------- */

async function loadVendors() {
  try {
    const res = await fetch('/api/vendors');
    if (!res.ok) throw new Error(`/api/vendors returned ${res.status}`);
    currentVendors = await res.json();
  } catch (e) {
    console.error('Failed to load vendors', e);
    currentVendors = {};
  }
}

function renderVendorCards() {
  const container = document.getElementById('vendor-cards-grid');
  if (!container) return;
  const vendors = Object.values(currentVendors || {});
  if (!vendors.length) {
    container.innerHTML = `<p class="muted text-sm">No adapters reported by /api/vendors. <button class="btn mt-2" onclick="loadVendors().then(renderVendorCards)">Retry</button></p>`;
    return;
  }
  container.innerHTML = vendors.map(v => `
    <div class="card card-pad space-y-3 vendor-card" role="button" tabindex="0"
         aria-label="Test ${esc(v.name)} in the workbench"
         onclick="openVendorCard(event, '${esc(v.vendor_id)}')"
         onkeydown="handleVendorCardKey(event, '${esc(v.vendor_id)}')">
      <div class="flex items-start justify-between gap-2">
        <div class="flex items-start gap-3">
          <span class="vendor-avatar" aria-hidden="true">${esc(vendorInitials(v.name))}</span>
          <div>
            <span class="pill pill-teal">${esc(v.system_type)}</span>
            <h3 class="font-bold mt-1" style="color:var(--vs-ink)">${esc(v.name)}</h3>
            <p class="label code" style="border:0;background:transparent;padding:0;color:var(--vs-muted)">${esc(v.vendor_id)} · v${esc(v.version)}</p>
          </div>
        </div>
        <span class="pill">${esc(v.format_type)}</span>
      </div>
      <p class="text-xs body-text leading-relaxed">${esc(v.description)}</p>
      <div class="pt-2 flex items-center justify-between gap-2 text-xs" style="border-top:1px solid var(--vs-line)">
        <span class="muted">Protocol: <strong style="color:var(--vs-ink)">${esc(v.protocol)}</strong></span>
        <button class="btn" onclick="runQuickDemo('${esc(v.vendor_id)}', 'gamma-mdms')">Test in workbench</button>
      </div>
    </div>
  `).join('');
  if (window.lucide) lucide.createIcons();
}

function renderMappingMatrix() {
  const body = document.getElementById('mapping-matrix-body');
  if (!body) return;
  const vendors = Object.values(currentVendors || {});
  if (!vendors.length) {
    body.innerHTML = '<tr><td colspan="6" class="muted">No adapters reported by /api/vendors.</td></tr>';
    return;
  }
  body.innerHTML = vendors.map(v => {
    const obis = Object.keys(v.obis_code_mappings || {}).length;
    const events = Object.keys(v.event_mappings || {}).length;
    return `<tr>
      <td><strong style="color:var(--vs-ink)">${esc(v.name)}</strong><div class="label">${esc(v.vendor_id)}</div></td>
      <td>${esc(v.system_type)}</td>
      <td>${esc(v.format_type)}</td>
      <td>${esc(v.protocol)}</td>
      <td>${obis}</td>
      <td>${events}</td>
    </tr>`;
  }).join('');
}

/* ---------- overview ---------- */

async function refreshDashboard() {
  try {
    const res = await fetch('/api/stats');
    const data = await res.json();
    const totalRuns = data.total_test_runs || 0;
    const avgScore = data.average_interoperability_score || 0;

    const usedAdapters = Object.keys(data.vendor_usage || {}).length;
    const totalAdapters = (data.active_vendor_adapters || 0) || usedAdapters;

    document.getElementById('stat-total-runs').innerText = totalRuns;
    document.getElementById('stat-total-runs-hint').innerText = totalRuns
      ? `${usedAdapters} of ${totalAdapters} adapters used`
      : 'No runs recorded yet — start one in Workbench.';

    document.getElementById('stat-avg-score').innerText = totalRuns ? avgScore.toFixed(1) + '%' : '0%';
    document.getElementById('stat-avg-score-hint').innerText = totalRuns
      ? `Across the most recent ${Math.min(totalRuns, 100)} runs.`
      : 'Available after your first run.';

    document.getElementById('stat-adapters').innerText = data.active_vendor_adapters || 0;

    const tbody = document.getElementById('recent-runs-table-body');
    const runs = data.recent_runs || [];
    if (!runs.length) {
      tbody.innerHTML = emptyRow(8, 'inbox', 'No runs yet. Open Workbench to execute the first validation.');
      if (window.lucide) lucide.createIcons();
      return;
    }
    tbody.innerHTML = runs.map(r => `
      <tr>
        <td class="code" style="background:transparent;border:0;padding:0 .6rem;color:var(--vs-teal-deep)">${esc(r.run_id)}</td>
        <td>${esc(fmtDate(r.execution_time))}</td>
        <td>${esc(r.source_vendor)}</td>
        <td>${esc(r.target_vendor || 'none')}</td>
        <td>${esc(r.total_records)}</td>
        <td>${scoreCell(r.total_score)}</td>
        <td><span class="${gradeClass(r.grade)}">${esc(r.grade)}</span></td>
        <td><a class="link" href="/api/test-runs/${encodeURIComponent(r.run_id)}/report.html" target="_blank" rel="noopener">Report</a></td>
      </tr>
    `).join('');
    if (window.lucide) lucide.createIcons();
  } catch (e) {
    console.error('Failed to refresh overview', e);
    const tbody = document.getElementById('recent-runs-table-body');
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="8"><div class="notice">
        Could not load dashboard statistics: ${esc(e.message)}.
        <button class="btn mt-2" onclick="refreshDashboard(); loadMlHealth(); renderHeatmap();">Retry</button>
      </div></td></tr>`;
    }
    ['stat-total-runs', 'stat-avg-score', 'stat-adapters'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerText = '—';
    });
  }
}

const SCORE_BANDS = [
  { label: '95–100', test: s => s >= 95 },
  { label: '85–95', test: s => s >= 85 && s < 95 },
  { label: '70–85', test: s => s >= 70 && s < 85 },
  { label: '50–70', test: s => s >= 50 && s < 70 },
  { label: '< 50', test: s => s < 50 },
];

async function renderHeatmap() {
  const container = document.getElementById('heatmap-body');
  const caption = document.getElementById('heatmap-caption');
  if (!container) return;
  try {
    const runs = await (await fetch('/api/test-runs?limit=200')).json();
    if (!runs.length) {
      container.innerHTML = `<div class="empty-state"><i data-lucide="bar-chart-3" class="w-4 h-4" aria-hidden="true"></i><span>No stored runs yet, so there is nothing to plot.</span></div>`;
      caption.innerText = '';
      if (window.lucide) lucide.createIcons();
      return;
    }
    const vendors = [...new Set(runs.map(r => r.source_vendor))].sort();
    const counts = {};
    vendors.forEach(v => { counts[v] = SCORE_BANDS.map(() => 0); });
    runs.forEach(r => {
      const bandIndex = SCORE_BANDS.findIndex(b => b.test(Number(r.total_score)));
      if (bandIndex >= 0) counts[r.source_vendor][bandIndex] += 1;
    });
    const max = Math.max(1, ...vendors.flatMap(v => counts[v]));

    const header = `<tr><th class="heat-axis">Vendor ↓ · band % →</th>${SCORE_BANDS.map(b => `<th class="band">${b.label}</th>`).join('')}</tr>`;
    const rows = vendors.map(v => `<tr>
      <th>${esc(v)}</th>
      ${counts[v].map((n, i) => {
        const alpha = n === 0 ? 0 : 0.15 + (0.75 * n / max);
        const style = n === 0
          ? 'background:var(--vs-surface-alt);color:var(--vs-muted)'
          : `background:rgba(14,154,167,${alpha.toFixed(2)});color:#062A31`;
        return `<td class="band" style="${style}" title="${esc(v)} · ${SCORE_BANDS[i].label}% · ${n} run(s)">${n}</td>`;
      }).join('')}
    </tr>`).join('');

    container.innerHTML = `<table class="heat" aria-label="Stored runs per source vendor and score band">
        <thead>${header}</thead><tbody>${rows}</tbody></table>
      <div class="legend">
        <span class="swatch" style="background:var(--vs-surface-alt)"></span><span>0 runs</span>
        <span class="swatch" style="background:rgba(14,154,167,0.35)"></span><span>fewer</span>
        <span class="swatch" style="background:rgba(14,154,167,0.9)"></span><span>more</span>
      </div>`;
    caption.innerText = `${runs.length} stored run(s). Rows are the source vendor, columns the interoperability score band; every cell shows its run count.`;
  } catch (e) {
    container.innerHTML = '<p class="muted text-sm">Could not load runs.</p>';
    console.error('Heatmap failed', e);
  }
}

async function loadMlHealth() {
  const body = document.getElementById('ml-screening-body');
  const headline = document.getElementById('ml-headline-accuracy');
  if (!body) return;
  body.innerHTML = '<p class="muted">Loading model metadata…</p>';
  try {
    const res = await fetch('/ml/health');
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      headline.innerText = '—';
      body.innerHTML = `<div class="notice">ML screening unavailable: ${esc(error.detail || res.status)}</div>`;
      return;
    }
    const health = await res.json();
    const metrics = health.metrics || {};
    const classifier = metrics.selected_classifier || 'classifier';
    const test = (metrics.fault_classification || {}).test || {};
    const classifierBlock = (test[classifier] || {});
    const accuracy = classifierBlock.accuracy;
    const macroRecall = (classifierBlock.classification_report || {})['macro avg']?.recall;
    const anomaly = (metrics.anomaly_detection || {}).test || {};

    headline.innerText = accuracy === undefined ? '—' : (accuracy * 100).toFixed(1) + '%';
    document.getElementById('ml-synthetic-badge').innerText = health.is_synthetic
      ? 'Trained on synthetic data'
      : 'Training data not marked synthetic';

    body.innerHTML = `
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div><p class="label">Classifier</p><p class="font-bold" style="color:var(--vs-ink)">${esc(classifier)}</p></div>
        <div><p class="label">Test accuracy</p><p class="font-bold" style="color:var(--vs-ink)">${pct(accuracy === undefined ? null : accuracy * 100)}</p></div>
        <div><p class="label">Macro recall</p><p class="font-bold" style="color:var(--vs-ink)">${pct(macroRecall === undefined ? null : macroRecall * 100)}</p></div>
        <div><p class="label">Anomaly recall</p><p class="font-bold" style="color:var(--vs-ink)">${pct(anomaly.recall === undefined ? null : anomaly.recall * 100)}</p></div>
      </div>
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
        <div><p class="label">Anomaly precision</p><p class="body-text">${pct(anomaly.precision === undefined ? null : anomaly.precision * 100)}</p></div>
        <div><p class="label">Anomaly threshold</p><p class="body-text">${esc(anomaly.threshold ?? '—')}</p></div>
        <div class="sm:col-span-2"><p class="label">Artifact versions (sha256 prefix)</p>
          <p class="body-text code" style="border:0;background:transparent;padding:0;color:var(--vs-body)">
            ${Object.entries(health.model_versions || {}).map(([k, v]) => `${esc(k)}:${esc(String(v).slice(0, 10))}`).join(' · ')}
          </p>
        </div>
      </div>`;
  } catch (e) {
    headline.innerText = '—';
    body.innerHTML = `<div class="notice">Could not reach /ml/health: ${esc(e.message)}</div>`;
  }
}

/* ---------- workbench ---------- */

async function generateSyntheticIntoWorkbench() {
  const vendorId = document.getElementById('source-vendor-select').value;
  const meters = document.getElementById('gen-meters').value || 3;
  const intervals = document.getElementById('gen-intervals').value || 4;
  const anomalies = document.getElementById('gen-inject-anomalies').checked;
  const tampers = document.getElementById('gen-inject-tampers').checked;

  try {
    const url = `/api/generate?vendor_id=${vendorId}&meter_count=${meters}&intervals=${intervals}&inject_anomalies=${anomalies}&inject_tampers=${tampers}`;
    const res = await fetch(url, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) {
      throw new Error((data && (data.detail || data.message)) || `Generation failed with ${res.status}`);
    }
    const payload = data.payload;
    document.getElementById('raw-payload-input').value =
      typeof payload === 'string' ? payload : JSON.stringify(payload, null, 2);
    clearFormError();
  } catch (e) {
    console.error('Failed to generate synthetic data', e);
    showFormError(`Failed to generate synthetic data: ${e.message}. Check the selected vendor and try again.`);
  }
}

async function loadSamplePreset(vendorId) {
  document.getElementById('source-vendor-select').value = vendorId;
  try {
    const res = await fetch(`/api/generate?vendor_id=${vendorId}&meter_count=2&intervals=4`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) {
      throw new Error((data && (data.detail || data.message)) || `Sample failed with ${res.status}`);
    }
    document.getElementById('raw-payload-input').value =
      typeof data.payload === 'string' ? data.payload : JSON.stringify(data.payload, null, 2);
    clearFormError();
    return true;
  } catch (e) {
    console.error('Preset load error', e);
    showFormError(`Could not generate a synthetic sample: ${e.message}. You can still paste a payload.`);
    return false;
  }
}

/* ---------- form validation and progress ---------- */

function showFormError(message) {
  const el = document.getElementById('form-error');
  if (!el) return;
  el.textContent = message;
  el.classList.remove('hidden');
}

function clearFormError() {
  const el = document.getElementById('form-error');
  if (el) { el.textContent = ''; el.classList.add('hidden'); }
}

function setRunStatus(message) {
  const el = document.getElementById('run-status');
  if (!el) return;
  el.textContent = message || '';
  el.classList.toggle('hidden', !message);
}

/**
 * Client-side checks only: enough to catch the obvious mistakes before a round trip.
 * The server still performs the real parse, mapping and physical validation.
 */
function validateWorkbenchInput() {
  const sourceVendor = document.getElementById('source-vendor-select').value;
  const fileInput = document.getElementById('file-upload-input');
  const raw = document.getElementById('raw-payload-input').value;

  if (fileInput.files.length > 0) {
    const file = fileInput.files[0];
    const allowedExtensions = ['.json', '.csv'];
    const name = file.name || '';
    const extension = name.includes('.') ? name.slice(name.lastIndexOf('.')).toLowerCase() : '';
    const isAllowedExtension = allowedExtensions.includes(extension);
    const isAllowedMime = ['application/json', 'text/csv', 'application/csv', 'text/plain'].includes(file.type || '');
    if (!isAllowedExtension && !isAllowedMime) {
      return {
        ok: false,
          message: `Unsupported file type: ${file.name || 'this file'}. Upload a JSON or CSV payload only.`,
        focus: 'file-upload-input',
      };
    }
      if (!isAllowedExtension || (file.type && !isAllowedMime)) {
        return {
          ok: false,
          message: 'Choose a JSON or CSV file with a matching file type.',
          focus: 'file-upload-input',
        };
      }
    if ((file.size || 0) > 5 * 1024 * 1024) {
      return {
        ok: false,
        message: 'The uploaded file is too large. Use a payload under 5 MB.',
        focus: 'file-upload-input',
      };
    }
    return { ok: true };
  }
  if (!raw.trim()) {
    return {
      ok: false,
      message: 'No payload yet. Load a sample, generate synthetic data, paste JSON/CSV, or upload a file.',
      focus: 'raw-payload-input',
    };
  }
  const format = (currentVendors[sourceVendor] || {}).format_type;
  if (format === 'json') {
    try {
      JSON.parse(raw);
    } catch (e) {
      return {
        ok: false,
        message: `This adapter expects JSON, and the payload does not parse: ${e.message}`,
        focus: 'raw-payload-input',
      };
    }
  }
  if (format === 'csv' && !raw.split(/\r?\n/).slice(0, 3).join('\n').includes(',')) {
    return {
      ok: false,
      message: 'This adapter expects CSV with a header row; no comma-separated row was found in the payload.',
      focus: 'raw-payload-input',
    };
  }
  return { ok: true };
}

function handleFetchFailure(prefix, error) {
  const detail = error && error.message ? error.message : String(error || 'Unknown error');
  console.error(prefix, error);
  showFormError(`${prefix}: ${detail}`);
}

function renderPendingStages() {
  const body = document.getElementById('stages-body');
  if (!body) return;
  const names = ['Parse', 'Syntactic validation', 'Semantic mapping', 'Physical validation', 'ML screening'];
  body.innerHTML = names.map(name => `
    <div class="stage">
      <div class="flex items-center justify-between gap-2">
        <span class="stage-name">${esc(name)}</span>
        <span class="pill">pending</span>
      </div>
      <p class="stage-meta mt-1">Waiting for the pipeline to reach this stage…</p>
    </div>
  `).join('');
}

async function runSampleValidation() {
  switchTab('workbench');
  const source = document.getElementById('source-vendor-select').value || 'alpha-hes';
  const loaded = await loadSamplePreset(source);
  if (!loaded) return;
  await runWorkbenchExecution({ sample: true });
}

async function runWorkbenchExecution(options = {}) {
  const sourceVendor = document.getElementById('source-vendor-select').value;
  const targetVendor = document.getElementById('target-vendor-select').value;
  const rawPayload = document.getElementById('raw-payload-input').value;
  const fileInput = document.getElementById('file-upload-input');
  const isSample = options.sample === true;

  const check = validateWorkbenchInput();
  if (!check.ok) {
    showFormError(check.message);
    const focusTarget = document.getElementById(check.focus);
    if (focusTarget) focusTarget.focus();
    return;
  }
  clearFormError();

  const formData = new FormData();
  formData.append('source_vendor', sourceVendor);
  formData.append('target_vendor', targetVendor);
  if (fileInput.files.length > 0) {
    formData.append('file', fileInput.files[0]);
  } else {
    formData.append('raw_payload', rawPayload);
  }

  lastRunWasSample = isSample;
  const btn = document.getElementById('btn-run-workbench');
  btn.disabled = true;
  btn.setAttribute('aria-busy', 'true');
  btn.innerHTML = '<span>Running pipeline…</span>';
  setRunStatus(`Validating ${sourceVendor}${targetVendor ? ' → ' + targetVendor : ''}. The five stages run in order; this normally takes a moment.`);

  const container = document.getElementById('results-container');
  container.classList.remove('hidden');
  const verdictTitle = document.getElementById('verdict-title');
  verdictTitle.innerText = 'Validation in progress';
  document.getElementById('verdict-reason').innerText =
    'Waiting for the pipeline result. Stage rows below are placeholders until each stage reports.';
  document.getElementById('verdict-report-link').classList.add('hidden');
  renderPendingStages();

  try {
    const res = await fetch('/api/workbench/execute', { method: 'POST', body: formData });
    const result = await res.json().catch(() => ({}));

    if (!res.ok) {
      verdictTitle.innerText = 'Validation could not run';
      document.getElementById('verdict-reason').innerText =
        `${result.detail || 'The service returned ' + res.status}. Nothing was scored; correct the input and run again.`;
      setRunStatus('');
      renderStages([]);
      showFormError(result.detail || `The service returned ${res.status}.`);
      return;
    }
    lastRun = result;
    setRunStatus('');
    displayExecutionResults(result);
  } catch (e) {
    verdictTitle.innerText = 'Validation could not run';
    document.getElementById('verdict-reason').innerText =
      `Could not reach the validation service: ${e.message}. Check that the server is running, then run again.`;
    setRunStatus('');
    renderStages([]);
    showFormError(`Network error: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.removeAttribute('aria-busy');
    btn.innerHTML = '<i data-lucide="play" class="w-4 h-4"></i><span>Run validation and transformation</span>';
    if (window.lucide) lucide.createIcons();
  }
}

function displayExecutionResults(res) {
  const container = document.getElementById('results-container');
  container.classList.remove('hidden');

  renderVerdict(res);

  document.getElementById('res-run-id').innerText = res.run_id;
  document.getElementById('res-duration').innerText = res.duration_ms + ' ms';
  document.getElementById('res-total-score').innerText = res.score.total_score;
  document.getElementById('res-summary-text').innerText = res.score.summary;
  document.getElementById('res-data-quality').innerText =
    res.data_quality ? res.data_quality.score.toFixed(1) + ' / 100' : '—';
  document.getElementById('res-model-version').innerText = res.model_version || 'unavailable';

  const reportLink = document.getElementById('report-export-link');
  reportLink.href = `/api/test-runs/${encodeURIComponent(res.run_id)}/report.html`;
  reportLink.classList.remove('hidden');

  const badge = document.getElementById('res-grade-badge');
  badge.innerText = res.score.grade;
  badge.className = `text-base ${gradeClass(res.score.grade)}`;

  document.getElementById('res-syntactic-score').innerText = res.score.syntactic_score + '%';
  document.getElementById('res-syntactic-bar').style.width = res.score.syntactic_score + '%';
  document.getElementById('res-semantic-score').innerText = res.score.semantic_score + '%';
  document.getElementById('res-semantic-bar').style.width = res.score.semantic_score + '%';
  document.getElementById('res-integrity-score').innerText = res.score.data_integrity_score + '%';
  document.getElementById('res-integrity-bar').style.width = res.score.data_integrity_score + '%';

  renderStages(res.stages || []);
  renderMlVerdict(res);
  renderIssues(res.issues || []);

  document.getElementById('res-canonical-code').innerText = JSON.stringify(res.canonical_payload, null, 2);
  document.getElementById('res-target-vendor-name').innerText = res.target_vendor || 'none';
  const targetCode = document.getElementById('res-target-code');
  if (typeof res.target_output === 'string') {
    targetCode.innerText = res.target_output;
  } else if (res.target_output) {
    targetCode.innerText = JSON.stringify(res.target_output, null, 2);
  } else {
    targetCode.innerText = '// No target transformation selected (validation only)';
  }

  if (window.lucide) lucide.createIcons();
  container.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderStages(stages) {
  const body = document.getElementById('stages-body');
  body.innerHTML = stages.map(stage => `
    <div class="stage">
      <div class="flex items-center justify-between gap-2">
        <span class="stage-name">${esc(stage.name)}</span>
        <span class="${STATUS_CLASS[stage.status] || 'pill'}">${esc(stage.status)}</span>
      </div>
      <p class="stage-meta mt-1">
        ${esc(stage.duration_ms)} ms · ${(stage.diagnostics || []).length} diagnostic(s)
      </p>
      ${stage.root_cause ? `<p class="text-xs mt-1 body-text">${esc(stage.root_cause)}</p>` : ''}
      ${stage.suggested_action ? `<p class="text-xs mt-1" style="color:var(--vs-amber-ink)">Action: ${esc(stage.suggested_action)}</p>` : ''}
    </div>
  `).join('') || '<p class="muted text-sm">No stage data returned.</p>';
}

function renderMlVerdict(res) {
  const body = document.getElementById('ml-verdict-body');
  if (res.ml_error) {
    body.innerHTML = `<div class="notice">ML screening unavailable for this run: ${esc(res.ml_error)}. Rule findings below are unaffected.</div>`;
    return;
  }
  const findings = res.ml_findings || [];
  if (!findings.length) {
    body.innerHTML = '<p class="muted">No ML flags for this run. The screen produced no warnings.</p>';
    return;
  }
  body.innerHTML = findings.map(finding => `
    <div class="p-2.5 rounded-lg" style="border:1px solid var(--vs-line);background:var(--vs-surface-alt)">
      <div class="flex items-center justify-between gap-2">
        <span class="flex items-center gap-1.5">
          <span class="tag tag-ml">ml</span>
          <span class="font-bold" style="color:var(--vs-ink)">${esc(finding.code)}</span>
        </span>
        <span class="label">${esc(finding.field || '')}</span>
      </div>
      <p class="mt-1 body-text">${esc(finding.explanation || finding.message)}</p>
      <p class="label mt-1">confidence ${Number(finding.confidence ?? 0).toFixed(3)} · ${esc(finding.confidence_source || '')}</p>
    </div>
  `).join('');
}

function issueCard(issue) {
  const isError = issue.severity === 'ERROR';
  return `
    <div class="p-2.5 rounded-lg text-xs" style="border:1px solid ${isError ? 'var(--vs-red)' : 'var(--vs-amber)'};
         background:${isError ? 'var(--vs-red-tint)' : 'var(--vs-amber-tint)'}">
      <div class="flex items-center justify-between gap-2">
        <span class="flex items-center gap-1.5">
          <span class="tag tag-rule">rule</span>
          <span class="font-bold" style="color:${isError ? 'var(--vs-red)' : 'var(--vs-amber-ink)'}">[${esc(issue.severity)}] ${esc(issue.code)}</span>
        </span>
        <span class="label code" style="border:0;background:transparent;padding:0">${esc(issue.field || 'envelope')}</span>
      </div>
      <p class="mt-1" style="color:var(--vs-ink)">${esc(issue.explanation || issue.message)}</p>
      ${issue.suggested_fix ? `<p class="mt-1 muted">Suggested action: ${esc(issue.suggested_fix)}</p>` : ''}
    </div>`;
}

function renderIssues(issues) {
  allIssues = issues;
  diagnosticsExpanded = false;
  const list = document.getElementById('res-issues-list');
  const summary = document.getElementById('diagnostics-summary');
  const toggle = document.getElementById('diagnostics-toggle');
  document.getElementById('res-issues-count').innerText = issues.length;

  if (!issues.length) {
    list.innerHTML = '<div class="notice notice-info">No rule violations detected for this payload.</div>';
    if (summary) summary.innerText = 'Every configured rule check passed.';
    if (toggle) { toggle.classList.add('hidden'); toggle.setAttribute('aria-expanded', 'false'); }
    return;
  }

  const errors = issues.filter(i => i.severity === 'ERROR').length;
  const warnings = issues.length - errors;
  const first = issues.find(i => i.severity === 'ERROR') || issues[0];
  if (summary) {
    summary.innerText =
      `${errors} error(s) · ${warnings} warning(s). Most important: [${first.severity}] ${first.code}` +
      `${first.field ? ' on ' + first.field : ''}.`;
  }

  const visible = issues.slice(0, DEFAULT_VISIBLE_DIAGNOSTICS);
  list.innerHTML = visible.map(issueCard).join('');
  if (toggle) {
    const hasMore = issues.length > DEFAULT_VISIBLE_DIAGNOSTICS;
    toggle.classList.toggle('hidden', !hasMore);
    toggle.innerText = hasMore ? `Show all ${issues.length} diagnostics` : '';
    toggle.setAttribute('aria-expanded', 'false');
  }
}

function toggleAllDiagnostics() {
  const list = document.getElementById('res-issues-list');
  const toggle = document.getElementById('diagnostics-toggle');
  if (!list) return;
  diagnosticsExpanded = !diagnosticsExpanded;
  const issues = diagnosticsExpanded ? allIssues : allIssues.slice(0, DEFAULT_VISIBLE_DIAGNOSTICS);
  list.innerHTML = issues.map(issueCard).join('');
  if (toggle) {
    toggle.innerText = diagnosticsExpanded ? 'Show fewer diagnostics' : `Show all ${allIssues.length} diagnostics`;
    toggle.setAttribute('aria-expanded', String(diagnosticsExpanded));
  }
}

function focusDiagnostics() {
  if (!diagnosticsExpanded && allIssues.length > DEFAULT_VISIBLE_DIAGNOSTICS) toggleAllDiagnostics();
  const card = document.getElementById('diagnostics-card');
  if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/** Overall outcome first, derived only from the returned issues, stages and score. */
function renderVerdict(res) {
  const issues = res.issues || [];
  const errors = issues.filter(i => i.severity === 'ERROR');
  const warnings = issues.filter(i => i.severity !== 'ERROR');
  const mlFlags = res.ml_findings || [];
  const score = Number(res.score && res.score.total_score);
  const title = document.getElementById('verdict-title');
  const reason = document.getElementById('verdict-reason');
  const card = document.getElementById('result-verdict');
  const sampleNote = document.getElementById('verdict-sample-note');
  const reportLink = document.getElementById('verdict-report-link');
  if (!title) return;

  let label;
  if (res.conformance_outcome === 'INCOMPLETE') {
    label = 'Incomplete assessment';
    card.style.borderLeft = '4px solid var(--vs-amber)';
    title.style.color = 'var(--vs-amber-ink)';
  } else if (errors.length) {
    label = 'Failed validation';
    card.style.borderLeft = '4px solid var(--vs-red)';
    title.style.color = 'var(--vs-red)';
  } else if (warnings.length || mlFlags.length || (Number.isFinite(score) && score < 85)) {
    label = 'Validated with warnings';
    card.style.borderLeft = '4px solid var(--vs-amber)';
    title.style.color = 'var(--vs-amber-ink)';
  } else {
    label = 'Passed validation';
    card.style.borderLeft = '4px solid var(--vs-teal-deep)';
    title.style.color = 'var(--vs-teal-deep)';
  }
  title.innerText = `${label} · score ${Number.isFinite(score) ? score : '—'}%`;

  const parts = [];
  if (errors.length) parts.push(`${errors.length} rule error(s)`);
  if (warnings.length) parts.push(`${warnings.length} rule warning(s)`);
  if (mlFlags.length) parts.push(`${mlFlags.length} ML flag(s) for review`);
  const first = errors[0] || warnings[0];
  const lead = first
    ? ` First: [${first.severity}] ${first.code}${first.field ? ' on ' + first.field : ''} — ${first.explanation || first.message}`
    : '';
  const advice = res.conformance_outcome === 'INCOMPLETE'
    ? ' Provide at least one valid meter reading, then run again.'
    : errors.length
    ? ' Fix the error(s) below and run again.'
    : (warnings.length || mlFlags.length)
      ? ' Check the renamed or flagged fields below; the payload is usable if those are expected.'
      : ' No rule violations were recorded for this payload.';
  reason.innerText = (parts.length ? parts.join(' · ') + '.' : 'No diagnostics were recorded.') + lead + advice;

  if (sampleNote) sampleNote.hidden = !lastRunWasSample;
  if (reportLink) {
    reportLink.href = `/api/test-runs/${encodeURIComponent(res.run_id)}/report.html`;
    reportLink.classList.remove('hidden');
  }
}

async function runQuickDemo(source, target) {
  switchTab('workbench');
  document.getElementById('source-vendor-select').value = source;
  document.getElementById('target-vendor-select').value = target;
  await generateSyntheticIntoWorkbench();
  await runWorkbenchExecution();
}

/* ---------- compare ---------- */

async function loadRunOptions() {
  const baseline = document.getElementById('compare-baseline');
  const candidate = document.getElementById('compare-candidate');
  if (!baseline || !candidate) return;
  try {
    const runs = await (await fetch('/api/test-runs?limit=100')).json();
    if (!runs.length) {
      baseline.innerHTML = '<option value="">No runs stored</option>';
      candidate.innerHTML = '<option value="">No runs stored</option>';
      return;
    }
    const options = runs.map(r => `<option value="${esc(r.run_id)}">${esc(r.run_id)} · ${esc(r.source_vendor)} · ${esc(r.total_score)}%</option>`).join('');
    baseline.innerHTML = options;
    candidate.innerHTML = options;
    if (runs.length > 1) candidate.selectedIndex = 1;
  } catch (e) {
    console.error('Failed to load run options', e);
  }
}

async function runComparison() {
  const baselineId = document.getElementById('compare-baseline').value;
  const candidateId = document.getElementById('compare-candidate').value;
  const body = document.getElementById('compare-body');
  if (!baselineId || !candidateId) {
    body.innerHTML = '<p class="muted">Two stored runs are required. Run validation in the Workbench first.</p>';
    return;
  }
  if (baselineId === candidateId) {
    body.innerHTML = '<p class="muted">Choose two different runs.</p>';
    return;
  }
  body.innerHTML = '<p class="muted">Comparing…</p>';
  try {
    const res = await fetch('/api/compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ baseline_run_id: baselineId, candidate_run_id: candidateId }),
    });
    const data = await res.json();
    if (!res.ok) {
      body.innerHTML = `<div class="notice">${esc(data.detail || 'Comparison failed')}</div>`;
      return;
    }
    const delta = data.score_deltas;
    const deltaRow = (label, value) => `
      <div><p class="label">${label}</p>
      <p class="font-bold" style="color:${value > 0 ? 'var(--vs-teal-deep)' : value < 0 ? 'var(--vs-red)' : 'var(--vs-ink)'}">
        ${value > 0 ? '+' : ''}${value}
      </p></div>`;

    body.innerHTML = `
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        ${deltaRow('Syntactic', delta.syntactic_score)}
        ${deltaRow('Semantic', delta.semantic_score)}
        ${deltaRow('Data integrity', delta.data_integrity_score)}
        ${deltaRow('Total', delta.total_score)}
      </div>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
        ${['resolved', 'persistent', 'newly_introduced'].map(key => `
          <div>
            <p class="font-bold mb-1" style="color:var(--vs-ink)">
              ${key.replace('_', ' ')} (${(data[key] || []).length})
            </p>
            ${(data[key] || []).length
              ? `<ul class="space-y-1">${data[key].map(item => {
                  const issue = key === 'persistent' ? item.candidate : item;
                  return `<li class="p-1.5 rounded" style="background:var(--vs-surface-alt)">
                    <span class="tag ${key === 'newly_introduced' ? 'tag-ml' : 'tag-rule'}">${esc(issue.severity || '')}</span>
                    ${esc(issue.code || '')}${issue.field ? ' · ' + esc(issue.field) : ''}
                  </li>`;
                }).join('')}</ul>`
              : '<p class="muted">None.</p>'}
          </div>`).join('')}
      </div>
      ${delta.total_score !== 0 && (data.resolved || []).length + (data.newly_introduced || []).length === 0
        ? `<p class="notice mt-3" role="note">
             The total score changed by ${esc(delta.total_score)} point(s), but no stored rule diagnostic
             differs between these runs. The stored diagnostics cannot explain this delta — it can come
             from record counts or from checks that are not persisted per issue.
           </p>`
        : ''}`;
    renderContractDiff(baselineId, candidateId, data);
  } catch (e) {
    body.innerHTML = `<div class="notice">Comparison failed: ${esc(e.message)}</div>`;
  }
}

async function renderContractDiff(baselineId, candidateId, comparison) {
  const container = document.getElementById('compare-contract-body');
  try {
    const [baseline, candidate] = await Promise.all([
      fetch(`/api/test-runs/${encodeURIComponent(baselineId)}`).then(r => r.json()),
      fetch(`/api/test-runs/${encodeURIComponent(candidateId)}`).then(r => r.json()),
    ]);
    const resolvedCodes = new Set((comparison.resolved || []).map(i => i.code + '|' + (i.field || '')));
    const introducedCodes = new Set((comparison.newly_introduced || []).map(i => i.code + '|' + (i.field || '')));

    const column = (title, run, highlightSet, highlightLabel, extraClass) => `
      <div class="card card-pad">
        <p class="font-bold mb-1" style="color:var(--vs-ink)">${esc(title)}: ${esc(run.run_id)}</p>
        <p class="label mb-2">${esc(run.source_vendor)} · score ${esc(run.score.total_score)}% · ${esc(run.score.grade)}</p>
        ${(run.issues || []).length ? `<ul class="space-y-1">${run.issues.map(issue => {
          const key = issue.code + '|' + (issue.field || '');
          const flagged = highlightSet.has(key);
          return `<li class="p-1.5 rounded flex items-center justify-between gap-2" style="background:${flagged ? 'var(--vs-amber-tint)' : 'var(--vs-surface-alt)'}">
            <span>${esc(issue.code)}${issue.field ? ' · ' + esc(issue.field) : ''}</span>
            ${flagged ? `<span class="tag ${extraClass}">${highlightLabel}</span>` : ''}
          </li>`;
        }).join('')}</ul>` : '<p class="muted">No rule issues recorded.</p>'}
      </div>`;

    container.innerHTML =
      column('Baseline', baseline, resolvedCodes, 'resolved', 'tag-rule') +
      column('Candidate', candidate, introducedCodes, 'new', 'tag-ml');
  } catch (e) {
    container.innerHTML = `<p class="muted">Could not load run details: ${esc(e.message)}</p>`;
  }
}

/* ---------- round trip ---------- */

async function loadRoundtripSample() {
  const vendorA = document.getElementById('rt-vendor-a').value;
  try {
    const res = await fetch(`/api/generate?vendor_id=${vendorA}&meter_count=1&intervals=2`, { method: 'POST' });
    const data = await res.json();
    document.getElementById('rt-payload').value =
      typeof data.payload === 'string' ? data.payload : JSON.stringify(data.payload, null, 2);
  } catch (e) {
    console.error('Round-trip sample failed', e);
  }
}

async function runRoundtrip() {
  const vendorA = document.getElementById('rt-vendor-a').value;
  const vendorB = document.getElementById('rt-vendor-b').value;
  const raw = document.getElementById('rt-payload').value.trim();
  const body = document.getElementById('rt-body');
  if (!raw) {
    body.innerHTML = '<p class="muted">Load or paste a vendor A payload first.</p>';
    return;
  }
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (e) {
    payload = raw;
  }
  body.innerHTML = '<p class="muted">Running round trip…</p>';
  try {
    const res = await fetch('/api/roundtrip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vendor_a: vendorA, vendor_b: vendorB, payload }),
    });
    const data = await res.json();
    if (!res.ok) {
      body.innerHTML = `<div class="notice">Round trip failed: ${esc(data.detail || res.status)}</div>`;
      return;
    }
    const diffs = data.field_differences || [];
    body.innerHTML = `
      <p class="text-xs muted mb-2">
        ${esc(vendorA)} → canonical → ${esc(vendorB)} → canonical ·
        ${diffs.length} field difference(s) · ${(data.adapter_issues || []).length} adapter diagnostic(s)
      </p>
      ${diffs.length ? `
        <div class="overflow-x-auto">
          <table class="vs">
            <thead><tr><th>Reading</th><th>Field</th><th>Before</th><th>After</th></tr></thead>
            <tbody>
              ${diffs.map(d => `<tr>
                <td>${esc(d.reading_index)}</td>
                <td>${esc(d.field || d.difference || '—')}</td>
                <td class="code" style="background:transparent;border:0;padding:0 .6rem;color:var(--vs-body)">${esc(JSON.stringify(d.before))}</td>
                <td class="code" style="background:transparent;border:0;padding:0 .6rem;color:var(--vs-body)">${esc(JSON.stringify(d.after))}</td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>` : '<div class="notice notice-info">The round trip preserved every canonical field.</div>'}
    `;
  } catch (e) {
    body.innerHTML = `<div class="notice">Round trip failed: ${esc(e.message)}</div>`;
  }
}

/* ---------- suites ---------- */

async function loadSuites() {
  const body = document.getElementById('suites-body');
  if (!body) return;
  body.innerHTML = '<tr><td colspan="4" class="muted">Loading suites…</td></tr>';
  try {
    const suites = await (await fetch('/api/suites')).json();
    if (!suites.length) {
      body.innerHTML = emptyRow(4, 'layers', 'No suites saved yet. Create one with POST /api/suites (see /docs).');
      if (window.lucide) lucide.createIcons();
      return;
    }
    body.innerHTML = suites.map(suite => `
      <tr>
        <td><strong style="color:var(--vs-ink)">${esc(suite.name)}</strong><div class="label">id ${esc(suite.id)}</div></td>
        <td>${(suite.scenarios || []).length}</td>
        <td>${esc(fmtDate(suite.created_at))}</td>
        <td><button class="btn" data-role-required="operator" onclick="runSuite(${Number(suite.id)})">Run suite</button></td>
      </tr>
    `).join('');
    applyRoleVisibility();
  } catch (e) {
    body.innerHTML = `<tr><td colspan="4" class="muted">Could not load suites: ${esc(e.message)}</td></tr>`;
  }
}

async function runSuite(suiteId) {
  const result = document.getElementById('suite-run-result');
  result.innerHTML = '<p class="muted">Running suite…</p>';
  try {
    const res = await fetch(`/api/suites/${suiteId}/run`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) {
      result.innerHTML = `<div class="notice">${esc(data.detail || 'Suite run failed')}</div>`;
      return;
    }
    result.innerHTML = `
      <p class="text-sm mb-2">
        Suite run ${esc(data.suite_run_id)} · <strong style="color:var(--vs-teal-deep)">${esc(data.passed_count)} passed</strong> ·
        <strong style="color:var(--vs-red)">${esc(data.failed_count)} failed</strong>
      </p>
      <ul class="space-y-1 text-xs">
        ${(data.results || []).map(item => `<li class="flex items-center justify-between gap-2 p-1.5 rounded" style="background:var(--vs-surface-alt)">
          <span>Scenario ${esc(item.scenario_index)}${item.run_id ? ' · ' + esc(item.run_id) : ''}</span>
          <span class="${item.status === 'passed' ? 'pill pill-teal' : 'pill pill-red'}">${esc(item.status)}</span>
        </li>`).join('')}
      </ul>`;
  } catch (e) {
    result.innerHTML = `<div class="notice">Suite run failed: ${esc(e.message)}</div>`;
  }
}

/* ---------- history ---------- */

async function loadHistoryRuns() {
  const tbody = document.getElementById('history-runs-body');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="8" class="muted">Loading runs…</td></tr>';
  try {
    const runs = await (await fetch('/api/test-runs')).json();
    if (!runs.length) {
      tbody.innerHTML = emptyRow(8, 'history', 'No historical runs recorded yet.');
      if (window.lucide) lucide.createIcons();
      return;
    }
    tbody.innerHTML = runs.map(r => `
      <tr>
        <td class="code" style="background:transparent;border:0;padding:0 .6rem;color:var(--vs-teal-deep)">${esc(r.run_id)}</td>
        <td>${esc(fmtDate(r.execution_time))}</td>
        <td>${esc(r.source_vendor)}</td>
        <td>${esc(r.target_vendor || 'none')}</td>
        <td>${esc(r.valid_records)} / ${esc(r.total_records)}</td>
        <td>${scoreCell(r.total_score)}</td>
        <td><span class="${gradeClass(r.grade)}">${esc(r.grade)}</span></td>
        <td class="flex flex-wrap gap-2">
          <button class="btn" onclick="viewRunDetail('${esc(r.run_id)}')">Detail</button>
          <a class="btn" href="/api/test-runs/${encodeURIComponent(r.run_id)}/report.html" target="_blank" rel="noopener">Report</a>
        </td>
      </tr>
    `).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="8" class="muted">Could not load runs: ${esc(e.message)}</td></tr>`;
  }
}

async function viewRunDetail(runId) {
  try {
    const r = await (await fetch(`/api/test-runs/${encodeURIComponent(runId)}`)).json();
    document.getElementById('modal-title').innerText = `Run ${r.run_id}`;
    document.getElementById('modal-content').innerHTML = `
      <div class="grid grid-cols-2 gap-3 p-3 rounded-lg" style="background:var(--vs-surface-alt)">
        <div><span class="label">Source</span><p style="color:var(--vs-ink)">${esc(r.source_vendor)}</p></div>
        <div><span class="label">Target</span><p style="color:var(--vs-ink)">${esc(r.target_vendor || 'none')}</p></div>
        <div><span class="label">Score</span><p style="color:var(--vs-ink)">${esc(r.score.total_score)}% (${esc(r.score.grade)})</p></div>
        <div><span class="label">Data quality</span><p style="color:var(--vs-ink)">${r.data_quality_score === null ? 'not recorded' : esc(r.data_quality_score)}</p></div>
        <div><span class="label">Model version</span><p style="color:var(--vs-ink)">${esc(r.model_version || 'not recorded')}</p></div>
        <div><span class="label">Duration</span><p style="color:var(--vs-ink)">${esc(r.duration_ms)} ms</p></div>
      </div>
      <div>
        <p class="font-bold mb-1" style="color:var(--vs-ink)">Rule diagnostics (${(r.issues || []).length})</p>
        <div class="space-y-1">
          ${(r.issues || []).map(iss => `
            <div class="p-2 rounded" style="background:var(--vs-surface-alt)">
              <p class="font-bold" style="color:${iss.severity === 'ERROR' ? 'var(--vs-red)' : 'var(--vs-amber-ink)'}">
                [${esc(iss.severity)}] ${esc(iss.code)}
              </p>
              <p style="color:var(--vs-ink)">${esc(iss.message)}</p>
              ${iss.suggested_fix ? `<p class="muted">Fix: ${esc(iss.suggested_fix)}</p>` : ''}
            </div>`).join('') || '<p class="muted">No issues recorded.</p>'}
        </div>
      </div>
      <div>
        <p class="font-bold mb-1" style="color:var(--vs-ink)">Raw payload preview</p>
        <pre class="code">${esc(r.raw_preview || '// none')}</pre>
      </div>
      <a class="btn" href="${esc(r.report_url || '/api/test-runs/' + encodeURIComponent(r.run_id) + '/report.html')}" target="_blank" rel="noopener">Export report</a>
    `;
    document.getElementById('detail-modal').classList.remove('hidden');
    document.getElementById('detail-modal').classList.add('flex');
    if (window.lucide) lucide.createIcons();
  } catch (e) {
    alert('Failed to load run details: ' + e.message);
  }
}

function closeModal() {
  document.getElementById('detail-modal').classList.add('hidden');
  document.getElementById('detail-modal').classList.remove('flex');
}

async function copyCode(elementId) {
  const el = document.getElementById(elementId);
  const text = el ? (el.innerText || el.value || '') : '';
  if (!text) {
    alert('There is nothing to copy yet.');
    return;
  }

  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      const helper = document.createElement('textarea');
      helper.value = text;
      helper.setAttribute('readonly', 'true');
      helper.style.position = 'fixed';
      helper.style.top = '-9999px';
      document.body.appendChild(helper);
      helper.select();
      const copied = document.execCommand('copy');
      document.body.removeChild(helper);
      if (!copied) throw new Error('Copy command was rejected by the browser.');
    }
    alert('Payload copied to clipboard.');
  } catch (error) {
    console.error('Clipboard copy failed', error);
    alert(`Clipboard copy failed: ${error.message || 'unknown browser error'}`);
  }
}

async function openUserAdmin() {
  const modal = document.getElementById('detail-modal');
  document.getElementById('modal-title').textContent = 'User management';
  document.getElementById('modal-content').innerHTML = `
    <form id="create-user-form" class="grid grid-cols-1 sm:grid-cols-4 gap-3 items-end">
      <div><label class="label" for="new-username">Username</label><input id="new-username" class="input mt-1 w-full" minlength="3" maxlength="64" required></div>
      <div><label class="label" for="new-password">Temporary password</label><input id="new-password" type="password" class="input mt-1 w-full" minlength="12" maxlength="256" autocomplete="new-password" required></div>
      <div><label class="label" for="new-role">Role</label><select id="new-role" class="select mt-1 w-full"><option value="operator">Operator</option><option value="viewer">Viewer / Auditor</option><option value="admin">Administrator</option></select></div>
      <button class="btn btn-primary" type="submit">Create account</button>
    </form>
    <p id="user-admin-error" class="notice mt-3 hidden" role="status"></p>
    <div id="user-admin-list" class="mt-4 overflow-x-auto">Loading accounts…</div>`;
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  document.getElementById('create-user-form').addEventListener('submit', createManagedUser);
  await loadManagedUsers();
}

async function loadManagedUsers() {
  const list = document.getElementById('user-admin-list');
  if (!list) return;
  try {
    const response = await fetch('/auth/users');
    const users = await response.json();
    if (!response.ok) throw new Error(users.detail || `Could not load users (${response.status}).`);
    list.innerHTML = `<table class="vs w-full"><thead><tr><th>User</th><th>Role</th><th>Status</th><th>Actions</th></tr></thead><tbody>
      ${users.map(user => `
        <tr>
          <td>${esc(user.username)}</td>
          <td><select id="user-role-${Number(user.id)}" class="select">
            ${['admin', 'operator', 'viewer'].map(role => `<option value="${role}" ${role === user.role ? 'selected' : ''}>${role}</option>`).join('')}
          </select></td>
          <td>${user.is_active ? 'Active' : 'Disabled'}</td>
          <td class="space-x-1">
            <button class="btn" type="button" onclick="saveManagedUser(${Number(user.id)}, ${!user.is_active})">Save role / ${user.is_active ? 'disable' : 'enable'}</button>
            <input id="user-password-${Number(user.id)}" type="password" class="input mt-1" minlength="12" maxlength="256" autocomplete="new-password" aria-label="New password for ${esc(user.username)}">
            <button class="btn" type="button" onclick="resetManagedPassword(${Number(user.id)})">Reset password</button>
          </td>
        </tr>`).join('')}
    </tbody></table>`;
  } catch (error) {
    list.textContent = `Could not load accounts: ${error.message}`;
  }
}

function showUserAdminError(message) {
  const error = document.getElementById('user-admin-error');
  if (!error) return;
  error.textContent = message;
  error.classList.remove('hidden');
}

async function createManagedUser(event) {
  event.preventDefault();
  const payload = {
    username: document.getElementById('new-username').value,
    password: document.getElementById('new-password').value,
    role: document.getElementById('new-role').value,
  };
  try {
    const response = await fetch('/auth/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `Account creation failed (${response.status}).`);
    document.getElementById('create-user-form').reset();
    await loadManagedUsers();
    showUserAdminError(`Account ${result.username} created as ${result.role}.`);
  } catch (error) {
    showUserAdminError(error.message);
  }
}

async function saveManagedUser(userId, active) {
  const role = document.getElementById(`user-role-${userId}`).value;
  try {
    const response = await fetch(`/auth/users/${userId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role, is_active: active }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `Account update failed (${response.status}).`);
    await loadManagedUsers();
    showUserAdminError(`Account ${result.username} updated.`);
  } catch (error) {
    showUserAdminError(error.message);
  }
}

async function resetManagedPassword(userId) {
  const field = document.getElementById(`user-password-${userId}`);
  if (!field || field.value.length < 12) {
    showUserAdminError('Enter a temporary password with at least 12 characters.');
    return;
  }
  try {
    const response = await fetch(`/auth/users/${userId}/password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: field.value }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `Password reset failed (${response.status}).`);
    field.value = '';
    showUserAdminError('Password updated; active sessions for this account were revoked.');
  } catch (error) {
    showUserAdminError(error.message);
  }
}
