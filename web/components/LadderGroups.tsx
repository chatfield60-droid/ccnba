import type {Prediction} from '../lib/data';
import type {Ladder} from '../lib/ladders';
import {selectionLabel,statLabel} from '../lib/labels';
import {pct,price} from '../lib/matchup';

type Group={id:string;name:string;game:string;ladders:Ladder[];best:Prediction;bestLadder:Ladder};
const rank=(r:Prediction)=>r.tier==='suggested'?0:1;
const bestRung=(rows:Prediction[])=>[...rows].sort((a,b)=>rank(a)-rank(b)||b.ev-a.ev)[0];
const rungSteps=(ladder:Ladder)=>ladder.rungs.map(r=>r.pick==='YES'?`${r.line}+`:
 r.pick==='NO'?`no ${r.line}+`:`${r.pick.toLowerCase()} ${r.line}`).join(' · ');

export default function LadderGroups({ladders,fixture,selected}:{ladders:Ladder[];fixture:string;selected:string}){
 const byPlayer=new Map<string,Ladder[]>();
 for(const ladder of ladders){const id=String(ladder.playerId);byPlayer.set(id,[...(byPlayer.get(id)||[]),ladder]);}
 const groups:Group[]=[...byPlayer].map(([id,items])=>{
  const sorted=[...items].sort((a,b)=>bestRung(b.rungs).ev-bestRung(a.rungs).ev);
  const all=sorted.flatMap(l=>l.rungs),best=bestRung(all);
  return{id,name:sorted[0].player,game:sorted[0].game,ladders:sorted,best,bestLadder:sorted.find(l=>l.rungs.includes(best))||sorted[0]};
 }).sort((a,b)=>rank(a.best)-rank(b.best)||b.best.ev-a.best.ev);
 const href=(id:string)=>`/props?${new URLSearchParams({fixture,view:'ladders',...(selected===id?{}:{player:id})})}#player-${id}`;
 return <>
  <p className="muted small player-count">{groups.length} {groups.length===1?'player':'players'} · {ladders.length} qualifying {ladders.length===1?'ladder':'ladders'} · {ladders.reduce((n,l)=>n+l.rungs.length,0)} positive EV rungs</p>
  <div className="player-groups">{groups.map(group=><article className={`player-group ${selected===group.id?'open':''}`} id={`player-${group.id}`} key={group.id}>
   <a className="player-summary" href={href(group.id)} aria-expanded={selected===group.id}>
    <span className="player-name"><strong>{group.name}</strong><small>{group.game}</small></span>
    <span className="player-best"><small>BEST RUNG · {group.bestLadder.rungs.length}-RUNG LADDER</small><strong>{selectionLabel(group.best.pick,group.best.line,group.best.stat)}</strong><small>{rungSteps(group.bestLadder)} {statLabel(group.bestLadder.stat)}</small></span>
    <span className="player-best-price"><strong>{price(group.best.odds)}</strong><small>{group.best.book||'Book not listed'}</small></span>
    <span className="player-best-ev"><strong>{pct(group.best.ev)} EV</strong><small>{pct(group.best.p_display)} chance</small></span>
    <span className="player-best-tier"><span className={`pill ${group.best.tier}`}>{group.best.tier}</span><small>{group.ladders.length} {group.ladders.length===1?'ladder':'ladders'} {selected===group.id?'↑':'↓'}</small></span>
   </a>
   {selected===group.id?<div className="player-lines"><div className="player-lines-head"><strong>Qualifying ladders for {group.name}</strong><a href={`/player/${group.id}`}>Full player projection →</a></div>
    {group.ladders.map((ladder,i)=><section className="ladder-run" key={`${ladder.stat}-${ladder.pick}-${i}`}><div className="ladder-run-head"><strong>{statLabel(ladder.stat)} · {ladder.pick==='YES'?'Over milestone':ladder.pick==='NO'?'Under milestone':ladder.pick}</strong><span>{ladder.rungs.length} consecutive positive EV rungs</span></div>
     <div className="tablewrap"><table><thead><tr>{['Rung','Book','Odds','Chance','Projection','Fair','EV','Tier'].map(x=><th key={x}>{x}</th>)}</tr></thead><tbody>{ladder.rungs.map((r,j)=><tr key={`${r.stat}-${r.line}-${j}`}><td data-label="Rung"><strong>{selectionLabel(r.pick,r.line,r.stat)}</strong></td><td data-label="Book">{r.book||'-'}</td><td data-label="Odds">{price(r.odds)}</td><td data-label="Chance">{pct(r.p_display)}</td><td data-label="Projection">{r.model_mean??'-'}</td><td data-label="Fair">{price(r.fair)}</td><td data-label="EV" className="ev">{pct(r.ev)}</td><td data-label="Tier"><span className={`pill ${r.tier}`}>{r.tier}</span></td></tr>)}</tbody></table></div>
    </section>)}
   </div>:null}
  </article>)}</div>
 </>;
}
