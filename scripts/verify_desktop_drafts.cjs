const {chromium} = require('C:/Users/wilco/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}, permissions: ['clipboard-read', 'clipboard-write']});
  const page = await context.newPage();
  const base = 'http://127.0.0.1:8788', targetId = 'd8bc13015732476a9050985fa3196ee5';
  const report = {errors: [], mutations: [], checks: [], layouts: [], copies: []};
  const check = (name, passed, detail) => report.checks.push({name, passed: !!passed, ...(detail === undefined ? {} : {detail})});
  page.on('pageerror', error => report.errors.push(error.message));
  page.on('request', request => {
    if (request.method() !== 'GET' && !request.url().endsWith('/api/auth/login')) report.mutations.push({method: request.method(), url: request.url()});
  });
  const login = await context.request.post(base + '/api/auth/login', {headers: {'X-ClipBot': '1'}, data: {password: 'preview-only-2026'}});
  if (!login.ok()) throw new Error('Isolated preview login failed');
  const actual = await (await context.request.get(base + '/api/research')).json();
  const target = actual.ideas.find(idea => idea.id === targetId);
  if (!target) throw new Error('Real saved draft was not loaded into preview');
  report.ideas = actual.ideas.map(idea => ({id: idea.id, status: idea.status, sentenceChecks: (idea.judgement?.sentence_checks || []).length}));
  try {
    await page.goto(base + '/#research', {waitUntil: 'networkidle'});
    await page.locator('nav button[data-view="research"]').click();
    await page.waitForFunction(() => researchData !== null);
    for (const idea of actual.ideas.filter(idea => idea.status === 'needs_review')) {
      const card = page.locator(`.research-idea:has(details[data-research-detail="${idea.id}"])`);
      await card.locator('summary').click();
      const body = await card.innerText();
      check(`${idea.id}: needs-review status visible`, body.includes('Needs review'));
      check(`${idea.id}: overview leads with evidence warnings`, await card.locator('.idea-judgement').innerText().then(text => text.includes(`${idea.judgement.unsupported_claims.length} evidence`)));
      check(`${idea.id}: script preserved exactly`, await card.locator('.idea-block').first().locator('pre').textContent() === idea.script);
      check(`${idea.id}: all five platform panels and copy buttons`, await card.locator('[data-copy-kind]').count() === 6 && ['youtube','tiktok','instagram','facebook','discord'].every(platform => Object.hasOwn(idea.posts, platform)));
      check(`${idea.id}: every warning visible`, idea.judgement.unsupported_claims.every(warning => body.includes(warning)));
      const savedChecks = idea.judgement.sentence_checks || [];
      check(`${idea.id}: every sentence check rendered`, await card.locator('[data-sentence-check]').count() === savedChecks.length);
      for (const saved of savedChecks) {
        const row = card.locator(`[data-sentence-check="${saved.id}"]`);
        const quotes = row.locator('blockquote');
        check(`${idea.id}: ${saved.id} quoted evidence`, saved.evidence ? await quotes.textContent() === saved.evidence : await quotes.count() === 0);
        const warning = saved.supported !== true || idea.judgement.unsupported_claims.some(item => item.startsWith(saved.id + ':'));
        if (warning) check(`${idea.id}: ${saved.id} warning overrides judge support`, await row.locator('.badge').innerText() === 'Needs review');
        for (const sourceId of saved.source_ids || []) {
          const source = idea.sources.find(item => item.id === sourceId);
          if (!source) continue;
          const link = row.locator('a');
          check(`${idea.id}: ${saved.id} evidence source link`, await link.getAttribute('href') === new URL(source.url).href && await link.getAttribute('target') === '_blank' && await link.getAttribute('rel') === 'noopener noreferrer');
        }
      }
      if (idea.id !== targetId) await card.locator('summary').click();
    }
    const card = page.locator(`.research-idea:has(details[data-research-detail="${targetId}"])`);
    const platformText = (platform, copy) => {
      if (platform === 'youtube') return [copy.title,copy.description,copy.tags.map(tag => '#' + tag).join(' ')].filter(Boolean).join('\n\n');
      if (['tiktok','instagram'].includes(platform)) return [copy.caption,copy.hashtags.map(tag => '#' + tag.replace(/^#/, '')).join(' ')].filter(Boolean).join('\n\n');
      if (platform === 'facebook') return [copy.title,copy.description].filter(Boolean).join('\n\n');
      return copy.message;
    };
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({width, height: width < 640 ? 844 : 1000});
      for (const kind of ['script','youtube','tiktok','instagram','facebook','discord']) {
        const button = card.locator(`[data-copy-kind="${kind}"]`);
        const expected = kind === 'script' ? target.script : platformText(kind, target.posts[kind]);
        check(`${width}px ${kind}: rendered saved copy`, await button.locator('xpath=../..').locator('pre').textContent() === expected);
        await button.click();
        const copied = await page.evaluate(() => navigator.clipboard.readText());
        report.copies.push({width, kind, exact: copied.replace(/\r\n?/g, '\n') === expected, characters: copied.length, lineEndings: copied.includes('\r\n') ? 'Windows CRLF' : 'LF'});
      }
      const layout = await page.evaluate(() => ({width: innerWidth, scrollWidth: document.documentElement.scrollWidth, overflow: document.documentElement.scrollWidth > innerWidth}));
      report.layouts.push(layout);
      await page.waitForFunction(() => !document.getElementById('toast').classList.contains('show'));
      await card.locator('.idea-top').evaluate(element => element.scrollIntoView({block: 'start', behavior: 'instant'}));
      await page.screenshot({path: path.resolve(`artifacts/desktop-real-draft-${width}.png`)});
      await card.locator('[data-sentence-check="script:0"]').screenshot({path: path.resolve(`artifacts/desktop-real-evidence-${width}.png`)});
      await card.locator('[data-sentence-check="youtube:description:3"]').screenshot({path: path.resolve(`artifacts/desktop-real-warning-${width}.png`)});
    }
    const firstSource = card.locator('[data-sentence-check="script:0"] a');
    await firstSource.focus();
    await page.keyboard.press('Tab');
    await page.keyboard.press('Shift+Tab');
    check('Evidence links remain in native keyboard navigation', await firstSource.evaluate(element => element === document.activeElement));
    const escaping = await page.evaluate(id => {
      const idea = researchData.ideas.find(item => item.id === id), source = idea.sources[0];
      const text = '<img src=x onerror="alert(1)"> <script>alert(1)</script>';
      const detached = document.createElement('div');
      detached.innerHTML = ideaDetail({...idea, script: text, sources: [{...source, title: text, url: 'javascript:alert(1)'}], judgement: {...idea.judgement, sentence_checks: [{id:'script:0',kind:'fact',supported:true,source_ids:[source.id],evidence:text,reason:text}]}});
      return detached.querySelectorAll('img,script').length === 0 && detached.querySelector('blockquote').textContent === text && ![...detached.querySelectorAll('a')].some(link => link.href.startsWith('javascript:'));
    }, targetId);
    check('Untrusted evidence text is escaped and unsafe source URLs are blocked', escaping);
    check('No GPU draft, refresh, deletion, or publishing request', report.mutations.length === 0);
  } finally {
    fs.writeFileSync('artifacts/desktop-real-drafts-report.json', JSON.stringify(report, null, 2));
    console.log(JSON.stringify({errors: report.errors, mutations: report.mutations, checks: report.checks.length, failed: report.checks.filter(check => !check.passed), ideas: report.ideas, layouts: report.layouts, copies: report.copies}));
    await browser.close();
  }
  if (report.errors.length || report.mutations.length || report.checks.some(check => !check.passed) || report.layouts.some(layout => layout.overflow) || report.copies.some(copy => !copy.exact)) process.exitCode = 1;
})().catch(error => {console.error(error); process.exit(1);});
