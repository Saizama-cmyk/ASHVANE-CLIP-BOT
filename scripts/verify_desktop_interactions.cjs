const {chromium} = require('C:/Users/wilco/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');

// This uses only the isolated preview profile. Never starts a model draft or a post.
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
  const page = await context.newPage();
  const base = 'http://127.0.0.1:8788';
  const report = {errors: [], checks: [], layouts: [], draftRequests: 0};
  const check = (name, passed, detail) => report.checks.push({name, passed: !!passed, detail});
  page.on('pageerror', error => report.errors.push(error.message));
  page.on('request', request => {
    if (request.url().endsWith('/api/research/draft')) report.draftRequests++;
  });
  const login = await context.request.post(base + '/api/auth/login', {
    headers: {'X-ClipBot': '1'}, data: {password: 'preview-only-2026'}
  });
  if (!login.ok()) throw new Error('Isolated preview login failed: ' + login.status());
  const research = async () => (await context.request.get(base + '/api/research')).json();
  try {
    await page.goto(base, {waitUntil: 'networkidle'});
    await page.locator('#view-desk.active').waitFor();
    await page.locator('#deskNext').click();
    await page.locator('#view-setup.active').waitFor();
    check('Today next action opens the real setup checklist', await page.locator('#checks li').count() > 0);
    await page.locator('nav button[data-view="desk"]').click();
    await page.locator('[data-desk-field="accounts"]').click();
    await page.locator('#sec-accounts.on').waitFor();
    check('Publishing Connect opens Accounts settings', true);
    await page.locator('nav button[data-view="research"]').click();
    await page.locator('#view-research.active').waitFor();
    await page.waitForFunction(() => researchData !== null || researchProblem !== '');
    const initial = await research();
    report.initialSources = initial.sources.length;
    report.initialIdeas = initial.ideas.length;
    const checkbox = page.locator('#researchSources input[type="checkbox"]').first();
    await checkbox.check();
    const sourceId = await checkbox.inputValue();
    check('Source selection names a single source', await page.locator('#researchSelection').innerText() === '1 selected source will guide this draft.');
    await page.locator('#researchSearch').fill('no-source-matches-this-query-2026');
    check('Search has a useful no-results state', await page.locator('#researchSources').innerText() === 'No sources match that search\nTry another title or topic.');
    await page.locator('#researchSearch').fill('');
    check('Source selection survives filtering', await page.locator(`#researchSources input[value="${sourceId}"]`).isChecked());
    await page.locator('#researchSettings').click();
    await page.locator('#sec-research.on').waitFor();
    check('Research settings opens its own section', true);
    await page.locator('#sfind').fill('no-settings-match-this-query-2026');
    check('Settings search has a no-results state', await page.locator('#nohits').isVisible());
    await page.locator('#sfind').fill('');
    await page.locator('nav button[data-view="research"]').click();
    check('Selection survives navigation', await page.locator(`#researchSources input[value="${sourceId}"]`).isChecked());
    await page.locator('#researchTopic').fill('   ');
    await page.locator('#researchDraft').click();
    check('Whitespace topic focuses a clear inline error', await page.locator('#researchFormError').isVisible() && await page.locator('#researchTopic').evaluate(element => element === document.activeElement));
    await page.locator('#researchTopic').fill('');
    await checkbox.uncheck();
    if (initial.busy) throw new Error('Preview research is unexpectedly busy; cannot verify refresh without waiting for the owner.');
    if (!process.argv.includes('--no-refresh')) {
      const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/research/refresh') && response.request().method() === 'POST');
      await page.locator('#researchRefresh').click();
      const response = await responsePromise;
      check('Real feed refresh is accepted', response.ok(), await response.json());
    }
    let finished;
    for (let attempts = 0; attempts < 70; attempts++) {
      finished = await research();
      if (!finished.busy) break;
      await page.waitForTimeout(1000);
    }
    report.refresh = {status: finished.status, busy: finished.busy, sources: finished.sources.length, errors: finished.errors, updated: finished.updated};
    check('Refresh completes and preserves linked evidence', !finished.busy && finished.sources.length > 0 && finished.sources.every(source => /^https?:\/\//.test(source.url)));
    check('Refresh does not create drafts', finished.ideas.length === initial.ideas.length);
    await page.evaluate(() => loadResearch());
    await page.waitForTimeout(3500); // Let the action toast close before visual inspection.
    for (const width of [1440, 900, 390, 320]) {
      await page.setViewportSize({width, height: width < 640 ? 844 : 1000});
      for (const view of ['desk', 'research', 'settings']) {
        await page.locator(`nav button[data-view="${view}"]`).click();
        await page.locator(`#view-${view}.active`).waitFor();
        if (view === 'settings') {
          await page.locator('#snav a[data-sec="research"]').click();
          await page.locator('#sec-research.on').waitFor();
        }
        const layout = await page.evaluate(() => ({width: innerWidth, scrollWidth: document.documentElement.scrollWidth, overflow: document.documentElement.scrollWidth > innerWidth, ...(document.documentElement.scrollWidth > innerWidth ? {elements: [...document.querySelectorAll('main *')].filter(element => element.getBoundingClientRect().right > innerWidth + 1).map(element => ({tag: element.tagName, id: element.id, class: element.className, right: element.getBoundingClientRect().right, scrollWidth: element.scrollWidth})).slice(0, 15)} : {})}));
        report.layouts.push({view, ...layout});
        if (width === 1440 || width === 390) {
          await page.screenshot({path: path.resolve(`artifacts/desktop-${view}-${width}.png`), fullPage: true});
          if (view === 'settings') await page.locator('#sec-research').scrollIntoViewIfNeeded();
          await page.screenshot({path: path.resolve(`artifacts/desktop-${view}-${width}-viewport.png`)});
        }
      }
    }
    check('No draft or GPU generation was requested', report.draftRequests === 0);
  } finally {
    fs.writeFileSync('artifacts/desktop-interactions-report.json', JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
    await browser.close();
  }
  if (report.errors.length || report.checks.some(check => !check.passed) || report.layouts.some(layout => layout.overflow)) process.exitCode = 1;
})().catch(error => {console.error(error); process.exit(1);});
