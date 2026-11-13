import BoardTable from '../../components/BoardTable';
import {gameProjections, safe, scoreFeed, slate} from '../../lib/data';
import type {Game, Player, ScoreGame} from '../../lib/data';

export const revalidate = 60;

const fmt = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(1) : '-';
function tipTime(value?: string) {
  if (!value || !Number.isFinite(Date.parse(value))) return 'Time TBD';
  return new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',hour:'numeric',minute:'2-digit',timeZoneName:'short'}).format(new Date(value));
}

function GameCard({game, projection, players=[]}:{game:ScoreGame;projection?:Game;players?:Player[]}) {
  const scored = ['final','live'].includes(game.status) && game.away_score != null && game.home_score != null;
  const projected = projection?.away_pts != null && projection?.home_pts != null;
  const roster = players.filter(p=>Number(p.game_id)===Number(game.game_id) && Number(p.min)>0);
  return <article className="matchup" id={`game-${game.game_id}`}>
    <div className="matchup-head"><div><span className="eyebrow">{game.date} · {game.status==='scheduled'?tipTime(game.starts_at):game.status}</span><h3>{game.away} at {game.home}</h3></div><span className={`game-status ${game.status}`}>{game.status}</span></div>
    <div className="scoregrid">{(['away','home'] as const).map(side=><div className="scoreline" key={side}><span>{game[side]}</span><strong>{scored?game[`${side}_score`]:projected?fmt(projection?.[`${side}_pts`]):'-'}</strong><small>{scored?'Score':projected?'Projection':'Awaiting model'}</small></div>)}</div>
    {projected?<div className="matchup-metrics"><span>Model score {fmt(projection?.away_pts)}–{fmt(projection?.home_pts)}</span><span>Total {fmt(projection?.total)}</span><span>Home win {projection?.home_win_prob==null?'-':`${fmt(Number(projection.home_win_prob)*100)}%`}</span></div>:null}
    {roster.length?<details className="box-detail"><summary>Projected player box score</summary><div className="boxteams">{(['away','home'] as const).map(side=><div key={side}><h4>{game[side]}</h4><div className="tablewrap"><table><thead><tr>{['Player','MIN','PTS','REB','AST','3PM'].map(x=><th key={x}>{x}</th>)}</tr></thead><tbody>{roster.filter(p=>p.side===side).sort((a,b)=>Number(b.min)-Number(a.min)).slice(0,8).map(p=><tr key={p.player_id}><td data-label="Player"><a href={`/player/${p.player_id}`}>{String(p.name||p.player||'Player')}</a></td>{(['min','pts','reb','ast','fg3m'] as const).map(k=><td data-label={k.toUpperCase()} key={k}>{fmt(p[k])}</td>)}</tr>)}</tbody></table></div></div>)}</div></details>:null}
  </article>;
}

export default async function Games({searchParams}:{searchParams:Promise<Record<string,string|string[]|undefined>>}) {
  const [params, board, feed] = await Promise.all([searchParams,slate(),scoreFeed()]);
  const stamp = feed.updated_at ? new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(feed.updated_at)) : [];
  const part = (kind:string) => stamp.find(p=>p.type===kind)?.value||'';
  const today = stamp.length ? `${part('year')}-${part('month')}-${part('day')}` : board.date;
  const current = feed.games.filter(g=>g.date===today);
  const fallback: ScoreGame[] = (board.date===today?board.games:[]).filter(g=>!current.some(x=>Number(x.game_id)===Number(g.game_id))).map(g=>({game_id:Number(g.game_id),date:today,status:'scheduled',home:String(g.home||g.home_team||'Home'),away:String(g.away||g.away_team||'Away'),home_score:null,away_score:null}));
  const todaysGames = [...current,...fallback].sort((a,b)=>String(a.starts_at||'').localeCompare(String(b.starts_at||'')));
  const upcoming = feed.games.filter(g=>g.date>today && g.status!=='final').slice(0,16);
  const finals = feed.games.filter(g=>g.date<today && g.status==='final').sort((a,b)=>b.date.localeCompare(a.date)||Number(b.game_id)-Number(a.game_id)).slice(0,24);
  const prior = await Promise.all([...new Set(finals.map(g=>g.date))].map(gameProjections));
  const projections = new Map<number,Game>([...board.games,...prior.flat()].filter(g=>g.game_id!=null).map(g=>[Number(g.game_id),g]));
  const rows = safe(board.predictions).filter(x=>['game_total','team_total','spread','moneyline'].includes(x.stat));
  return <>
    <section className="hero"><div className="eyebrow">NBA MATCHUPS / {today}</div><h1>Price the game.<br/><span>Follow the score.</span></h1><p className="herocopy">Projected score and player box before tip. Live and final scores update throughout game day.</p>{feed.updated_at?<p className="small muted">Scores updated {new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',dateStyle:'medium',timeStyle:'short'}).format(new Date(feed.updated_at))} ET</p>:null}</section>
    <section className="section"><h2>Today&apos;s games</h2>{todaysGames.length?<div className="matchup-grid">{todaysGames.map(g=><GameCard key={g.game_id} game={g} projection={projections.get(g.game_id)} players={board.players}/>)}</div>:<div className="empty">No games on today&apos;s slate.</div>}</section>
    {upcoming.length?<section className="section"><h2>Up next</h2><div className="matchup-grid">{upcoming.map(g=><GameCard key={g.game_id} game={g}/>)}</div></section>:null}
    <section className="section"><h2>Recent finals</h2>{finals.length?<div className="matchup-grid">{finals.map(g=><GameCard key={g.game_id} game={g} projection={projections.get(g.game_id)}/>)}</div>:<div className="empty">Final scores will appear after games finish.</div>}</section>
    <section className="section"><h2>Team markets</h2><p className="muted small">Prices are shown for comparison. Team markets are not suggested plays.</p>{rows.length?<BoardTable rows={rows} params={params} basePath="/games"/>:<div className="empty">No team lines.</div>}</section>
  </>;
}
