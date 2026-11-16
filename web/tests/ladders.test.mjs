import test from 'node:test';
import assert from 'node:assert/strict';
import {findPositiveEvLadders} from '../lib/ladders.ts';

const offer=(line,ev=.05,pick='YES',tier='lean')=>({
 game_id:1,player_id:7,player:'Test Player',game:'A @ B',stat:'points',line,pick,
 odds:110,ev,tier,line_type:'alternate',
});

test('keeps a run of three adjacent positive EV alternate offers',()=>{
 const ladders=findPositiveEvLadders([offer(10),offer(8),offer(9)]);
 assert.equal(ladders.length,1);
 assert.deepEqual(ladders[0].rungs.map(r=>r.line),[8,9,10]);
});

test('a priced but nonpositive or opposite-side threshold breaks a ladder',()=>{
 assert.equal(findPositiveEvLadders([offer(8),offer(9,-.01),offer(10),offer(11)]).length,0);
 assert.equal(findPositiveEvLadders([offer(8),offer(9,.05,'UNDER'),offer(10)]).length,0);
 assert.equal(findPositiveEvLadders([offer(8),offer(9,.05,'YES','pass'),offer(10)]).length,0);
});

test('two isolated positive prices are not a ladder',()=>{
 assert.equal(findPositiveEvLadders([offer(8),offer(10)]).length,0);
});
