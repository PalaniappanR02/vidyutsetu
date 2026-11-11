/**
 * VidyutSetu Enterprise Frontend Application Logic
 */

let activeTab = 'dashboard';
let currentVendors = {};

document.addEventListener('DOMContentLoaded', async () => {
  if (window.lucide) {
    lucide.createIcons();
  }
  await loadVendors();
  await refreshDashboard();
});

function switchTab(tabId) {
  activeTab = tabId;
  document.querySelectorAll('.tab-view').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.nav-tab').forEach(el => {
    el.classList.remove('bg-brand-600', 'text-white', 'shadow-sm');
    el.classList.add('text-slate-400');
  });

  const activeView = document.getElementById(`view-${tabId}`);
  const activeBtn = document.getElementById(`tab-btn-tab-${tabId}`) || document.getElementById(`tab-btn-${tabId}`);
  if (activeView) activeView.classList.remove('hidden');
  if (activeBtn) {
    activeBtn.classList.remove('text-slate-400');
    activeBtn.classList.add('bg-brand-600', 'text-white', 'shadow-sm');
  }

  if (window.lucide) lucide.createIcons();

  if (tabId === 'dashboard') refreshDashboard();
  if (tabId === 'history') loadHistoryRuns();
  if (tabId === 'vendors') renderVendorCards();
}

async function loadVendors() {
  try {
    const res = await fetch('/api/vendors');
    currentVendors = await res.json();
  } catch (e) {
    console.error('Failed to load vendors', e);
  }
}

async function refreshDashboard() {
  try {
    const res = await fetch('/api/stats');
    const data = await res.json();
    document.getElementById('stat-total-runs').innerText = data.total_test_runs || 0;
    document.getElementById('stat-avg-score').innerText = (data.average_interoperability_score || 0) + '%';
    document.getElementById('stat-adapters').innerText = data.active_vendor_adapters || 4;

    const tbody = document.getElementById('recent-runs-table-body');
    tbody.innerHTML = '';
    if (!data.recent_runs || data.recent_runs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" class="py-6 text-center text-slate-500 font-sans">No test runs executed yet. Launch a test from the Workbench tab!</td></tr>`;
      return;
    }

    data.recent_runs.forEach(r => {
      const tr = document.createElement('tr');
      tr.className = 'hover:bg-slate-800/40 transition cursor-pointer';
      tr.onclick = () => viewRunDetail(r.run_id);

      const badgeColor = r.total_score >= 85 ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' :
                         r.total_score >= 70 ? 'text-amber-400 bg-amber-500/10 border-amber-500/20' :
                         'text-rose-400 bg-rose-500/10 border-rose-500/20';

      tr.innerHTML = `
        <td class="py-2.5 px-3 font-semibold text-brand-400">${r.run_id}</td>
        <td class="py-2.5 px-3 text-slate-300 font-sans">${new Date(r.execution_time).toLocaleTimeString()}</td>
        <td class="py-2.5 px-3 font-sans text-slate-200">${r.source_vendor}</td>
        <td class="py-2.5 px-3 font-sans text-slate-400">${r.target_vendor || 'None'}</td>
        <td class="py-2.5 px-3 text-slate-200">${r.total_records}</td>
        <td class="py-2.5 px-3 font-bold text-white">${r.total_score}%</td>
        <td class="py-2.5 px-3"><span class="px-2 py-0.5 rounded text-xs font-bold border ${badgeColor}">${r.grade}</span></td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    console.error('Failed to refresh dashboard stats', e);
  }
}

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

    const editor = document.getElementById('raw-payload-input');
    if (typeof payload === 'string') {
      editor.value = payload;
    } else {
      editor.value = JSON.stringify(payload, null, 2);
    }
  } catch (e) {
    alert('Failed to generate synthetic data: ' + e.message);
  }
}

async function loadSamplePreset(vendorId) {
  document.getElementById('source-vendor-select').value = vendorId;
  const editor = document.getElementById('raw-payload-input');

  let sampleFile = '';
  if (vendorId === 'alpha-hes') sampleFile = 'alpha_hes_normal.json';
  else if (vendorId === 'beta-hes') sampleFile = 'beta_hes_normal.csv';
  else if (vendorId === 'gamma-mdms') sampleFile = 'gamma_mdms_normal.json';
  else if (vendorId === 'delta-legacy') sampleFile = 'delta_legacy_normal.json';

  try {
    const res = await fetch(`/api/generate?vendor_id=${vendorId}&meter_count=2&intervals=4`);
    const data = await res.json();
    if (typeof data.payload === 'string') {
      editor.value = data.payload;
    } else {
      editor.value = JSON.stringify(data.payload, null, 2);
    }
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
    alert('Please provide a payload or upload a file first.');
    return;
  }

  const btn = document.getElementById('btn-run-workbench');
  btn.disabled = true;
  btn.innerHTML = `<span class="animate-spin inline-block mr-2">⚙</span> Validating & Normalizing...`;

  try {
    const res = await fetch('/api/workbench/execute', {
      method: 'POST',
      body: formData
    });
    const result = await res.json();
    btn.disabled = false;
    btn.innerHTML = `<span>Execute Interoperability Validation & Transformation</span>`;

    if (res.status !== 200) {
      alert('Execution failed: ' + (result.detail || 'Unknown error'));
      return;
    }

    displayExecutionResults(result);
  } catch (e) {
    btn.disabled = false;
    btn.innerHTML = `<span>Execute Interoperability Validation & Transformation</span>`;
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

  const badge = document.getElementById('res-grade-badge');
  badge.innerText = res.score.grade;
  badge.className = 'px-3 py-1 rounded-lg text-lg font-extrabold border ' +
    (res.score.total_score >= 85 ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' :
     res.score.total_score >= 70 ? 'bg-amber-500/20 text-amber-400 border-amber-500/30' :
     'bg-rose-500/20 text-rose-400 border-rose-500/30');

  // Breakdown bars
  document.getElementById('res-syntactic-score').innerText = res.score.syntactic_score + '%';
  document.getElementById('res-syntactic-bar').style.width = res.score.syntactic_score + '%';

  document.getElementById('res-semantic-score').innerText = res.score.semantic_score + '%';
  document.getElementById('res-semantic-bar').style.width = res.score.semantic_score + '%';

  document.getElementById('res-integrity-score').innerText = res.score.data_integrity_score + '%';
  document.getElementById('res-integrity-bar').style.width = res.score.data_integrity_score + '%';

  // Issues & Suggestions
  const issuesList = document.getElementById('res-issues-list');
  issuesList.innerHTML = '';
  document.getElementById('res-issues-count').innerText = res.issues.length;

  if (res.issues.length === 0) {
    issuesList.innerHTML = `<div class="p-3 bg-emerald-950/40 border border-emerald-800 rounded-lg text-emerald-300 text-xs flex items-center space-x-2">
      <i data-lucide="check-circle" class="w-4 h-4 text-emerald-400"></i>
      <span>Zero conformance violations detected! Full IEC 61968-9 and physical grid criteria satisfied.</span>
    </div>`;
  } else {
    res.issues.forEach(iss => {
      const issDiv = document.createElement('div');
      const isErr = iss.severity === 'ERROR';
      const bgBorder = isErr ? 'bg-rose-950/40 border-rose-900/60' : 'bg-amber-950/40 border-amber-900/60';
      const textCol = isErr ? 'text-rose-400' : 'text-amber-400';

      issDiv.className = `p-3 rounded-lg border ${bgBorder} text-xs space-y-1`;
      issDiv.innerHTML = `
        <div class="flex items-center justify-between">
          <span class="font-bold ${textCol} flex items-center space-x-1.5 font-mono">
            <span>[${iss.severity}] ${iss.code}</span>
          </span>
          <span class="text-slate-400 text-[11px] font-mono">${iss.field || 'Envelope'}</span>
        </div>
        <p class="text-slate-200">${iss.message}</p>
        ${iss.suggested_fix ? `<div class="text-slate-400 bg-slate-900/80 p-2 rounded border border-slate-800 text-[11px] mt-1">
          <span class="text-brand-400 font-semibold">Suggested Remediation:</span> ${iss.suggested_fix}
        </div>` : ''}
      `;
      issuesList.appendChild(issDiv);
    });
  }

  // Canonical viewer
  document.getElementById('res-canonical-code').innerText = JSON.stringify(res.canonical_payload, null, 2);

  // Target output
  document.getElementById('res-target-vendor-name').innerText = res.target_vendor || 'None';
  const targetCode = document.getElementById('res-target-code');
  if (typeof res.target_output === 'string') {
    targetCode.innerText = res.target_output;
  } else if (res.target_output) {
    targetCode.innerText = JSON.stringify(res.target_output, null, 2);
  } else {
    targetCode.innerText = '// No target transformation selected (Validation Only)';
  }

  if (window.lucide) lucide.createIcons();
  container.scrollIntoView({ behavior: 'smooth' });
}

async function runQuickDemo(source, target) {
  switchTab('workbench');
  document.getElementById('source-vendor-select').value = source;
  document.getElementById('target-vendor-select').value = target;
  await generateSyntheticIntoWorkbench();
  await runWorkbenchExecution();
}

async function loadHistoryRuns() {
  try {
    const res = await fetch('/api/test-runs');
    const runs = await res.json();
    const tbody = document.getElementById('history-runs-body');
    tbody.innerHTML = '';

    if (!runs || runs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="9" class="py-6 text-center text-slate-500 font-sans">No historical test runs recorded yet.</td></tr>`;
      return;
    }

    runs.forEach(r => {
      const tr = document.createElement('tr');
      tr.className = 'hover:bg-slate-800/40 transition text-xs';
      tr.innerHTML = `
        <td class="py-3 px-3 font-semibold text-brand-400">${r.run_id}</td>
        <td class="py-3 px-3 text-slate-300 font-sans">${new Date(r.execution_time).toLocaleString()}</td>
        <td class="py-3 px-3 text-white font-sans">${r.source_vendor}</td>
        <td class="py-3 px-3 text-slate-400 font-sans">${r.target_vendor || 'None'}</td>
        <td class="py-3 px-3 text-slate-300">${r.valid_records} / ${r.total_records}</td>
        <td class="py-3 px-3 font-bold text-white">${r.total_score}%</td>
        <td class="py-3 px-3"><span class="px-2 py-0.5 rounded font-bold ${r.total_score >= 85 ? 'text-emerald-400 bg-emerald-500/10' : 'text-amber-400 bg-amber-500/10'}">${r.grade}</span></td>
        <td class="py-3 px-3 text-slate-400">${r.duration_ms} ms</td>
        <td class="py-3 px-3">
          <button onclick="viewRunDetail('${r.run_id}')" class="text-brand-400 hover:text-brand-300 font-sans font-semibold">View Detail</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    console.error('Failed to load history', e);
  }
}

async function viewRunDetail(runId) {
  try {
    const res = await fetch(`/api/test-runs/${runId}`);
    const r = await res.json();

    document.getElementById('modal-title').innerText = `Test Run Audit: ${r.run_id}`;
    const modalContent = document.getElementById('modal-content');
    modalContent.innerHTML = `
      <div class="space-y-4">
        <div class="grid grid-cols-2 gap-4 bg-slate-950 p-4 rounded-xl border border-slate-800">
          <div><strong class="text-slate-400">Source:</strong> <span class="text-white">${r.source_vendor}</span></div>
          <div><strong class="text-slate-400">Target:</strong> <span class="text-white">${r.target_vendor || 'None'}</span></div>
          <div><strong class="text-slate-400">Execution Score:</strong> <span class="text-brand-400 font-bold">${r.score.total_score}% (${r.score.grade})</span></div>
          <div><strong class="text-slate-400">Duration:</strong> <span class="text-slate-300">${r.duration_ms} ms</span></div>
        </div>

        <div>
          <h4 class="font-bold text-slate-300 mb-2 font-sans">Diagnostic Issues Found (${r.issues.length}):</h4>
          <div class="space-y-2 max-h-48 overflow-y-auto pr-2">
            ${r.issues.map(iss => `
              <div class="p-2 rounded bg-slate-950 border border-slate-800 text-[11px]">
                <div class="text-rose-400 font-bold">[${iss.severity}] ${iss.code}</div>
                <div class="text-slate-300">${iss.message}</div>
                ${iss.suggested_fix ? `<div class="text-brand-400 mt-1">Fix: ${iss.suggested_fix}</div>` : ''}
              </div>
            `).join('') || '<div class="text-emerald-400 text-xs">No issues recorded.</div>'}
          </div>
        </div>

        <div>
          <h4 class="font-bold text-slate-300 mb-2 font-sans">Raw Payload Preview:</h4>
          <pre class="bg-slate-950 p-3 rounded text-slate-400 text-[11px] overflow-x-auto max-h-40 border border-slate-800">${r.raw_preview || '// None'}</pre>
        </div>
      </div>
    `;

    document.getElementById('detail-modal').classList.remove('hidden');
    if (window.lucide) lucide.createIcons();
  } catch (e) {
    alert('Failed to load run details: ' + e.message);
  }
}

function closeModal() {
  document.getElementById('detail-modal').classList.add('hidden');
}

function renderVendorCards() {
  const container = document.getElementById('vendor-cards-grid');
  container.innerHTML = '';

  Object.values(currentVendors).forEach(v => {
    const card = document.createElement('div');
    card.className = 'bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm space-y-4';
    card.innerHTML = `
      <div class="flex items-start justify-between">
        <div>
          <span class="px-2 py-0.5 rounded bg-brand-500/10 text-brand-400 border border-brand-500/20 text-xs font-semibold uppercase">${v.system_type}</span>
          <h3 class="text-lg font-bold text-white mt-1">${v.name}</h3>
          <p class="text-xs text-slate-400 font-mono">ID: ${v.vendor_id} | v${v.version}</p>
        </div>
        <span class="px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-xs font-mono uppercase">${v.format_type}</span>
      </div>

      <p class="text-xs text-slate-300 leading-relaxed">${v.description}</p>

      <div class="pt-2 border-t border-slate-800/80 flex items-center justify-between text-xs">
        <span class="text-slate-400">Protocol: <strong class="text-slate-200">${v.protocol}</strong></span>
        <button onclick="runQuickDemo('${v.vendor_id}', 'gamma-mdms')" class="text-brand-400 hover:text-brand-300 font-medium flex items-center space-x-1">
          <span>Test in Workbench</span>
          <i data-lucide="arrow-right" class="w-3.5 h-3.5"></i>
        </button>
      </div>
    `;
    container.appendChild(card);
  });
  if (window.lucide) lucide.createIcons();
}

function copyCode(elementId) {
  const text = document.getElementById(elementId).innerText;
  navigator.clipboard.writeText(text);
  alert('Payload copied to clipboard!');
}
