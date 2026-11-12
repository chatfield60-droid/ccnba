"""Fetch the current BALLDONTLIE NBA odds into one consensus row per exact line."""
import argparse,csv,os,sqlite3,statistics,time,urllib.parse,urllib.request,json,sys
BASE='https://api.balldontlie.io'
def request(path,params):
    url=BASE+path+'?'+urllib.parse.urlencode(params,doseq=True)
    for attempt in range(5):
        try:
            req=urllib.request.Request(url,headers={'Authorization':os.environ['BDL_API_KEY']})
            with urllib.request.urlopen(req,timeout=35) as response:return json.load(response)
        except Exception as e:
            if attempt==4:raise
            time.sleep(2**attempt)
def implied(x):return -x/(-x+100) if x<0 else 100/(x+100)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--date',required=True);a=ap.parse_args()
    db=sqlite3.connect(os.environ.get('BDL_DB','bdl_nba.sqlite'));db.row_factory=sqlite3.Row
    games=[r['game_id'] for r in db.execute('select game_id from games where date=? and postponed=0',(a.date,))]
    active={r['player_id']:dict(r) for r in db.execute('select * from active_players')}
    names={pid:f"{r['first_name']} {r['last_name']}" for pid,r in active.items()}
    teams={r['team_id']:r['abbr'] for r in db.execute('select * from teams')}
    grouped={};team=[]
    for gid in games:
        game=db.execute('select * from games where game_id=?',(gid,)).fetchone()
        label=f"{teams.get(game['visitor_team_id'],'AWAY')} @ {teams.get(game['home_team_id'],'HOME')}"
        for p in request('/nba/v2/odds/player_props',{'game_id':gid}).get('data',[]):
            m=p.get('market') or {};pid=p.get('player_id');line=p.get('line_value');stat=p.get('prop_type')
            if not pid or not stat or line is None:continue
            key=(gid,pid,stat,line);grouped.setdefault(key,[]).append((p.get('vendor',''),m,label))
        cursor=None
        while True:
            params={'game_ids[]':gid,'per_page':100}
            if cursor:params['cursor']=cursor
            body=request('/nba/v2/odds',params)
            for p in body.get('data',[]):
                book=p.get('vendor','')
                for stat,line,over,under in [('game_total',p.get('total_value'),p.get('total_over_odds'),p.get('total_under_odds')),('spread',p.get('spread_home_value'),p.get('spread_home_odds'),p.get('spread_away_odds')),('moneyline',0,p.get('moneyline_home_odds'),p.get('moneyline_away_odds'))]:
                    if line is None or over is None or under is None:continue
                    team.append(dict(game_id=gid,game=label,stat=stat,line=line,over_odds=over,under_odds=under,home_odds=over,away_odds=under,over_book=book,under_book=book,book=book))
            cursor=body.get('meta',{}).get('next_cursor')
            if not cursor:break
    team_groups={}
    for offer in team:team_groups.setdefault((offer['game_id'],offer['stat'],str(offer['line'])),[]).append(offer)
    team=[]
    for offers in team_groups.values():
        over=max(offers,key=lambda x:float(x['over_odds']));under=max(offers,key=lambda x:float(x['under_odds']))
        row=dict(over);row.update(over_odds=over['over_odds'],under_odds=under['under_odds'],home_odds=over['over_odds'],away_odds=under['under_odds'],over_book=over['book'],under_book=under['book'])
        team.append(row)
    rows=[]
    for (gid,pid,stat,line),offers in grouped.items():
        pairs=[(book,m) for book,m,_ in offers if m.get('type')=='over_under' and m.get('over_odds') is not None and m.get('under_odds') is not None]
        if pairs:
            po=statistics.median(implied(m['over_odds'])/(implied(m['over_odds'])+implied(m['under_odds'])) for _,m in pairs)
            ob,om=max(pairs,key=lambda x:x[1]['over_odds']);ub,um=max(pairs,key=lambda x:x[1]['under_odds'])
            rows.append(dict(game_id=gid,game=offers[0][2],player_id=pid,player=names.get(pid,str(pid)),team=teams.get(active.get(pid,{}).get('team_id'),''),stat=stat,line=line,over_odds=om['over_odds'],under_odds=um['under_odds'],over_book=ob,under_book=ub,p_book_over=po,quote_count=len(pairs)))
        else:
            milestones=[(book,m,label) for book,m,label in offers if m.get('type')=='milestone' and m.get('odds') is not None]
            if milestones:
                book,m,label=max(milestones,key=lambda x:x[1]['odds'])
                rows.append(dict(game_id=gid,game=label,player_id=pid,player=names.get(pid,str(pid)),stat=stat,line=line,yes_odds=m['odds'],book=book))
    max_quotes={}
    for r in rows:
        if r.get('quote_count'):
            k=(r['game_id'],r['player_id'],r['stat']);max_quotes[k]=max(max_quotes.get(k,0),r['quote_count'])
    for r in rows:
        k=(r['game_id'],r['player_id'],r['stat'])
        r['line_type']='most_quoted' if r.get('quote_count') and r['quote_count']==max_quotes.get(k) else 'alternate'
    fields=['game_id','game','player_id','player','team','stat','line','over_odds','under_odds','yes_odds','home_odds','away_odds','over_book','under_book','book','p_book_over','line_type','quote_count']
    w=csv.DictWriter(sys.stdout,fieldnames=fields);w.writeheader();w.writerows(rows+team)
if __name__=='__main__':main()
