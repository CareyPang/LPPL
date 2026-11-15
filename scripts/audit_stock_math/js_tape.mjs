import fs from 'fs';
const R = `${process.env.LPPL_ROOT || '/home/ubuntu/repos/LPPL'}/web/app/`;
eval(fs.readFileSync(R + 'engine.js', 'utf8'));
eval(fs.readFileSync(R + 'critical.js', 'utf8'));
const CP = globalThis.CP;
const [sym, start, end, step] = [process.argv[2], process.argv[3], process.argv[4], +(process.argv[5] || 5)];
const rows = fs.readFileSync(`${process.env.AUDIT_OUT || '/home/ubuntu/audit'}/${sym}.csv`, 'utf8').trim().split('\n').slice(1).map(r => { const a = r.split(','); return { date: a[0].slice(0, 10), close: +a[4] }; });
const logp = rows.map(b => Math.log(b.close));
const T0 = rows.findIndex(b => b.date >= start); let T1 = rows.findIndex(b => b.date > end); if (T1 < 0) T1 = rows.length;
const out = ['T,date,close,total,nq,c1_lo,c1_hi,c1_mid,c1_n,c1_conf,c2_lo,c2_hi,c2_mid,c2_n,c2_conf'];
const t0 = Date.now();
for (let T = T0; T < T1; T += step) {
  const s = CP.topScan(logp, T);
  const c = s.clusters.filter(c => c.n >= 4 && c.conf >= 0.06);
  const f = (x) => x ? [x.lo, x.hi, x.mid, x.n, x.conf.toFixed(3)].join(',') : ',,,,';
  out.push([T, rows[T].date, rows[T].close, s.total, s.nq, f(c[0]), f(c[1])].join(','));
}
fs.writeFileSync(`${process.env.AUDIT_OUT || '/home/ubuntu/audit'}/js_tape_${sym}.csv`, out.join('\n') + '\n');
console.log(sym, 'scans', out.length - 1, 'sec', ((Date.now() - t0) / 1000).toFixed(0));
