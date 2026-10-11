const {chromium} = require('C:/Users/wilco/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');

function schemaFieldPaths(schema) {
  const resolve = raw => {
    let node = raw;
    while (node && node.$ref) node = schema.$defs[node.$ref.split('/').pop()];
    if (node?.allOf?.length === 1) return resolve(node.allOf[0]);
    return node || {};
  };
  const paths = [];
  const visit = (raw, prefix) => {
    const node = resolve(raw);
    for (const [key, child] of Object.entries(node.properties || {})) {
      const prop = resolve(child), field = [...prefix, key];
      if (prop.type === 'object' && prop.properties) visit(prop, field);
      else paths.push(field.join('.'));
    }
  };
  for (const [key, section] of Object.entries(schema.properties)) visit(section, [key]);
  return paths.sort();
}

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const base = 'http://127.0.0.1:8788';
  const auth = await (await context.request.get(base + '/api/auth/status')).json();
  if (auth.setup) await context.request.post(base + '/api/auth/setup', {
    headers: {'X-ClipBot': '1'}, data: {name: 'Preview', password: 'preview-only-2026'}
  });
  else await context.request.post(base + '/api/auth/login', {
    headers: {'X-ClipBot': '1'}, data: {password: 'preview-only-2026'}
  });
  await page.goto(base, {waitUntil: 'networkidle'});
  await page.locator('#view-desk.active').waitFor();
  await page.screenshot({path: path.resolve('artifacts/desktop-today.png'), fullPage: true});
  const today = await page.locator('#view-desk').innerText();
  await page.locator('nav button[data-view="research"]').click();
  await page.locator('#view-research.active').waitFor();
  await page.waitForFunction(() => researchData !== null || researchProblem !== '');
  let researchRefresh = {started: false, status: 'already busy'};
  if (!process.argv.includes('--no-refresh') && await page.locator('#researchRefresh').isEnabled()) {
    const refreshResponse = page.waitForResponse(response => response.url().endsWith('/api/research/refresh') && response.request().method() === 'POST');
    await page.locator('#researchRefresh').click();
    const response = await refreshResponse;
    researchRefresh = {started: true, status: response.status(), body: await response.json()};
    await page.waitForFunction(() => researchData && !researchData.busy && !researchSending, null, {timeout: 45000}).catch(() => {});
    await page.evaluate(() => loadResearch());
  }
  await page.screenshot({path: path.resolve('artifacts/desktop-research.png'), fullPage: true});
  const research = await page.locator('#view-research').innerText();
  const sourceCount = await page.locator('.research-source').count();
  await page.locator('nav button[data-view="settings"]').click();
  await page.locator('[data-field]').first().waitFor({state: 'attached'});
  const schema = await (await context.request.get(base + '/api/settings/schema')).json();
  const actualFields = await page.locator('[data-field]').evaluateAll(elements => elements.map(element => element.dataset.field).sort());
  const expectedFields = schemaFieldPaths(schema.schema || schema);
  const fields = actualFields.length;
  const missingFields = expectedFields.filter(field => !actualFields.includes(field));
  const extraFields = actualFields.filter(field => !expectedFields.includes(field));
  const duplicateFields = actualFields.filter((field, index) => actualFields.indexOf(field) !== index);
  await page.setViewportSize({width: 390, height: 844});
  await page.locator('nav button[data-view="desk"]').click();
  await page.screenshot({path: path.resolve('artifacts/desktop-narrow.png'), fullPage: true});
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  const overflowElements = await page.evaluate(() => [...document.querySelectorAll('body *')].filter(element => {
    const rect = element.getBoundingClientRect();
    return rect.width && rect.right > innerWidth + 1 && getComputedStyle(element).display !== 'none';
  }).map(element => ({tag: element.tagName, id: element.id, class: element.className, width: Math.round(element.getBoundingClientRect().width), right: Math.round(element.getBoundingClientRect().right), scrollWidth: element.scrollWidth})).slice(0,30));
  await page.locator('nav button[data-view="research"]').click();
  const researchOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  await page.screenshot({path: path.resolve('artifacts/desktop-research-narrow.png'), fullPage: true});
  const result = {errors, fields, expectedFields: expectedFields.length, missingFields, extraFields, duplicateFields, overflow, researchOverflow, overflowElements, researchRefresh, sourceCount, today, research};
  fs.writeFileSync('artifacts/browser-report.json', JSON.stringify(result, null, 2));
  console.log(JSON.stringify({errors, fields, expectedFields: expectedFields.length, missingFields, extraFields, duplicateFields, overflow, researchOverflow, overflowElements, researchRefresh, sourceCount, todayLoaded: !!today, researchLoaded: !!research}));
  await browser.close();
  if (errors.length || overflow || researchOverflow || missingFields.length || extraFields.length || duplicateFields.length) process.exitCode = 1;
})().catch(error => {console.error(error); process.exit(1);});
