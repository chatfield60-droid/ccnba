"""Validate model outputs and produce only public JSON files."""
import argparse,csv,json,os,sys,datetime
from zoneinfo import ZoneInfo
from pathlib import Path
PUBLIC=['player','player_id','team','opponent','game','game_id','stat','line','line_type','pick','odds','book','model_mean','fair','p_display','ev','tier','reason','backup','direction','p_hit']
def rows(path):
    with open(path,newline='') as f:return list(csv.DictReader(f))
def numeric(x):
    try:return float(x)
    except:return None
def clean(row,fields):
    out={}
    for k in fields:
        if k in row and row[k] not in ('',None):out[k]=numeric(row[k]) if k in ('player_id','game_id','line','odds','model_mean','fair','p_display','ev','p_hit') else row[k]
    return out
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--date',required=True);ap.add_argument('--out',default='out');ap.add_argument('--publish',default='publish');a=ap.parse_args()
    src=Path(a.out);pred=rows(src/f'predictions_{a.date}.csv');box=rows(src/f'box_{a.date}.csv');games=rows(src/f'games_{a.date}.csv')
    for r in pred:
        if r.get('pick') in ('OVER','HOME','YES') and r.get('over_book'):r['book']=r['over_book']
        if r.get('pick') in ('UNDER','AWAY','NO') and r.get('under_book'):r['book']=r['under_book']
        ev=numeric(r.get('ev'));raw=numeric(r.get('ev_calibrated_raw'))
        if ev is None or ev>=.15 or raw is not None and raw>=.15:raise ValueError('A 15% EV row reached predictions')
        if r.get('tier')=='suggested' and (ev<.10 or r.get('stat') in ('game_total','team_total','spread','moneyline')):raise ValueError('Invalid suggested row')
    ids=[r.get('player_id') or r.get('player') for r in pred if r.get('tier')=='suggested']
    if len(ids)!=len(set(ids)):raise ValueError('Multiple suggestions for one player')
    teams={}
    for r in box:
        if r.get('team_id'):teams[r['team_id']]=teams.get(r['team_id'],0)+(numeric(r.get('min')) or 0)*(numeric(r.get('p_active')) or 0)
    if any(not 236<=v<=246 for v in teams.values()):raise ValueError(f'Expected minutes outside range: {teams}')
    dest=Path(a.publish)/'slates'/a.date;dest.mkdir(parents=True,exist_ok=True)
    (dest/'predictions.json').write_text(json.dumps([clean(r,PUBLIC) for r in pred],allow_nan=False))
    (dest/'players.json').write_text(json.dumps([{k:(numeric(v) if numeric(v) is not None else v) for k,v in r.items() if v!=''} for r in box],allow_nan=False))
    (dest/'games.json').write_text(json.dumps([{k:(numeric(v) if numeric(v) is not None else v) for k,v in r.items() if v!=''} for r in games],allow_nan=False))
    (dest/'meta.json').write_text(json.dumps({'date':a.date,'run_time_et':datetime.datetime.now(ZoneInfo('America/New_York')).isoformat(),'model_version':'v2.2','counts':{t:sum(r.get('tier')==t for r in pred) for t in ('suggested','lean','pass')}}))
    print(dest)
if __name__=='__main__':main()
