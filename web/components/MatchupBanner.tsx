import type {Game, ScoreGame} from '../lib/data';
import {number,teamName,tip} from '../lib/matchup';

export default function MatchupBanner({game,score}:{game:Game;score?:ScoreGame}){
 const home=String(game.home||game.home_team||score?.home||'Home'),away=String(game.away||game.away_team||score?.away||'Away');
 const final=score?.status==='final'&&score.home_score!=null&&score.away_score!=null;
 return <div className="projection-score">
  <div className="projection-team home"><span className="team-label">HOME</span><h3>{teamName(home)}</h3><strong>{number(game.home_pts)}</strong><small>projected points</small>{final?<div className="final-score">Final {score.home_score}</div>:null}</div>
  <div className="projection-total"><span>EXPECTED TOTAL</span><strong>{number(game.total)}</strong><small>{final?'Final '+score.away_score+'–'+score.home_score:tip(score?.starts_at)}</small></div>
  <div className="projection-team away"><span className="team-label">AWAY</span><h3>{teamName(away)}</h3><strong>{number(game.away_pts)}</strong><small>projected points</small>{final?<div className="final-score">Final {score.away_score}</div>:null}</div>
 </div>;
}
