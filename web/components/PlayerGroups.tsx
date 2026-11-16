import type {Prediction} from '../lib/data';
import {selectionLabel,statLabel} from '../lib/labels';
import {pct,price} from '../lib/matchup';

type Params=Record<string,string|string[]|undefined>;
type Group={id:string;name:string;rows:Prediction[];best?:Prediction};
const value=(v:string|string[]|undefined)=>Array.isArray(v)?v[0]||'':v||'';
const rank=(r:Prediction)=>r.tier==='suggested'?0:r.tier==='lean'?1:2;
const eligible=(r:Prediction)=>r.ev>0&&(r.tier==='suggested'||r.tier==='lean');

export default function PlayerGroups({rows,params={},fixture}:{rows:Prediction[];params?:Params;fixture:string}){
 const q=value(params.q).trim().toLowerCase(),stat=value(params.stat),lineType=value(params.lineType),tier=value(params.tier);
 const stats=[...new Set(rows.map(r=>r.stat))].sort();
 const filtered=rows.filter(r=>(!q||`${r.player||''} ${r.team||''} ${r.opponent||''}`.toLowerCase().includes(q))&&
  (!stat||r.stat===stat)&&(!lineType||r.line_type===lineType)&&(!tier||r.tier===tier));
 const map=new Map<string,Group>();
 for(const r of filtered){
  const id=String(r.player_id||r.player||'');
  if(!map.has(id))map.set(id,{id,name:r.player||`Player ${id}`,rows:[]});
  map.get(id)!.rows.push(r);
 }
 const groups=[...map.values()];
 for(const group of groups){
  group.rows.sort((a,b)=>rank(a)-rank(b)||b.ev-a.ev);
  group.best=group.rows.find(eligible)||group.rows[0];
 }
 groups.sort((a,b)=>rank(a.best!)-rank(b.best!)||b.best!.ev-a.best!.ev||a.name.localeCompare(b.name));
 const pageSize=30;
 const pages=Math.max(1,Math.ceil(groups.length/pageSize));
 const requested=Number(value(params.page)),page=Number.isInteger(requested)?Math.min(Math.max(requested,1),pages):1;
 const shown=groups.slice((page-1)*pageSize,page*pageSize);
 const selected=value(params.player);
 const href=(target:number)=>{
  const query=new URLSearchParams({fixture,view:'board',page:String(target)});
  for(const [key,v] of Object.entries({q,stat,lineType,tier}))if(v)query.set(key,v);
  return `/props?${query}`;
 };
 const playerHref=(id:string)=>{
  const query=new URLSearchParams({fixture,view:'board',page:String(page)});
  for(const [key,v] of Object.entries({q,stat,lineType,tier}))if(v)query.set(key,v);
  if(selected!==id)query.set('player',id);
  return `/props?${query}#player-${id}`;
 };
 return <>
  <form method="get" action="/props" className="filters player-filters">
   <input type="hidden" name="fixture" value={fixture}/><input type="hidden" name="view" value="board"/>
   <input name="q" aria-label="Search player or team" placeholder="Search player or team" defaultValue={value(params.q)}/>
   <select name="stat" aria-label="Stat" defaultValue={stat}><option value="">All stats</option>{stats.map(x=><option key={x} value={x}>{statLabel(x)}</option>)}</select>
   <select name="lineType" aria-label="Line type" defaultValue={lineType}><option value="">All lines</option><option value="most_quoted">Most quoted</option><option value="alternate">Alternates</option></select>
   <select name="tier" aria-label="Tier" defaultValue={tier}><option value="">All tiers</option>{['suggested','lean','pass'].map(x=><option value={x} key={x}>{x}</option>)}</select>
   <button type="submit" className="filterbutton">Apply</button>
  </form>
  <p className="muted small player-count">{groups.length} players · {filtered.length} priced lines · top line shown for each player</p>
  {shown.length?<div className="player-groups">{shown.map(group=><article className={`player-group ${selected===group.id?'open':''}`} id={`player-${group.id}`} key={group.id}>
   <a className="player-summary" href={playerHref(group.id)} aria-expanded={selected===group.id}><span className="player-name"><strong>{group.name}</strong><small>{group.rows[0]?.game||`${group.rows[0]?.team||''} vs ${group.rows[0]?.opponent||''}`}</small></span>
    <span className="player-best"><small>{group.best&&eligible(group.best)?'BEST ELIGIBLE PLAY':'TOP PRICED LINE · PASS'}</small><strong>{group.best?selectionLabel(group.best.pick,group.best.line,group.best.stat):'No priced line'}</strong>{group.best?.line_type==='alternate'?<b className="altbadge">ALT</b>:null}</span>
    <span className="player-best-price">{group.best?<><strong>{price(group.best.odds)}</strong><small>{group.best.book||'Book not listed'}</small></>:null}</span>
    <span className="player-best-ev">{group.best?<><strong>{pct(group.best.ev)} EV</strong><small>{pct(group.best.p_display)} chance</small></>:null}</span>
    <span className="player-best-tier">{group.best?<span className={`pill ${group.best.tier}`}>{group.best.tier}</span>:null}<small>{group.rows.length} {group.rows.length===1?'line':'lines'} {selected===group.id?'↑':'↓'}</small></span>
   </a>
   {selected===group.id?<div className="player-lines"><div className="player-lines-head"><strong>All priced lines for {group.name}</strong>{group.rows[0]?.player_id?<a href={`/player/${group.rows[0].player_id}`}>Full player projection →</a>:null}</div>
    <div className="tablewrap"><table><thead><tr>{['Market','Pick','Book','Odds','Chance','Projection','Fair','EV','Tier'].map(x=><th key={x}>{x}</th>)}</tr></thead><tbody>{group.rows.map((r,i)=><tr key={`${r.stat}-${r.line}-${r.pick}-${i}`} title={r.tier==='pass'?r.reason:''}><td data-label="Market">{statLabel(r.stat)} {r.line} {r.line_type==='alternate'?<small className="altbadge">ALT</small>:null}</td><td data-label="Pick">{r.pick}</td><td data-label="Book">{r.book||'-'}</td><td data-label="Odds">{price(r.odds)}</td><td data-label="Chance">{pct(r.p_display)}</td><td data-label="Projection">{r.model_mean??'-'}</td><td data-label="Fair">{price(r.fair)}</td><td data-label="EV" className="ev">{pct(r.ev)}</td><td data-label="Tier"><span className={`pill ${r.tier}`}>{r.tier}</span></td></tr>)}</tbody></table></div>
   </div>:null}
  </article>)}</div>:<div className="empty">No player lines match these filters.</div>}
  {pages>1?<nav className="pager player-pager" aria-label="Player pages">{page>1?<a href={href(page-1)}>Previous</a>:null}<span>Page {page} of {pages}</span>{page<pages?<a href={href(page+1)}>Next</a>:null}</nav>:null}
 </>;
}
