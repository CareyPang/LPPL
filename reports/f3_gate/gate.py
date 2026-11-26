import sys, numpy as np, pandas as pd
from pathlib import Path
sys.path.insert(0, '/home/ubuntu/work/i182')
from research.eval import profile_synth as ps
from research.lppls import profile_fit as pf

a = pd.read_parquet('reports/profile_synth_ar1/rows.parquet')
f = pd.read_parquet('reports/profile_synth/rows.parquet')
f = f[f.asset.isna()]
cols = ['task_id', 'tc_hat', 'm_hat', 'w_hat', 'box_pass', 'b_hat']
x = a.merge(f[cols], on='task_id', suffixes=('_f3', '_f2'))
assert len(x) == 5000
b = x[x.kind == 'bubble'].copy()
out = []
for n, g in b.groupby('n'):
    e3 = (g.tc_hat_f3 - g.tc_true).abs(); e2 = (g.tc_hat_f2 - g.tc_true).abs()
    row = dict(n=n, N=len(g),
        tc_med_f2=e2.median(), tc_med_f3=e3.median(),
        tc_change_pct=100 * (e3.median() / e2.median() - 1),
        extreme_f2=100 * (e2 > 0.25 * n).mean(), extreme_f3=100 * (e3 > 0.25 * n).mean(),
        m_mae_ratio=(g.m_hat_f3 - g.m_true).abs().mean() / (g.m_hat_f2 - g.m_true).abs().mean(),
        w_mae_ratio=(g.w_hat_f3 - g.w_true).abs().mean() / (g.w_hat_f2 - g.w_true).abs().mean())
    out.append(row)
p1 = pd.DataFrame(out)
nl = x[x.kind == 'null']
p2 = nl.groupby('n').agg(null_box_f2=('box_pass_f2', 'mean'), null_box_f3=('box_pass_f3', 'mean'), N=('task_id', 'size')) * 1
p2[['null_box_f2', 'null_box_f3']] *= 100
p2b = nl.groupby(['n', 'null_class']).agg(f2=('box_pass_f2', 'sum'), f3=('box_pass_f3', 'sum'))
worse = p2b[p2b.f3 > p2b.f2]

tasks = {t['task_id']: t for t in ps._synthetic_tasks(Path('/home/ubuntu/work/global-full'))}
def acf1(v):
    v = v - v.mean(); return float(v[1:] @ v[:-1] / (v @ v))
rows = []
for r in b.itertuples():
    y = np.asarray(tasks[r.task_id]['y'], float); t = np.arange(len(y), dtype=float)
    res3, beta3, _, _ = pf._ar1_linear_fit(t, y, r.tc_hat_f3, r.m_hat_f3, r.w_hat_f3, r.rho_hat)
    res2, beta2, _, _ = pf._ar1_linear_fit(t, y, r.tc_hat_f2, r.m_hat_f2, r.w_hat_f2, 0.0)
    rows.append(dict(n=r.n, noise=r.noise, innov_f3=acf1(res3[1:]) if beta3 is not None else np.nan,
                     ols_resid_acf=acf1(res2) if beta2 is not None else np.nan))
p3 = pd.DataFrame(rows)
p3s = p3.groupby('n').agg(innov_acf_med=('innov_f3', 'median'), innov_abs_med=('innov_f3', lambda s: s.abs().median()),
                          ols_resid_acf_med=('ols_resid_acf', 'median'), nan=('innov_f3', lambda s: s.isna().sum()))
pd.set_option('display.width', 200)
print(p1.round(3).to_string(index=False)); print(p2.round(2).to_string()); print('null classes where F3 box-pass > F2:\n', worse.to_string())
print(p3s.round(3).to_string())
