// Run against a local portal serving representative benchmark summaries:
// PLAYWRIGHT_MODULE=/path/to/playwright PORTAL_URL=http://127.0.0.1:9186 node review-check.cjs
// Playwright is a local verification tool, not a portal runtime dependency.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const base = process.env.PORTAL_URL || 'http://127.0.0.1:9186';
const output = process.env.EVIDENCE_DIR || '/tmp/OME-1841-review';
(async () => {
  await fs.mkdir(output, {recursive: true});
  const browser = await chromium.launch({channel: 'chrome', headless: true});
  const results = [];
  const failures = [];
  const check = (actual, expected, label) => {
    try { assert.equal(actual, expected, label); } catch (e) { failures.push(e.message); }
  };
  for (const width of [1440, 375]) for (const theme of ['light', 'dark']) {
    const context = await browser.newContext({viewport: {width, height: 1000}, colorScheme: theme});
    await context.route('**/*', r => new URL(r.request().url()).origin === base ? r.continue() : r.abort());
    const page = await context.newPage();
    await page.goto(base);
    await page.locator('.card').first().waitFor();
    await page.evaluate(() => document.fonts.ready);
    await page.keyboard.press('Tab');
    check(await page.locator('.skip-link').evaluate(e => e === document.activeElement), true, 'first tab reaches skip link');
    await page.keyboard.press('Enter');
    check(await page.locator('main').evaluate(e => e === document.activeElement), true, 'skip link still focuses main');
    await page.locator('.fine-print').click();
    await page.keyboard.press('ArrowDown');
    const data = await page.evaluate(() => {
      const main = document.querySelector('main'), footer = document.querySelector('footer');
      const box = footer.getBoundingClientRect(), fine = document.querySelector('.fine-print').getBoundingClientRect();
      const firstCard = document.querySelector('.card').getBoundingClientRect();
      return {
        active: document.activeElement.tagName, outline: getComputedStyle(main).outlineStyle,
        footer: {x: box.x, width: box.width, height: box.height, gap: box.top - fine.bottom},
        cardX: firstCard.x,
        siblingLandmarks: main.parentElement === footer.parentElement && !footer.closest('main,section,article,aside,nav'),
        overflow: document.documentElement.scrollWidth > innerWidth,
      };
    });
    check(data.active, 'MAIN', 'scroll scenario focuses main');
    check(data.outline, 'none', 'scrolling plain text must not outline the entire main');
    check(data.footer.width, width === 1440 ? 880 : 343, 'footer line matches original content width');
    check(Math.round(data.footer.height), 36, 'footer retains original height');
    check(data.footer.gap, 64, 'footer retains original gap');
    check(data.footer.x, data.cardX, 'footer and cards share left alignment');
    check(data.siblingLandmarks, true, 'main/footer remain sibling page landmarks');
    check(data.overflow, false, 'no horizontal overflow');
    await page.screenshot({path: `${output}/${width}-${theme}-footer.png`});
    for (const selector of ['.rail-link', '#theme-toggle', '#benchmark-search', '.card']) {
      const el = page.locator(selector).first(); await el.focus();
      const ring = await el.evaluate(e => ({style: getComputedStyle(e).outlineStyle, width: getComputedStyle(e).outlineWidth}));
      check(ring.style, 'solid', selector + ' keeps visible keyboard ring');
      check(ring.width, '2px', selector + ' keeps visible keyboard ring width');
    }
    results.push({width, theme, ...data});
    // Generic links on other pages retain the browser focus treatment; their
    // more-specific table/chart rings are outside this homepage change.
    for (const name of ['benchmark', 'spec', 'about', 'data']) {
      await page.goto(`${base}/${name}.html`); await page.keyboard.press('Tab');
      await page.locator('.rail-link').first().focus();
      check(await page.locator('.rail-link').first().evaluate(e => getComputedStyle(e).outlineStyle), 'auto', name + ' generic links keep their existing focus treatment');
    }
    await context.close();
  }
  await browser.close();
  await fs.writeFile(`${output}/measurements.json`, JSON.stringify({results, failures}, null, 2));
  assert.deepEqual(failures, []);
  console.log('PASS: main scroll/skip focus, footer geometry and homepage-only rings at both sizes/themes');
})().catch(e => { console.error(e); process.exit(1); });
