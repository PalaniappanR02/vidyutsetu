const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..', '..');
const databasePath = path.join(os.tmpdir(), `vidyutsetu-browser-${process.pid}.db`);
const databaseUrl = `sqlite:///${databasePath.replace(/\\/g, '/')}`;
const defaultPython = process.platform === 'win32'
  ? path.join(root, '.venv', 'Scripts', 'python.exe')
  : path.join(root, '.venv', 'bin', 'python');
const python = process.env.VIDYUTSETU_PYTHON || defaultPython;

async function waitForReadiness(server) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    if (server.exitCode !== null) throw new Error(`API process exited with ${server.exitCode}.`);
    try {
      const response = await fetch('http://127.0.0.1:8765/ready');
      if (response.ok) return;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error('API did not become ready within 30 seconds.');
}

async function main() {
  const server = spawn(
    python,
    ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8765'],
    {
      cwd: root,
      env: {
        ...process.env,
        VIDYUTSETU_ENV: 'test',
        VIDYUTSETU_AUTH_MODE: 'password',
        VIDYUTSETU_DATABASE_URL: databaseUrl,
        VIDYUTSETU_INITIAL_ADMIN_PASSWORD: 'Browser-Test-Admin-Password-1!',
        VIDYUTSETU_DEMO_ADMIN_USERNAME: 'browser-admin',
      },
      stdio: 'ignore',
    },
  );
  let browser;
  try {
    await waitForReadiness(server);
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    await page.route('https://cdn.tailwindcss.com/**', route => route.abort());
    await page.route('https://unpkg.com/**', route => route.abort());
    await page.goto('http://127.0.0.1:8765/dashboard', { waitUntil: 'domcontentloaded' });
    await page.getByRole('heading', { name: 'Sign in to VidyutSetu' }).waitFor();
    await page.locator('#login-username').fill('browser-admin');
    await page.locator('#login-password').fill('Browser-Test-Admin-Password-1!');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await page.getByText('browser-admin · admin').waitFor();

    await page.getByRole('tab', { name: 'Workbench' }).click();
    await page.locator('#view-workbench button[onclick="runSampleValidation()"]').click();
    await page.waitForFunction(() => {
      const runId = document.getElementById('res-run-id');
      return runId && runId.textContent.trim() && runId.textContent.trim() !== '—';
    }, { timeout: 30000 });

    await page.getByRole('button', { name: 'Manage users' }).click();
    await page.locator('#new-username').fill('browser-viewer');
    await page.locator('#new-password').fill('Browser-Viewer-Password-1!');
    await page.locator('#new-role').selectOption('viewer');
    await page.getByRole('button', { name: 'Create account' }).click();
    await page.getByText('Account browser-viewer created as viewer.').waitFor();
    await page.getByRole('button', { name: 'Close run detail' }).click();

    await page.getByRole('button', { name: 'Sign out' }).click();
    await page.locator('#login-username').fill('browser-viewer');
    await page.locator('#login-password').fill('Browser-Viewer-Password-1!');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await page.getByText('browser-viewer · viewer').waitFor();
    assert.equal(await page.locator('#tab-btn-workbench').isVisible(), false);
    assert.equal(
      await page.evaluate(() =>
        fetch('/api/generate?vendor_id=alpha-hes', { method: 'POST' }).then(response => response.status),
      ),
      403,
    );
    assert.equal(
      await page.evaluate(() => fetch('/api/stats').then(response => response.status)),
      200,
    );
    const overflow = await page.evaluate(() =>
      Array.from(document.querySelectorAll('body *')).flatMap(element => {
        const bounds = element.getBoundingClientRect();
        return bounds.right > window.innerWidth + 1
          ? [{ tag: element.tagName, id: element.id, className: String(element.className).slice(0, 100), right: Math.round(bounds.right) }]
          : [];
      }).slice(0, 12),
    );
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth),
      true,
      `mobile dashboard should not overflow horizontally: ${JSON.stringify(overflow)}`,
    );
    console.log('Browser workflow passed: sign-in, validation, user administration, viewer RBAC, and mobile layout.');
  } finally {
    if (browser) await browser.close();
    if (server.exitCode === null) {
      const exited = new Promise(resolve => server.once('exit', resolve));
      server.kill();
      await exited;
      await new Promise(resolve => setTimeout(resolve, 150));
    }
    for (const suffix of ['', '-wal', '-shm']) {
      const file = `${databasePath}${suffix}`;
      if (!fs.existsSync(file)) continue;
      for (let attempt = 0; attempt < 10; attempt += 1) {
        try {
          fs.unlinkSync(file);
          break;
        } catch (error) {
          if (error.code !== 'EBUSY' || attempt === 9) throw error;
          await new Promise(resolve => setTimeout(resolve, 100));
        }
      }
    }
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
