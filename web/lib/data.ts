import {list} from '@vercel/blob';
export type Prediction={player?:string;player_id?:number;team?:string;opponent?:string;game?:string;stat:string;line?:number;pick:string;odds:number;book?:string;model_mean?:number;fair?:number;p_display?:number;ev:number;tier:string;reason?:string;backup?:string;direction?:string;p_hit?:number;game_id?:number;line_type?:string};
export type Player=Record<string,unknown>&{player_id:number;player?:string;team?:string;min?:number;p_active?:number};
export type Game=Record<string,unknown>&{game_id?:number;game?:string;home_team?:string;away_team?:string;home?:string;away?:string;home_pts?:number;away_pts?:number;total?:number;home_margin?:number;home_win_prob?:number};
export type Graded={date:string;player:string;stat:string;line:number;pick:string;odds:number;book?:string;ev:number;tier:string;actual:number;result:string;units:number};
async function read<T>(path:string,fallback:T,revalidate=300):Promise<T>{try{const token=process.env.BLOB_READ_WRITE_TOKEN;const found=await list({prefix:path,limit:100,...(token?{token}:{})});const item=found.blobs.find(b=>b.pathname===path);if(!item)return fallback;const res=await fetch(item.url,{next:{revalidate}});if(!res.ok)return fallback;return await res.json() as T}catch{return fallback}}
export async function slate(){const latest=await read<{date:string}>('slates/latest.json',{date:''});const d=latest.date;return{date:d,predictions:d?await read<Prediction[]>(`slates/${d}/predictions.json`,[]):[],players:d?await read<Player[]>(`slates/${d}/players.json`,[]):[],games:d?await read<Game[]>(`slates/${d}/games.json`,[]):[],meta:d?await read<Record<string,unknown>>(`slates/${d}/meta.json`,{}):{}}}
export async function history(){return read<Graded[]>('results/history.json',[],60)}
export const safe=(rows:Prediction[])=>rows.filter(r=>Number.isFinite(Number(r.ev))&&Number(r.ev)<.15&&r.tier!=='over_cap');
export const pct=(x?:number)=>Number.isFinite(Number(x))?`${(Number(x)*100).toFixed(1)}%`:'-';
export const odds=(x?:number)=>Number.isFinite(Number(x))?`${Number(x)>0?'+':''}${x}`:'-';
