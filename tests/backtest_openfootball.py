"""Backtest modelu na danych openfootball (bez kursów): log-loss i kalibracja 1X2 / O2.5."""
import json, glob, sys, time
import numpy as np, pandas as pd
sys.path.insert(0, '.')
from bot.model import fit_league, score_matrix, markets
D = sys.argv[1] if len(sys.argv) > 1 else '/home/claude/data'
rows = []
for f in glob.glob(f'{D}/*.json'):
    lg = f.split('.')[-2]
    if lg == 'cl': continue
    d = json.load(open(f)); m = d['matches'] if isinstance(d, dict) else d
    for x in m:
        ft = (x.get('score') or {}).get('ft') if isinstance(x.get('score'), dict) else None
        if ft: rows.append(dict(league=lg, date=pd.Timestamp(x['date']), home=x['team1'], away=x['team2'], hg=ft[0], ag=ft[1]))
df = pd.DataFrame(rows).sort_values('date')
res = []
t0 = time.time()
for lg, g in df.groupby('league'):
    test_dates = pd.date_range('2025-09-01', g.date.max(), freq='14D')
    for a, b in zip(test_dates[:-1], test_dates[1:]):
        tr = g[(g.date < a) & (g.date >= a - pd.Timedelta(days=3*365))]
        te = g[(g.date >= a) & (g.date < b)]
        if te.empty: continue
        mdl = fit_league(tr, lg, ref_date=a - pd.Timedelta(days=1))
        for r in te.itertuples():
            mk = markets(score_matrix(*mdl.lambdas(r.home, r.away), mdl.rho))
            out = '1' if r.hg > r.ag else 'X' if r.hg == r.ag else '2'
            res.append(dict(league=lg, p1=mk['1'], px=mk['X'], p2=mk['2'], out=out, po=mk['O2.5'], o=int(r.hg+r.ag>2)))
r = pd.DataFrame(res)
r['pout'] = np.where(r.out=='1', r.p1, np.where(r.out=='X', r.px, r.p2))
base = r.out.value_counts(normalize=True)
print(f'mecze testowe: {len(r)}, czas {time.time()-t0:.1f}s')
print('log-loss 1X2 model:', round(-np.log(r.pout).mean(), 4), ' bazowy (częstości):', round(-np.log(r.out.map(base)).mean(), 4))
print('Brier O2.5 model:', round(((r.po-r.o)**2).mean(), 4), ' bazowy:', round(((r.o.mean()-r.o)**2).mean(), 4))
r['bin'] = pd.cut(r.p1, [0, .2, .35, .5, .65, .8, 1])
print(r.groupby('bin', observed=True).apply(lambda x: pd.Series(dict(n=len(x), model=x.p1.mean(), real=(x.out=='1').mean()))).round(3))
