import {get} from '@vercel/blob';
export type Prediction={player?:string;player_id?:number;team?:string;opponent?:string;game?:string;stat:string;line?:number;pick:string;odds:number;book?:string;model_mean?:number;fair?:number;p_display?:number;ev:number;tier:string;reason?:string;backup?:string;direction?:string;p_hit?:number;game_id?:number;line_type?:string};
export type Player=Record<string,unknown>&{player_id:number;player?:string;team?:string;min?:number;p_active?:number};
export type Game=Record<string,unknown>&{game_id?:number;game?:string;home_team?:string;away_team?:string;home?:string;away?:string;home_pts?:number;away_pts?:number;total?:number;home_margin?:number;home_win_prob?:number};
export type ScoreGame={game_id:number;date:string;starts_at?:string;status:'scheduled'|'live'|'final'|'postponed';status_text?:string;home:string;away:string;home_score:number|null;away_score:number|null};
export type ScoreFeed={updated_at:string;games:ScoreGame[]};
export type Graded={date:string;player?:string;game?:string;game_id?:number;stat:string;line:number;pick:string;odds:number;book?:string;ev:number;tier:string;actual:number|null;result:string;units:number};
async function read<T>(path:string,fallback:T):Promise<T>{try{const token=process.env.BLOB_READ_WRITE_TOKEN;if(!token)return fallback;const blob=await get(path,{access:'public',token,useCache:false});if(!blob)return fallback;return await new Response(blob.stream).json() as T}catch{return fallback}}
export async function slate(){
 const latest=await read<{date:string}>('slates/latest.json',{date:''}),d=latest.date;
 if(!d)return{date:d,predictions:[] as Prediction[],players:[] as Player[],games:[] as Game[],meta:{}};
 const [predictions,players,games,meta]=await Promise.all([
  read<Prediction[]>(`slates/${d}/predictions.json`,[]),
  read<Player[]>(`slates/${d}/players.json`,[]),
  read<Game[]>(`slates/${d}/games.json`,[]),
  read<Record<string,unknown>>(`slates/${d}/meta.json`,{}),
 ]);
 const gameIds=new Set(games.map(g=>String(g.game_id)));
 const playerGames=new Set(players.map(p=>`${p.game_id}|${p.player_id}`));
 return{date:d,predictions:predictions.filter(p=>gameIds.has(String(p.game_id))&&(!p.player_id||playerGames.has(`${p.game_id}|${p.player_id}`))),players,games,meta};
}
export async function history(){return read<Graded[]>('results/history.json',[])}
export async function scoreFeed(){return read<ScoreFeed>('games/live.json',{updated_at:'',games:[]})}
export async function gameProjections(date:string){return read<Game[]>(`slates/${date}/games.json`,[])}
export const safe=(rows:Prediction[])=>rows.filter(r=>Number.isFinite(Number(r.ev))&&Number(r.ev)<.15&&r.tier!=='over_cap');
export const pct=(x?:number)=>Number.isFinite(Number(x))?`${(Number(x)*100).toFixed(1)}%`:'-';
export const odds=(x?:number)=>Number.isFinite(Number(x))?`${Number(x)>0?'+':''}${x}`:'-';
