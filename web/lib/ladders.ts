import type {Prediction} from './data';

export type Ladder={gameId:number;playerId:number;player:string;game:string;stat:string;pick:string;rungs:Prediction[]};
const priced=(r:Prediction)=>r.line_type==='alternate'&&r.player_id!=null&&r.game_id!=null&&
 Number.isFinite(r.line)&&Number.isFinite(r.odds);
const positive=(r:Prediction)=>r.ev>0&&(r.tier==='suggested'||r.tier==='lean');

/** A ladder is a run of at least three adjacent offered alternate thresholds.
 * An unavailable, nonpositive, pass, or opposite-direction threshold breaks the run. */
export function findPositiveEvLadders(rows:Prediction[]):Ladder[]{
 const markets=new Map<string,Prediction[]>();
 for(const row of rows.filter(priced)){
  const key=[row.game_id,row.player_id,row.stat].join('|');
  markets.set(key,[...(markets.get(key)||[]),row]);
 }
 const ladders:Ladder[]=[];
 for(const offers of markets.values()){
  offers.sort((a,b)=>Number(a.line)-Number(b.line));
  let run:Prediction[]=[];
  const finish=()=>{
   if(run.length>=3){
    const first=run[0];
    ladders.push({gameId:Number(first.game_id),playerId:Number(first.player_id),player:first.player||String(first.player_id),
     game:first.game||'',stat:first.stat,pick:first.pick,rungs:run});
   }
   run=[];
  };
  for(const offer of offers){
   if(positive(offer)&&(!run.length||offer.pick===run[0].pick))run.push(offer);
   else{finish();if(positive(offer))run.push(offer);}
  }
  finish();
 }
 return ladders.sort((a,b)=>Math.max(...b.rungs.map(r=>r.ev))-Math.max(...a.rungs.map(r=>r.ev)));
}
