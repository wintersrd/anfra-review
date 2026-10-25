// ECharts SSR harness: evaluates the inline app JS from apps/running.html
// against real query results and catches per-chart setOption crashes.
// This caught the echarts 6.1.0 visualMap `d[0].coord` crash that blanked
// every chart below fitness-trend — keep it green.
//
// Usage: node chart_harness.mjs <results.json> <apps/running.html> <echarts.min.js>
//   results.json: { "<query id>": { "fields": [..], "rows": [[..], ..] } }
// Exits 1 if any chart throws; prints one THROW line per broken chart.

import { createRequire } from 'module';
import { readFileSync } from 'fs';

const [, , resultsPath, htmlPath, echartsPath] = process.argv;
if (!resultsPath || !htmlPath || !echartsPath) {
  console.error('usage: node chart_harness.mjs <results.json> <app.html> <echarts.min.js>');
  process.exit(2);
}
const require = createRequire(import.meta.url);
const realEcharts = require(echartsPath);
const results = JSON.parse(readFileSync(resultsPath, 'utf8'));
const html = readFileSync(htmlPath, 'utf8');

const m = html.match(/<script>\n([\s\S]*?)<\/script>\s*\n\s*<\/body>/);
if (!m) { console.error('inline app script not found in html'); process.exit(2); }
const appJs = m[1];

// ---- browser stubs (SSR-safe minimal DOM) ----
const chartErrors = {};
const fakeEl = (id) => ({
  id, textContent: '', dataset: {}, style: {}, childElementCount: 0,
  replaceChildren() {}, append() {}, addEventListener() {}, setAttribute() {},
  refresh() {}, classList: { toggle() {}, add() {}, remove() {} },
  // zrender measures text through a canvas 2d context even in SSR/SVG mode
  getContext: () => ({
    font: '',
    measureText: (t) => ({ width: String(t ?? '').length * 7 }),
  }),
});
const elements = {};
globalThis.document = {
  readyState: 'complete',
  documentElement: { dataset: {}, classList: { toggle() {}, add() {}, remove() {} } },
  getElementById(id) { return (elements[id] ??= fakeEl(id)); },
  createElement: (tag) => fakeEl('_' + tag),
  addEventListener() {},
  querySelectorAll: () => [],
};
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.window = globalThis;
globalThis.matchMedia = () => ({ matches: false, addEventListener() {} });
globalThis.requestAnimationFrame = () => {};  // NO-OP: calling fn() loops forever in echarts
globalThis.MutationObserver = class { observe() {} disconnect() {} };
globalThis.addEventListener = () => {};

let storedRender = null;
globalThis.Anfra = {
  user: { name: 'Harness' },
  createApp() {
    return {
      createQuery(name) {
        const r = results[name] || { fields: [], rows: [] };
        return {
          name, state: 'success', error: null, selectedRows: [],
          result: { columns: r.fields.map((f) => ({ name: f, fieldName: f })), rows: r.rows },
          select() {}, setCondition() {}, loadOptions: async () => ['Run', 'TrailRun', 'Ride'],
        };
      },
      mapCrossFilter() {},
      createFilter(name) { return { name, loadOptions: async () => ['Run', 'TrailRun', 'Ride'], setCondition() {} }; },
      mapControl() {},
      subscribe(fn) { storedRender = fn; },
      execute() {},
    };
  },
};

// echarts with per-chart SSR instances; setOption errors captured per chart id
globalThis.echarts = {
  init(el) {
    const inst = realEcharts.init(null, null, { renderer: 'svg', ssr: true, width: 920, height: 420 });
    return {
      setOption(opt) {
        try { inst.setOption(opt); }
        catch (err) {
          chartErrors[el.id] = err.message + ' || ' + String(err.stack).split('\n')[1]?.trim().slice(0, 120);
        }
      },
      on() {},
      getInstanceByDom() { return inst; },
    };
  },
};

try { eval(appJs); } catch (e) {
  console.log('SCRIPT-LEVEL THROW:', e.message, '|', String(e.stack).split('\n')[1]?.trim().slice(0, 140));
}
if (storedRender) {
  try { storedRender(); } catch (e) {
    console.log('RENDER THROW:', e.message, '|', String(e.stack).split('\n')[1]?.trim().slice(0, 140));
  }
} else {
  console.log('THROW <app> => no render subscribed via Anfra.subscribe');
}
let attempted = 0;
for (const [id, el] of Object.entries(elements)) {
  if (id.startsWith('_') || !/-/.test(id)) continue;
  attempted++;
  if (chartErrors[id]) console.log('THROW', id, '=>', chartErrors[id]);
}
console.log('charts attempted:', attempted);
process.exit(Object.keys(chartErrors).length > 0 ? 1 : 0);
