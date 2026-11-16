import type {Prediction} from './data';
export type TopPick=Prediction&{category:string};
export function topPickMix(rows:Prediction[],limit=6):TopPick[]{
 const qualified=rows.filter(r=>['suggested','lean'].includes(r.tier)&&r.ev>0&&r.ev<.15&&Number.isFinite(Number(r.p_display))&&r.player_id);
 const byEdge=[...qualified].sort((a,b)=>b.ev-a.ev||Number(b.p_display)-Number(a.p_display));
 const byChance=[...qualified].sort((a,b)=>Number(b.p_display)-Number(a.p_display)||b.ev-a.ev);
 const chosen:TopPick[]=[],seen=new Set<string>();
 const add=(row:Prediction|undefined,category:string)=>{if(!row||chosen.length>=limit)return;const id=`${row.game_id||row.game}|${row.player_id}`;if(seen.has(id))return;seen.add(id);chosen.push({...row,category})};
 const suggested=[...qualified.filter(r=>r.tier==='suggested')].sort((a,b)=>b.ev-a.ev);
 for(const row of suggested)add(row,'Model suggested play');
 if(chosen.length===0)add(byEdge[0],'Highest model edge');
 let chanceCount=0;
 for(const row of byChance.filter(r=>r.tier==='lean'&&r.ev>=.005&&Number(r.p_display)>=.6)){
  if(chanceCount>=2)break;
  const before=chosen.length;add(row,'Higher model chance');
  if(chosen.length>before)chanceCount++;
 }
 for(const row of byEdge)add(row,'Model edge');
 return chosen;
}

export function nearSuggestionFloor(rows:Prediction[],limit=6):Prediction[]{
 const suggested=new Set(rows.filter(r=>r.tier==='suggested').map(r=>String(r.player_id)));
 const candidates=rows.filter(r=>r.tier==='lean'&&r.player_id&&r.ev>=.07&&r.ev<.08&&
  !suggested.has(String(r.player_id))&&(r.reason||'').startsWith('not suggested: below suggested floors')&&
  !(r.reason||'').includes(';')).sort((a,b)=>b.ev-a.ev);
 const seen=new Set<string>();
 return candidates.filter(r=>{const id=String(r.player_id);if(seen.has(id))return false;seen.add(id);return true}).slice(0,limit);
}
