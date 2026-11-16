import type {Graded} from '../lib/data';
import {statLabel} from '../lib/labels';

const HEADERS=['Date','Player / Game','Market','Pick','Odds','EV','Actual','Result','Units'];

export default function ResultsTable({rows,total,page,pages,tier,q}:{rows:Graded[];total:number;page:number;pages:number;tier:string;q:string}){
 const href=(target:number)=>'/results?'+new URLSearchParams({...(tier?{tier}:{}),...(q?{q}:{}),page:String(target)});
 const start=(page-1)*100+1;
 return <>
  <form className="filters" method="get" action="/results">
   <input name="q" placeholder="Search player, matchup, or market" aria-label="Search results" defaultValue={q}/>
   <select name="tier" aria-label="Tier" defaultValue={tier}><option value="">All tiers</option><option value="suggested">Suggested</option><option value="lean">Lean</option><option value="pass">Pass</option></select>
   <button className="filterbutton" type="submit">Apply</button>
  </form>
  <p className="muted small">Showing {total?String(start)+'-'+String(Math.min(page*100,total)):'0'} of {total} graded lines</p>
  <div className="tablewrap"><table><thead><tr>{HEADERS.map(x=><th key={x}>{x}</th>)}</tr></thead><tbody>{rows.map((r,i)=><tr key={[r.date,r.game_id,r.player,r.stat,r.line,i].join('-')}>
   {[r.date,r.player||r.game||'Game '+(r.game_id||''),statLabel(r.stat)+' '+r.line,r.pick,(r.odds>0?'+':'')+r.odds,(r.ev*100).toFixed(1)+'%',r.actual,r.result,(r.units>0?'+':'')+r.units.toFixed(2)+'u'].map((v,j)=><td key={j} data-label={HEADERS[j]}>{v}</td>)}
  </tr>)}</tbody></table></div>
  {pages>1?<nav className="pagination" aria-label="Results pages"><span>Page {page} of {pages}</span>{page>1?<a href={href(page-1)}>Previous</a>:null}{page<pages?<a href={href(page+1)}>Next</a>:null}</nav>:null}
 </>;
}
