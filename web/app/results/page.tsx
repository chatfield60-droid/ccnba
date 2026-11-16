import {history} from '../../lib/data';
import ResultsTable from '../../components/ResultsTable';
import {statLabel} from '../../lib/labels';
import type {Graded} from '../../lib/data';

export const dynamic='force-dynamic';
const param=(v:string|string[]|undefined)=>Array.isArray(v)?v[0]||'':v||'';
const rank=(tier:string)=>tier==='suggested'?0:tier==='lean'?1:tier==='pass'?2:3;
function metrics(a:Graded[]){
 const settled=a.filter(r=>r.result==='win'||r.result==='loss');
 const units=settled.reduce((n,r)=>n+Number(r.units),0);
 const risk=settled.reduce((n,r)=>n+(r.odds<0?Math.abs(r.odds)/100:1),0);
 return{record:settled.filter(r=>r.result==='win').length+'-'+settled.filter(r=>r.result==='loss').length,units,roi:risk?units/risk*100:0};
}

export default async function Results({searchParams}:{searchParams:Promise<Record<string,string|string[]|undefined>>}){
 const rows=await history(),params=await searchParams;
 const suggested=rows.filter(r=>r.tier==='suggested'&&r.result!=='void');
 const leans=rows.filter(r=>r.tier==='lean'&&r.result!=='void');
 const a=metrics(suggested),b=metrics(leans);
 const groups=new Map<string,Graded[]>();
 for(const r of suggested){
  const band=r.ev<.08?'6 to 8%':r.ev<.10?'8 to 10%':r.ev<.12?'10 to 12%':r.ev<.14?'12 to 14%':'14 to 15%';
  for(const key of ['Stat: '+statLabel(r.stat),'Side: '+r.pick,'EV: '+band])groups.set(key,[...(groups.get(key)||[]),r]);
 }
 const running:{date:string;units:number}[]=[];let total=0;
 for(const r of [...suggested].sort((x,y)=>x.date.localeCompare(y.date))){total+=Number(r.units);running.push({date:r.date,units:total});}
 const extent=Math.max(1,...running.map(x=>Math.abs(x.units)));
 const tier=['suggested','lean','pass'].includes(param(params.tier))?param(params.tier):'';
 const q=param(params.q).trim().slice(0,100),needle=q.toLowerCase();
 const filtered=rows.filter(r=>(!tier||r.tier===tier)&&(!needle||(String(r.player||'')+' '+String(r.game||'')+' '+r.stat+' '+statLabel(r.stat)).toLowerCase().includes(needle)));
 filtered.sort((x,y)=>y.date.localeCompare(x.date)||rank(x.tier)-rank(y.tier)||y.ev-x.ev);
 const pages=Math.max(1,Math.ceil(filtered.length/100));
 const requested=Number(param(params.page)),page=Number.isInteger(requested)?Math.min(Math.max(requested,1),pages):1;
 return <>
  <section className="hero"><div className="eyebrow">Full history</div><h1>Results</h1><div className="summary"><span>Suggested: {a.record} · {a.units.toFixed(2)}u · {a.roi.toFixed(1)}% ROI</span><span>Leans: {b.record} · {b.units.toFixed(2)}u · {b.roi.toFixed(1)}% ROI</span><a href="/results.csv">Download CSV</a></div></section>
  <section className="section"><h2>Suggested breakdown</h2>{groups.size?<div className="statgrid">{[...groups].map(([name,g])=>{const m=metrics(g);return <div className="statbox" key={name}><span className="eyebrow">{name}</span><b>{m.record}</b><small>{m.units.toFixed(2)}u · {m.roi.toFixed(1)}% ROI</small></div>;})}</div>:<div className="empty">No settled suggested plays.</div>}</section>
  <section className="section"><h2>Cumulative units</h2>{running.length?<div role="img" aria-label="Cumulative units by graded pick" style={{display:'flex',alignItems:'end',height:180,gap:2,borderBottom:'2px solid #151515',background:'#fff',padding:'12px 10px 0'}}>{running.map((x,i)=><div key={i} title={x.date+': '+x.units.toFixed(2)+'u'} style={{flex:1,minWidth:2,height:String(Math.max(2,Math.abs(x.units)/extent*100))+'%',background:x.units>=0?'#c82127':'#151515'}}/>)}</div>:<div className="empty">No settled picks yet.</div>}</section>
  <section className="section"><h2>Every graded pick</h2>{rows.length?<ResultsTable rows={filtered.slice((page-1)*100,page*100)} total={filtered.length} page={page} pages={pages} tier={tier} q={q}/>:<div className="empty">No graded picks yet.</div>}</section>
 </>;
}
