import type {Metadata} from 'next';
import PlayerGroups from '../../components/PlayerGroups';
import LadderGroups from '../../components/LadderGroups';
import MatchupBanner from '../../components/MatchupBanner';
import {safe,scoreFeed,slate} from '../../lib/data';
import {selectionLabel} from '../../lib/labels';
import {findPositiveEvLadders} from '../../lib/ladders';
import {chosenFixture,easternDate,fixtureList,oddsOpen,pct,price,teamName,tip} from '../../lib/matchup';

export const revalidate=30;
export const metadata:Metadata={title:'CC Analytics | NBA Player Props'};
const param=(v:string|string[]|undefined)=>Array.isArray(v)?v[0]||'':v||'';
const VIEWS=[['board','Player board'],['edges','Best edges'],['ladders','Ladder plays'],['parlay','Parlay']];

export default async function Props({searchParams}:{searchParams:Promise<Record<string,string|string[]|undefined>>}){
 const [params,board,feed]=await Promise.all([searchParams,slate(),scoreFeed()]);
 const fixtures=fixtureList(board.games,feed);
 const pricedIds=new Set(safe(board.predictions).filter(r=>r.player_id).map(r=>Number(r.game_id)));
 const selected=chosenFixture(fixtures,param(params.fixture),pricedIds);
 const game=selected?.game,score=selected?.score,fixture=String(game?.game_id||'');
 const view=VIEWS.some(x=>x[0]===param(params.view))?param(params.view):'board';
 const open=board.date===easternDate()&&oddsOpen(score);
 const rows=open?safe(board.predictions).filter(r=>r.player_id&&Number(r.game_id)===Number(game?.game_id)):[];
 const edges=rows.filter(r=>['suggested','lean'].includes(r.tier)&&r.ev>0)
  .sort((a,b)=>(a.tier==='suggested'?0:1)-(b.tier==='suggested'?0:1)||b.ev-a.ev).slice(0,24);
 const statusById=new Map(feed.games.map(g=>[Number(g.game_id),g]));
 const topEdges=board.date===easternDate()?safe(board.predictions).filter(r=>r.player_id&&r.tier==='suggested'&&r.ev>=.08&&oddsOpen(statusById.get(Number(r.game_id)))).sort((a,b)=>b.ev-a.ev):[];
 const longOdds=board.date===easternDate()?safe(board.predictions).filter(r=>r.player_id&&r.tier==='suggested'&&Number(r.odds)>=100&&r.ev>0&&r.ev<.15&&oddsOpen(statusById.get(Number(r.game_id)))).sort((a,b)=>b.odds-a.odds||b.ev-a.ev).slice(0,6):[];
 const seenLongshots=new Set<string>();
 const longshots=(board.date===easternDate()?safe(board.predictions):[]).filter(r=>r.player_id&&Number(r.odds)>=400&&oddsOpen(statusById.get(Number(r.game_id)))).sort((a,b)=>b.odds-a.odds).filter(r=>{const key=`${r.game_id}-${r.player_id}`;if(seenLongshots.has(key))return false;seenLongshots.add(key);return true}).slice(0,8);
 const ladders=findPositiveEvLadders(rows);
 return <>
  {!open?<p className="closed-prices">Prices are closed for this fixture. The next pregame board appears after the morning model run.</p>:null}
  <section className="site-panel"><div className="panel-heading"><div><span className="eyebrow">TODAY / {board.date}</span><h2>Top edges</h2><p>Suggested player props with at least 8% EV across today's open games.</p></div></div>{topEdges.length?<div className="edge-list props-edges">{topEdges.map((r,i)=><article className="edge-card" key={`${r.game_id}-${r.player_id}-${r.stat}-${r.line}-${i}`}><div className="edge-meta"><span className="eyebrow">MODEL SUGGESTED</span>{r.line_type==='alternate'?<b className="altbadge">ALT</b>:null}</div><h3>{r.player}</h3><p>{r.game} · {selectionLabel(r.pick,r.line,r.stat)} · {pct(r.p_display)} chance</p><div className="edge-numbers"><span><small>FAIR</small><strong>{price(r.fair)}</strong></span><span><small>BEST ODDS</small><strong>{price(r.odds)}</strong></span><span><small>EV</small><strong>{pct(r.ev)}</strong></span></div><div className="edge-footer">{r.book||'Book not listed'} · <a href={`/props?fixture=${r.game_id}&view=board`}>Open matchup →</a></div>{r.backup?<details><summary>Why this play?</summary><p>{r.backup}</p></details>:null}</article>)}</div>:<div className="empty">No open suggested plays at 8% EV or higher right now.</div>}</section>
  {longOdds.length?<section className="site-panel"><div className="panel-heading"><div><span className="eyebrow">PLUS-MONEY PICKS</span><h2>Plus-money suggested plays</h2><p>Suggested player props at +100 or longer, ranked by posted odds.</p></div></div><div className="edge-list props-edges">{longOdds.map((r,i)=><article className="edge-card" key={`${r.game_id}-${r.player_id}-${r.stat}-${r.line}-${r.pick}-${i}`}><div className="edge-meta"><span className="eyebrow">MODEL SUGGESTED</span>{r.line_type==='alternate'?<b className="altbadge">ALT</b>:null}</div><h3>{r.player}</h3><p>{r.game} · {selectionLabel(r.pick,r.line,r.stat)} · {pct(r.p_display)} chance</p><div className="edge-numbers"><span><small>BEST ODDS</small><strong>{price(r.odds)}</strong></span><span><small>FAIR</small><strong>{price(r.fair)}</strong></span><span><small>EV</small><strong>{pct(r.ev)}</strong></span></div><div className="edge-footer">{r.book||'Book not listed'} · <a href={`/props?fixture=${r.game_id}&view=edges`}>Open matchup →</a></div></article>)}</div></section>:null}
  <section className="site-panel"><div className="panel-heading"><div><span className="eyebrow">+400 AND LONGER</span><h2>Longshot markets</h2><p>Available book prices. The longshot probability model is under review, so these are unranked markets.</p></div></div>{longshots.length?<div className="edge-list props-edges">{longshots.map((r,i)=><article className="edge-card" key={`${r.game_id}-${r.player_id}-${r.stat}-${r.line}-${i}`}><div className="edge-meta"><span className="eyebrow">AVAILABLE MARKET</span>{r.line_type==='alternate'?<b className="altbadge">ALT</b>:null}</div><h3>{r.player}</h3><p>{r.game} · {selectionLabel(r.pick,r.line,r.stat)}</p><div className="edge-numbers"><span><small>BEST ODDS</small><strong>{price(r.odds)}</strong></span></div><div className="edge-footer">{r.book||'Book not listed'} · <a href={`/props?fixture=${r.game_id}&view=board`}>Open matchup →</a></div></article>)}</div>:<div className="empty">No open +400 or longer player props are available right now.</div>}</section>
  <section className="site-panel builder">
   <div className="panel-heading"><div><span className="eyebrow">PLAYER PROPS</span><h2>Choose a fixture</h2></div><a className="quiet-link" href={`/?fixture=${fixture}`}>Open matchup →</a></div>
   <form className="fixture-form" method="get" action="/props">
    <label htmlFor="props-fixture"><strong>FIXTURE FEED</strong><small>{fixtures.length} model matchups · {rows.length} priced player lines</small></label>
    <input type="hidden" name="view" value={view}/>
    <select id="props-fixture" name="fixture" defaultValue={fixture} aria-label="Upcoming fixture">{fixtures.map(({game:g,score:s})=><option key={g.game_id} value={g.game_id}>{teamName(String(g.away||s?.away||''))} at {teamName(String(g.home||s?.home||''))} · {tip(s?.starts_at)}</option>)}</select>
    <button type="submit" className="filterbutton">Open fixture</button>
   </form>
  </section>
  {game?<>
   <MatchupBanner game={game} score={score}/>
   <nav className="tool-tabs" aria-label="Player pricing tools">{VIEWS.map(([id,label])=><a key={id} className={view===id?'active':''} href={`/props?fixture=${fixture}&view=${id}`}>{label}</a>)}</nav>
   {view==='board'?<section className="site-panel tool-content"><div className="panel-heading"><div><span className="eyebrow">FAIR PRICES</span><h2>Player board</h2><p>Each player shows the best eligible play, or a marked pass when none qualify. Open a player to see every priced line in this view.</p></div><span className="muted small">{rows.length} lines</span></div><PlayerGroups rows={rows} params={params} fixture={fixture}/></section>:null}
   {view==='edges'?<section className="site-panel tool-content"><div className="panel-heading"><div><span className="eyebrow">MODEL EDGE</span><h2>Best edges</h2><p>Suggested plays lead. Positive EV leans follow with their original labels.</p></div></div>{edges.length?<div className="edge-list props-edges">{edges.map((r,i)=><article className="edge-card" key={`${r.player_id}-${r.stat}-${r.line}-${i}`}><div className="edge-meta"><span className="eyebrow">{r.tier==='suggested'?'MODEL SUGGESTED':'POSITIVE EV LEAN'}</span>{r.line_type==='alternate'?<b className="altbadge">ALT</b>:null}</div><h3>{r.player}</h3><p>{selectionLabel(r.pick,r.line,r.stat)} · {pct(r.p_display)} chance</p><div className="edge-numbers"><span><small>FAIR</small><strong>{price(r.fair)}</strong></span><span><small>BOOK</small><strong>{price(r.odds)}</strong></span><span><small>EV</small><strong>{pct(r.ev)}</strong></span></div><div className="edge-footer">{r.book||'Book not listed'}</div><details><summary>Why this edge?</summary><p>{r.backup||r.reason||'No breakdown available.'}</p></details></article>)}</div>:<div className="empty">No positive EV player lines for this matchup.</div>}</section>:null}
   {view==='ladders'?<section className="site-panel tool-content">
    <div className="panel-heading"><div><span className="eyebrow">AVAILABLE ALT MARKETS</span><h2>Ladder plays</h2><p>A ladder needs at least three consecutive offered thresholds with positive EV for the same player, stat, and direction.</p></div><span className="muted small">{ladders.length} qualifying {ladders.length===1?'ladder':'ladders'}</span></div>
    {ladders.length?<LadderGroups ladders={ladders} fixture={fixture} selected={param(params.player)}/>:<div className="empty">No three-rung positive EV ladder is available for this fixture right now.</div>}
   </section>:null}
   {view==='parlay'?<section className="site-panel tool-content"><div className="panel-heading"><div><span className="eyebrow">CORRELATION CHECK</span><h2>Parlay</h2></div></div><div className="empty">The NBA model has no validated same-game correlation prices. Single props and alternate ladders remain available in the other tabs.</div></section>:null}
  </>:<div className="empty">No fixture projection is available yet.</div>}
 </>;
}
