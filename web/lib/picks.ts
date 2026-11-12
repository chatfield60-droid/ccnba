import type {Prediction} from './data';
export type TopPick=Prediction&{category:string};
export function topPickMix(rows:Prediction[],limit=3):TopPick[]{
 const qualified=rows.filter(r=>['suggested','lean'].includes(r.tier)&&r.ev>0&&r.ev<.15&&Number.isFinite(Number(r.p_display))&&r.player_id);
 const mainPlayers=new Set(qualified.filter(r=>r.line_type==='most_quoted').map(r=>`${r.game_id||r.game}|${r.player_id}`));
 const candidates=qualified.filter(r=>r.line_type==='most_quoted'||!mainPlayers.has(`${r.game_id||r.game}|${r.player_id}`));
 const byEdge=[...candidates].sort((a,b)=>b.ev-a.ev||Number(b.p_display)-Number(a.p_display));
 const byChance=[...candidates].sort((a,b)=>Number(b.p_display)-Number(a.p_display)||b.ev-a.ev);
 const chosen:TopPick[]=[],seen=new Set<string>();
 const add=(row:Prediction|undefined,category:string)=>{if(!row||chosen.length>=limit)return;const id=`${row.game_id||row.game}|${row.player_id}`;if(seen.has(id))return;seen.add(id);chosen.push({...row,category})};
 const suggested=[...qualified.filter(r=>r.tier==='suggested')].sort((a,b)=>b.ev-a.ev);
 add(suggested[0],'Model suggested play');
 if(chosen.length===0)add(byEdge[0],'Highest model edge');
 add(byChance.find(r=>r.ev>=.005&&!seen.has(`${r.game_id||r.game}|${r.player_id}`)),'Higher model chance');
 for(const row of byEdge)add(row,'Model edge');
 return chosen;
}
