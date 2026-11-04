"""Test end-to-end bez internetu: dane openfootball + sztuczne kursy rynkowe."""
import json, glob, os, sys, shutil
import numpy as np, pandas as pd
sys.path.insert(0, '.')
os.environ['BETS_ENCRYPTION_KEY'] = 'Qn2b9yqv3XyP5rN3aBF7mQkq1oN0w0c2Gq2c5mZr8eQ='
from bot import config as C
C.BETS_KEY = os.environ['BETS_ENCRYPTION_KEY']
C.STATE = C.ROOT / 'tests' / '_state'; C.DOCS = C.ROOT / 'tests' / '_docs'
shutil.rmtree(C.STATE, ignore_errors=True)
from bot import data_sources as D, injuries as I, news as N, pipeline as PL, tracker as T, telegram as TG, message as M
from bot.model import fit_league, score_matrix, markets
from bot.site import build_site

LG = {'en.1':'EPL','es.1':'LALIGA','it.1':'SERIEA','de.1':'BUNDES','fr.1':'LIGUE1'}
rows, fut = [], []
for f in glob.glob('/home/claude/data/*.json'):
    lg = LG.get(f.split('.',1)[1].rsplit('.',1)[0])
    if not lg: continue
    d = json.load(open(f)); m = d['matches'] if isinstance(d, dict) else d
    for x in m:
        ft = (x.get('score') or {}).get('ft') if isinstance(x.get('score'), dict) else None
        r = dict(league=lg, date=pd.Timestamp(x['date']), home=x['team1'], away=x['team2'])
        if ft: rows.append({**r, 'hg':ft[0], 'ag':ft[1]})
        else: fut.append({**r, 'time': x.get('time','15:00')})
ALL = pd.DataFrame(rows)
NOW = pd.Timestamp('2026-03-14 07:00', tz='UTC')
fut = [dict(league=r.league, date=r.date, home=r.home, away=r.away, time='15:00') for r in ALL[(ALL.date>=NOW.tz_localize(None).normalize())&(ALL.date<=NOW.tz_localize(None)+pd.Timedelta(hours=60))].itertuples()]
D.fdcuk_results = lambda lg: ALL[(ALL.league==lg)&(ALL.date<NOW.tz_localize(None))].sort_values('date').reset_index(drop=True)
D.attach_xg = lambda df, lg: df
D.clubelo_ratings = lambda day=None: pd.DataFrame(columns=['Club','Country','Level','Elo'])
D.fdorg_matches = lambda *a, **k: []
D.odds_api = lambda lg: []
I.league_absences = lambda lg, teams: {teams[0]: {'players':[{'player':'Gwiazda Testowa','value':60e6,'weight':1,'reason':'Hamstring','until':None,'days_out':5}], 'share':0.12}}
N.fetch_all = lambda hours=72: [{'title':f'{fut[0]["home"]} striker ruled out','link':'http://x','summary':'','published':'2026-09-24T10:00:00+00:00','source':'Test'}]
rng = np.random.default_rng(1)
def fake_fixtures():
    out = []
    for r in fut:
        ko = pd.Timestamp(f"{r['date'].date()} {r['time'][:5]}").tz_localize('Europe/London').tz_convert('UTC')
        if not (NOW <= ko <= NOW + pd.Timedelta(hours=60)): continue
        m = fit_league(D.fdcuk_results(r['league']), r['league'])
        mk = markets(score_matrix(*m.lambdas(r['home'], r['away']), m.rho))
        p = np.array([mk['1'], mk['X'], mk['2']]) * np.exp(rng.normal(0, .08, 3)); p /= p.sum()
        po = np.clip(mk['O2.5'] + rng.normal(0, .04), .2, .8)
        out.append(dict(league=r['league'], kickoff=ko, home=r['home'], away=r['away'],
          odds_h=1/(p[0]*1.05), odds_d=1/(p[1]*1.05), odds_a=1/(p[2]*1.05), odds_o25=1/(po*1.05), odds_u25=1/((1-po)*1.05)))
    return pd.DataFrame(out)
D.fdcuk_fixtures = fake_fixtures
C.HORIZON_HOURS = 60

res, hist = PL.analyse(now=NOW.to_pydatetime())
res['day'] = '2026-03-14'; res['message'] = M.daily(res)
T.save('picks/2026-03-14.json', res); T.save('picks_latest.json', res)
T.record_day('2026-03-14', res, res['matches'])
print(res['message'])
print('\n--- komendy ---')
for cmd in ['/zagrane S1 10 2.05', '/zagrane D1 2 85', '/zagrane wlasny 5 3.4 kupon kolegi', '/zagrane XX 1 2', '/bilans']:
    print('>', cmd, '\n', TG.handle(cmd))
# rozliczenie prawdziwymi wynikami z danych
ids = [m['id'] for m in res['matches']]
real = {PL.match_id(r.league, r.date, r.home, r.away): (int(r.hg), int(r.ag)) for r in ALL.itertuples()}
results = {i: real[i] for i in ids if i in real}
print('\nwyniki dopasowane:', len(results), '/', len(ids))
ch = T.settle(results); bets = T.load_bets(); chb = T.settle_bets(bets, results); T.save_bets(bets)
print('rozliczone typy:', [(c['id'], c['status']) for c in ch]); print('moje:', [(b['nr'], b['status'], b.get('payout')) for b in chb])
print(TG.handle('/bilans')); print(TG.handle('/model'))
build_site(); print('strona:', (C.DOCS/'index.html').stat().st_size, 'B')
print('bets.enc zaszyfrowany:', (C.STATE/'bets.enc').read_bytes()[:20])
