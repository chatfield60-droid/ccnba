import {createHash} from 'node:crypto';
import {get} from '@vercel/blob';
import {safe, slate} from '../../../lib/data';

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

export async function GET(){
 const board=await slate();
 const predictions=safe(board.predictions);
 const snapshotId=typeof board.meta.snapshot_id==='string'?
  board.meta.snapshot_id:await legacySnapshotId(board.date);
 return Response.json({
  date:board.date,
  snapshot_id:snapshotId,
  run_time_et:board.meta.run_time_et??null,
  model_version:board.meta.model_version??null,
  odds_source:'BALLDONTLIE',
  predictions,
 },{headers:{'Cache-Control':'no-store'}});
}
