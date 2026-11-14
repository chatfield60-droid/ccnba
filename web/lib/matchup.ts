import type {Game, Prediction, ScoreFeed, ScoreGame} from './data';

const NAMES:Record<string,string>={ATL:'Atlanta Hawks',BOS:'Boston Celtics',BKN:'Brooklyn Nets',CHA:'Charlotte Hornets',CHI:'Chicago Bulls',CLE:'Cleveland Cavaliers',DAL:'Dallas Mavericks',DEN:'Denver Nuggets',DET:'Detroit Pistons',GSW:'Golden State Warriors',HOU:'Houston Rockets',IND:'Indiana Pacers',LAC:'LA Clippers',LAL:'Los Angeles Lakers',MEM:'Memphis Grizzlies',MIA:'Miami Heat',MIL:'Milwaukee Bucks',MIN:'Minnesota Timberwolves',NOP:'New Orleans Pelicans',NYK:'New York Knicks',OKC:'Oklahoma City Thunder',ORL:'Orlando Magic',PHI:'Philadelphia 76ers',PHX:'Phoenix Suns',POR:'Portland Trail Blazers',SAC:'Sacramento Kings',SAS:'San Antonio Spurs',TOR:'Toronto Raptors',UTA:'Utah Jazz',WAS:'Washington Wizards'};
export const teamName=(abbr?:string)=>NAMES[abbr||'']||abbr||'Team';
export const price=(odds?:number)=>Number.isFinite(Number(odds))?`${Number(odds)>0?'+':''}${odds}`:'—';
export const pct=(value?:number)=>Number.isFinite(Number(value))?`${(Number(value)*100).toFixed(1)}%`:'—';
export const number=(value?:number,digits=1)=>Number.isFinite(Number(value))?Number(value).toFixed(digits):'—';
export function easternDate(value=new Date()){const parts=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(value);const part=(kind:string)=>parts.find(p=>p.type===kind)?.value||'';return `${part('year')}-${part('month')}-${part('day')}`;}
export function oddsOpen(score?:ScoreGame){return !score||score.status==='scheduled'&&(!score.starts_at||Date.parse(score.starts_at)>Date.now());}
export function tip(value?:string){if(!value||!Number.isFinite(Date.parse(value)))return 'Time TBD';return new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}).format(new Date(value));}
export function fixtureList(games:Game[],feed:ScoreFeed):{game:Game;score?:ScoreGame}[]{
 return games.filter(g=>g.game_id!=null).map(game=>({game,score:feed.games.find(s=>Number(s.game_id)===Number(game.game_id))}));
}
export function chosenFixture(fixtures:ReturnType<typeof fixtureList>,id?:string){return fixtures.find(x=>String(x.game.game_id)===id)||fixtures[0];}
export function gameMarkets(rows:Prediction[],id?:number){return rows.filter(r=>Number(r.game_id)===Number(id)&&['game_total','team_total','spread','moneyline'].includes(r.stat));}
