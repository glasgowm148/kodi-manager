// Real synthetic API plus browser failure injection; no TV/network mutations.
const { test, expect, startDemo, waitForPage } = require('./fixtures');

test('refusals retain operation references in the private support bundle', async ({ page, app }) => {
  const demo = await startDemo(['--read-only']);
  try {
    await app.open('health');
    await page.goto(demo.url + '/#/health');
    await waitForPage(page);
    const refusal = await page.evaluate(async () => {
      try { await api('/api/stack/backup', {password:'synthetic-secret', title:'Personal viewing'}); }
      catch (error) { return {code:error.code, outcome:error.outcome, operation:error.operation}; }
    });
    expect(refusal.code).toBe('write_disabled');
    expect(refusal.outcome).toBe('refused');
    expect(refusal.operation.correlation_id).toMatch(/^[0-9a-f]{32}$/);
    await page.locator('#supportDiagnostics').click();
    const bundle = page.locator('#supportBundle');
    await expect(bundle).toContainText('write_disabled');
    await expect(bundle).toContainText(refusal.operation.operation_id);
    await expect(bundle).toContainText('Enable writes in the active profile');
    await expect(bundle).not.toContainText('synthetic-secret');
    await expect(bundle).not.toContainText('Personal viewing');
    await expect(bundle).not.toContainText('demo-token-0000');
    expect(app.errors).toEqual([]);
  } finally { await demo.stop(); }
});

test('lost and invalid write replies report unknown outcome without retrying', async ({ page, app }) => {
  await app.open('health');
  let calls = 0;
  await page.route('**/api/stack/backup', async route => {
    calls++;
    if (calls === 1) await route.abort('failed');
    else await route.fulfill({status:200, contentType:'text/plain', body:'invalid JSON'});
  });
  for (const code of ['outcome_unknown', 'invalid_response']) {
    const error = await page.evaluate(async () => {
      try { await api('/api/stack/backup', {}); }
      catch (error) { reportError(error); return {code:error.code, outcome:error.outcome}; }
    });
    expect(error).toEqual({code, outcome:'unknown'});
    await expect(page.locator('.toast-error').last()).toContainText('Inspect current state');
  }
  expect(calls).toBe(2);
});

test('older services retain health checks without offering unsupported diagnostics', async ({ page, app }) => {
  await page.route('**/api/health', async route => {
    const response = await route.fetch();
    const body = await response.json();
    delete body.data.diagnostics;
    await route.fulfill({response, json:body});
  });
  await app.open('health');
  await expect(page.locator('#content h2')).toHaveText('Health checks');
  await expect(page.locator('#supportDiagnostics')).toHaveCount(0);
  expect(app.errors).toEqual([]);
});
