const STAT_NAMES:Record<string,string>={
 points:'Points',rebounds:'Rebounds',assists:'Assists',threes:'3-Pointers Made',three_points:'3-Pointers Made',
 steals:'Steals',blocks:'Blocks',turnovers:'Turnovers',blocks_steals:'Blocks + Steals',steals_blocks:'Steals + Blocks',
 points_rebounds:'Points + Rebounds',points_assists:'Points + Assists',rebounds_assists:'Rebounds + Assists',
 points_rebounds_assists:'Points + Rebounds + Assists',double_double:'Double-Double',triple_double:'Triple-Double',
 points_1q:'1st Quarter Points',rebounds_1q:'1st Quarter Rebounds',assists_1q:'1st Quarter Assists',
 points_first3min:'First 3 Minutes Points',rebounds_first3min:'First 3 Minutes Rebounds',assists_first3min:'First 3 Minutes Assists',
 game_total:'Game Total',team_total:'Team Total',spread:'Spread',moneyline:'Moneyline',
 min:'Minutes',pts:'Points',reb:'Rebounds',ast:'Assists',fg3m:'3-Pointers Made',fgm:'Field Goals Made',
 fga:'Field Goal Attempts',fg3a:'3-Point Attempts',ftm:'Free Throws Made',fta:'Free Throw Attempts',
 oreb:'Offensive Rebounds',dreb:'Defensive Rebounds',stl:'Steals',blk:'Blocks',tov:'Turnovers',pf:'Personal Fouls',
 pr:'Points + Rebounds',pa:'Points + Assists',ra:'Rebounds + Assists',pra:'Points + Rebounds + Assists',stocks:'Steals + Blocks',
 p_active:'Chance to Play',home_win_prob:'Home Win Chance',home_margin:'Home Margin',proj_pace:'Projected Pace',total_sd:'Total Uncertainty',
 };

export function statLabel(stat:string){
 return STAT_NAMES[stat]||stat.replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
}

export function selectionLabel(pick:string,line:number|undefined,stat:string){
 const market=statLabel(stat);
 if(pick==='YES')return `${line}+ ${market}`;
 if(pick==='NO')return `No ${line}+ ${market}`;
 return `${pick} ${line} ${market}`;
}
