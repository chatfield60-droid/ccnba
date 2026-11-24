import {createHash} from 'node:crypto';
import {safe, slate} from '../../../lib/data';

export const dynamic='force-dynamic';

// This is the same published model slate that powers the CC Analytics NBA board.
// Downstream consumers should retain its line, side, odds, and tier as published.
export async function GET(){
 const board=await slate();
 const predictions=safe(board.predictions);
 const snapshotId=createHash('sha256')
  .update(JSON.stringify({date:board.date,predictions}))
  .digest('hex');
 return Response.json({
  date:board.date,
  snapshot_id:snapshotId,
  run_time_et:board.meta.run_time_et??null,
  model_version:board.meta.model_version??null,
  odds_source:'BALLDONTLIE',
  predictions,
 },{headers:{'Cache-Control':'no-store'}});
}
