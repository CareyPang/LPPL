import fs from 'fs';
const R = `${process.env.LPPL_ROOT || '/home/ubuntu/repos/LPPL'}/web/app/`;
eval(fs.readFileSync(R + 'engine.js', 'utf8'));
eval(fs.readFileSync(R + 'critical.js', 'utf8'));
const CP = globalThis.CP;
const [sym, start, step] = [process.argv[2], process.argv[3], +(process.argv[4] || 5)];
const rows = fs.readFileSync(`${process.env.AUDIT_OUT || '/home/ubuntu/audit'}/${sym}.csv`, 'utf8').trim().split('\n').slice(1).map(r => { const a = r.split(','); return { date: a[0].slice(0, 10), open: +a[1], high: +a[2], low: +a[3], close: +a[4], volume: +a[5] }; });
const logp = rows.map(b => Math.log(b.close));
const T0 = rows.findIndex(b => b.date >= start);
console.log(sym, 'bars', rows.length, 'T0', T0, rows[T0].date);
for (let T = T0; T < rows.length; T += step) {
  const s = CP.topScan(logp, T);
  const c = s.clusters.filter(c => c.n >= 4 && c.conf >= 0.06);
  const fmt = (x) => x ? `[${CP.dateAt(rows, T + x.lo)}..${CP.dateAt(rows, T + x.hi)} mid=${CP.dateAt(rows, T + x.mid)} n=${x.n} conf=${x.conf.toFixed(2)}]` : '-';
  console.log(T, rows[T].date, rows[T].close.toFixed(0), 'nq', s.nq, '/', s.total, 'c1', fmt(c[0]), 'c2', fmt(c[1]));
}
