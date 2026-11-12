"""Append yesterday's settled player props to public result history."""
import argparse,csv,json,sqlite3,subprocess
from pathlib import Path
STATS={'points':'pts','rebounds':'reb','assists':'ast','threes':'fg3m','steals':'stl','blocks':'blk','points_rebounds':('pts','reb'),'points_assists':('pts','ast'),'rebounds_assists':('reb','ast'),'points_rebounds_assists':('pts','reb','ast')}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--date',required=True);a=ap.parse_args();path=Path('publish/slates')/a.date/'predictions.json'
 if not path.exists():return
 picks=json.loads(path.read_text());db=sqlite3.connect('bdl_nba.sqlite');db.row_factory=sqlite3.Row
 dest=Path('publish/results/history.json');dest.parent.mkdir(parents=True,exist_ok=True)
 history=json.loads(dest.read_text()) if dest.exists() else [];seen={(str(x.get('date')),str(x.get('player_id') or x.get('game_id')),str(x.get('stat')),str(x.get('line'))) for x in history}
 for p in picks:
  key=(a.date,str(p.get('player_id') or p.get('game_id')),str(p.get('stat')),str(p.get('line')))
  if key in seen:continue
  stat=STATS.get(p.get('stat'));actual=None;result='void';units=0.0
  if stat and p.get('player_id'):
   box=db.execute('select * from player_stats where date=? and player_id=?',(a.date,int(p['player_id']))).fetchone()
   if box and float(box['min'] or 0)>0:
    actual=sum(float(box[k] or 0) for k in (stat if isinstance(stat,tuple) else (stat,)))
    side=p.get('pick');line=float(p.get('line') or 0);result='push' if actual==line else 'win' if (actual>line)==(side=='OVER') else 'loss'
    price=float(p.get('odds') or 0);risk=abs(price)/100 if price<0 else 1
    units=(1 if price<0 else price/100) if result=='win' else -risk if result=='loss' else 0
  if not stat and p.get('game_id'):
   g=db.execute('select * from games where game_id=?',(int(p['game_id']),)).fetchone()
   if g and g['home_score'] is not None and g['visitor_score'] is not None:
    home=float(g['home_score']);away=float(g['visitor_score']);market=p.get('stat');line=float(p.get('line') or 0);side=p.get('pick')
    if market=='game_total':actual=home+away;delta=actual-line;win=(delta>0)==(side=='OVER')
    elif market=='spread':actual=home-away;delta=actual+line;win=(delta>0)==(side=='HOME')
    elif market=='moneyline':actual=home-away;delta=actual;win=(delta>0)==(side=='HOME')
    else:delta=None
    if delta is not None:
     result='push' if delta==0 else 'win' if win else 'loss'
     price=float(p.get('odds') or 0);risk=abs(price)/100 if price<0 else 1
     units=(1 if price<0 else price/100) if result=='win' else -risk if result=='loss' else 0
  history.append({**{k:p.get(k) for k in ('player','player_id','game_id','stat','line','pick','odds','book','ev','tier')},'date':a.date,'actual':actual,'result':result,'units':round(units,3)})
 dest.write_text(json.dumps(history))
if __name__=='__main__':main()
