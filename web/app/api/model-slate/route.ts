import {createHash} from 'node:crypto';
import {get} from '@vercel/blob';
import {safe, slateByDate} from '../../../lib/data';

export const dynamic='force-dynamic';

// This is the same published model slate that powers the CC Analytics NBA board.
// Downstream consumers should retain its line, side, odds, and tier as published.
async function legacySnapshotId(date:string):Promise<string|null>{
 const token=process.env.BLOB_READ_WRITE_TOKEN;
 if(!token||!date)return null;
 try{
  const blob=await get(`slates/${date}/predictions.json`,{access:'public',token,useCache:false});
  if(!blob)return null;
  const bytes=await new Response(blob.stream).arrayBuffer();
  return createHash('sha256').update(Buffer.from(bytes)).digest('hex');
 }catch{return null;}
}

export async function GET(request:Request){
 const requestedDate=new URL(request.url).searchParams.get('date');
 if(requestedDate&&!/^\d{4}-\d{2}-\d{2}$/.test(requestedDate)){
  return Response.json({error:'date must be YYYY-MM-DD'},{status:400});
 }
 const board=await slateByDate(requestedDate??undefined);
 if(requestedDate&&!board.games.length){
  return Response.json({error:'slate unavailable',date:requestedDate},{status:404});
 }
 const predictions=safe(board.predictions);
 const snapshotId=typeof board.meta.snapshot_id==='string'?
  board.meta.snapshot_id:await legacySnapshotId(board.date);
 return Response.json({
  date:board.date,
  snapshot_id:snapshotId,
  run_time_et:board.meta.run_time_et??null,
  model_version:board.meta.model_version??null,
  odds_source:'BALLDONTLIE',
  games:board.games.map(g=>({
   game_id:g.game_id,date:g.date,home_team_id:g.home_team_id,
   away_team_id:g.away_team_id,home:g.home,away:g.away,
   home_pts:g.home_pts,away_pts:g.away_pts,total:g.total,
   home_margin:g.home_margin,home_win_prob:g.home_win_prob,
  })),
  players:board.players.map(p=>({
   game_id:p.game_id,player_id:p.player_id,player:p.player,
   team:p.team,team_id:p.team_id,
  })),
  predictions,
 },{headers:{'Cache-Control':'no-store'}});
}
