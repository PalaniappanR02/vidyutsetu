/**
 * VidyutSetu workbench frontend logic.
 * All numbers come from the API; nothing here invents analytics.
 */

let activeTab = 'overview';
let currentVendors = {};
let lastRun = null;

const STATUS_CLASS = {
  pass: 'pill pill-teal',
  warn: 'pill pill-amber',
  fail: 'pill pill-red',
  skipped: 'pill',
};

document.addEventListener('DOMContentLoaded', async () => {
  applyStoredTheme();
  if (window.lucide) lucide.createIcons();
  await loadVendors();
  await refreshDashboard();
  await loadMlHealth();
  await renderHeatmap();
});

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
    currentVendors = await res.json();
  } catch (e) {
    console.error('Failed to load vendors', e);
  }
}

function renderVendorCards() {
  const container = document.getElementById('vendor-cards-grid');
  if (!container) return;
  const vendors = Object.values(currentVendors || {});
  if (!vendors.length) {
    container.innerHTML = '<p class="muted text-sm">No adapters reported by /api/vendors.</p>';
    return;
  }
  container.innerHTML = vendors.map(v => `
    <div class="card card-pad space-y-3">
      <div class="flex items-start justify-between gap-2">
        <div>
          <span class="pill pill-teal">${esc(v.system_type)}</span>
          <h3 class="font-bold mt-1" style="color:var(--vs-ink)">${esc(v.name)}</h3>
          <p class="label code" style="border:0;background:transparent;padding:0;color:var(--vs-muted)">${esc(v.vendor_id)} · v${esc(v.version)}</p>
        </div>
        <span class="pill">${esc(v.format_type)}</span>
      </div>
      <p class="text-xs body-text leading-relaxed">${esc(v.description)}</p>
      <div class="pt-2 flex items-center justify-between text-xs" style="border-top:1px solid var(--vs-line)">
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

    document.getElementById('stat-total-runs').innerText = totalRuns;
    document.getElementById('stat-total-runs-hint').innerText = totalRuns
      ? `${Object.keys(data.vendor_usage || {}).length} adapter(s) used so far.`
      : 'No runs recorded yet — start one in Workbench.';

    document.getElementById('stat-avg-score').innerText = totalRuns ? avgScore.toFixed(1) + '%' : '0%';
    document.getElementById('stat-avg-score-hint').innerText = totalRuns
      ? `Across the most recent ${Math.min(totalRuns, 100)} runs.`
      : 'Available after your first run.';

    document.getElementById('stat-adapters').innerText = data.active_vendor_adapters || 0;

    const tbody = document.getElementById('recent-runs-table-body');
    const runs = data.recent_runs || [];
    if (!runs.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="muted">No runs yet. Open Workbench to execute the first validation.</td></tr>`;
      return;
    }
    tbody.innerHTML = runs.map(r => `
      <tr>
        <td class="code" style="background:transparent;border:0;padding:0 .6rem;color:var(--vs-teal-deep)">${esc(r.run_id)}</td>
        <td>${esc(new Date(r.execution_time).toLocaleString())}</td>
        <td>${esc(r.source_vendor)}</td>
        <td>${esc(r.target_vendor || 'none')}</td>
        <td>${esc(r.total_records)}</td>
        <td><strong style="color:var(--vs-ink)">${esc(r.total_score)}%</strong></td>
        <td><span class="${r.total_score >= 85 ? 'pill pill-teal' : 'pill pill-amber'}">${esc(r.grade)}</span></td>
        <td><a class="link" href="/api/test-runs/${encodeURIComponent(r.run_id)}/report.html" target="_blank" rel="noopener">Report</a></td>
      </tr>
    `).join('');
  } catch (e) {
    console.error('Failed to refresh overview', e);
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
      container.innerHTML = '<p class="muted text-sm">No stored runs yet, so there is nothing to plot.</p>';
      caption.innerText = '';
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

    const header = `<tr><th>Vendor</th>${SCORE_BANDS.map(b => `<th class="band">${b.label}</th>`).join('')}</tr>`;
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

    container.innerHTML = `<table class="heat"><thead>${header}</thead><tbody>${rows}</tbody></table>`;
    caption.innerText = `Score distribution of ${runs.length} stored run(s). Cell intensity is the run count per band.`;
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
    const payload = data.payload;
    document.getElementById('raw-payload-input').value =
      typeof payload === 'string' ? payload : JSON.stringify(payload, null, 2);
  } catch (e) {
    alert('Failed to generate synthetic data: ' + e.message);
  }
}

async function loadSamplePreset(vendorId) {
  document.getElementById('source-vendor-select').value = vendorId;
  try {
    const res = await fetch(`/api/generate?vendor_id=${vendorId}&meter_count=2&intervals=4`, { method: 'POST' });
    const data = await res.json();
    document.getElementById('raw-payload-input').value =
      typeof data.payload === 'string' ? data.payload : JSON.stringify(data.payload, null, 2);
  } catch (e) {
    console.error('Preset load error', e);
  }
}

async function runWorkbenchExecution() {
  const sourceVendor = document.getElementById('source-vendor-select').value;
  const targetVendor = document.getElementById('target-vendor-select').value;
  const rawPayload = document.getElementById('raw-payload-input').value;
  const fileInput = document.getElementById('file-upload-input');

  const formData = new FormData();
  formData.append('source_vendor', sourceVendor);
  formData.append('target_vendor', targetVendor);

  if (fileInput.files.length > 0) {
    formData.append('file', fileInput.files[0]);
  } else if (rawPayload.trim()) {
    formData.append('raw_payload', rawPayload);
  } else {
    alert('Provide a payload or upload a file first.');
    return;
  }

  const btn = document.getElementById('btn-run-workbench');
  btn.disabled = true;
  btn.innerHTML = '<span>Running pipeline…</span>';

  try {
    const res = await fetch('/api/workbench/execute', { method: 'POST', body: formData });
    const result = await res.json();
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="play" class="w-4 h-4"></i><span>Run validation and transformation</span>';
    if (window.lucide) lucide.createIcons();

    if (res.status !== 200) {
      alert('Execution failed: ' + (result.detail || 'Unknown error'));
      return;
    }
    lastRun = result;
    displayExecutionResults(result);
  } catch (e) {
    btn.disabled = false;
    btn.innerHTML = '<span>Run validation and transformation</span>';
    alert('Error running test: ' + e.message);
  }
}

function displayExecutionResults(res) {
  const container = document.getElementById('results-container');
  container.classList.remove('hidden');

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
  badge.className = res.score.total_score >= 85 ? 'pill pill-teal text-base'
    : res.score.total_score >= 70 ? 'pill pill-amber text-base' : 'pill pill-red text-base';

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

function renderIssues(issues) {
  const list = document.getElementById('res-issues-list');
  document.getElementById('res-issues-count').innerText = issues.length;
  if (!issues.length) {
    list.innerHTML = '<div class="notice notice-info">No rule violations detected for this payload.</div>';
    return;
  }
  list.innerHTML = issues.map(issue => {
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
  }).join('');
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
    body.innerHTML = '<p class="muted">Two stored runs are required.</p>';
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
      </div>`;
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
      body.innerHTML = '<tr><td colspan="4" class="muted">No suites saved yet. Create one with POST /api/suites (see /docs).</td></tr>';
      return;
    }
    body.innerHTML = suites.map(suite => `
      <tr>
        <td><strong style="color:var(--vs-ink)">${esc(suite.name)}</strong><div class="label">id ${esc(suite.id)}</div></td>
        <td>${(suite.scenarios || []).length}</td>
        <td>${esc(suite.created_at ? new Date(suite.created_at).toLocaleString() : '—')}</td>
        <td><button class="btn" onclick="runSuite(${Number(suite.id)})">Run suite</button></td>
      </tr>
    `).join('');
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
      tbody.innerHTML = '<tr><td colspan="8" class="muted">No historical runs recorded yet.</td></tr>';
      return;
    }
    tbody.innerHTML = runs.map(r => `
      <tr>
        <td class="code" style="background:transparent;border:0;padding:0 .6rem;color:var(--vs-teal-deep)">${esc(r.run_id)}</td>
        <td>${esc(new Date(r.execution_time).toLocaleString())}</td>
        <td>${esc(r.source_vendor)}</td>
        <td>${esc(r.target_vendor || 'none')}</td>
        <td>${esc(r.valid_records)} / ${esc(r.total_records)}</td>
        <td><strong style="color:var(--vs-ink)">${esc(r.total_score)}%</strong></td>
        <td><span class="${r.total_score >= 85 ? 'pill pill-teal' : 'pill pill-amber'}">${esc(r.grade)}</span></td>
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

function copyCode(elementId) {
  const text = document.getElementById(elementId).innerText;
  navigator.clipboard.writeText(text);
  alert('Payload copied to clipboard.');
}
