const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {CodexBridge} = require('../scripts/drivers/types/codex/codex-bridge.js');
function fixture(t, active=true) {
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'agmsg-delivery-test-'));
  t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  const b=Object.create(CodexBridge.prototype);
  Object.assign(b,{opts:{inlineInbox:true,project:'/trusted',workspaceRoots:[],turnTimeout:0},
    threadId:'thread-parent',activeTurnId:active?'turn-parent':null,turnActive:active,threadIdle:!active,
    pendingWake:true,stopping:false,deliveryPromise:null,deliveryFile:path.join(dir,'delivery.json'),
    identity:{team:'test',name:'parent'},identities:[{team:'test',name:'parent'}]});
  b.calls=[];b.acks=[];b.armed=0;
  b.peekInbox=()=>[{team:'test',name:'parent',rows:[{id:'msg-1',at:'2026-10-15T00:00:00Z',from:'child',body:'DONE'}]}];
  b.acknowledgeDelivery=(record)=>{b.acks.push(record);fs.unlinkSync(b.deliveryFile);};
  b.armWatch=async()=>{b.armed++;};
  b.client={request:async(method,params)=>{b.calls.push({method,params});return method==='turn/steer'?{turnId:params.expectedTurnId}:{turn:{id:'new-turn'}};}};
  return b;
}
test('active parent is steered once, after peeking and before acknowledgement',async t=>{
 const b=fixture(t);let release;
 b.client.request=async(method,params)=>{b.calls.push({method,params});await new Promise(r=>release=r);return {turnId:'turn-parent'};};
 const first=b.tryStartTurn();const second=b.tryStartTurn();
 await new Promise(r=>setImmediate(r));assert.equal(b.calls.length,1);assert.equal(b.acks.length,0);
 assert.equal(b.calls[0].method,'turn/steer');assert.equal(b.calls[0].params.expectedTurnId,'turn-parent');
 assert.match(b.calls[0].params.input[0].text,/child: DONE/);release();await Promise.all([first,second]);
 assert.equal(b.acks.length,1);assert.equal(b.armed,1);assert.equal(b.pendingWake,false);
});
test('idle receiver retains turn/start route',async t=>{const b=fixture(t,false);await b.tryStartTurn();assert.equal(b.calls[0].method,'turn/start');assert.equal(b.acks.length,1);});
test('confirmed rejection, including turn race, leaves unread and clears sending journal',async t=>{
 const b=fixture(t);b.client.request=async()=>{throw Object.assign(new Error('expected turn mismatch'),{rpcRejected:true});};
 await assert.rejects(b.tryStartTurn(),/mismatch/);assert.equal(b.acks.length,0);assert.equal(b.pendingWake,true);assert.equal(fs.existsSync(b.deliveryFile),false);
 b.activeTurnId=null;b.turnActive=false;b.threadIdle=true;b.client.request=async()=>({turn:{id:'new-turn'}});await b.tryStartTurn();assert.equal(b.acks.length,1);
});
test('ambiguous timeout retains unread and refuses replay even after restart',async t=>{
 const b=fixture(t);b.client.request=async()=>{throw new Error('timeout');};await assert.rejects(b.tryStartTurn(),/timeout/);
 assert.equal(b.acks.length,0);assert.equal(JSON.parse(fs.readFileSync(b.deliveryFile)).state,'sending');
 const restarted=fixture(t);restarted.deliveryFile=b.deliveryFile;assert.throws(()=>restarted.recoverDelivery(),/uncertain/);assert.equal(restarted.calls.length,0);
});
test('accepted input with failed acknowledgement is recovered without resending',async t=>{
 const b=fixture(t);const ack=b.acknowledgeDelivery;b.acknowledgeDelivery=()=>{throw new Error('ack failed');};
 await assert.rejects(b.tryStartTurn(),/ack failed/);assert.equal(JSON.parse(fs.readFileSync(b.deliveryFile)).state,'accepted');
 b.acknowledgeDelivery=ack;b.recoverDelivery();assert.equal(b.calls.length,1);assert.equal(b.acks.length,1);assert.equal(fs.existsSync(b.deliveryFile),false);
});
test('foreign turn notifications do not change target state',t=>{const b=fixture(t);b.onTurnStarted({threadId:'other',turn:{id:'other-turn'}});assert.equal(b.activeTurnId,'turn-parent');});
test('active turn discovery requests one summary without full history',async t=>{
 const b=fixture(t);b.activeTurnId=null;b.client.request=async(method,params)=>{b.calls.push({method,params});return method==='thread/turns/list'?{data:[{id:'observed-turn',status:'inProgress'}]}:{turnId:params.expectedTurnId};};
 await b.tryStartTurn();assert.deepEqual(b.calls[0].params,{threadId:'thread-parent',limit:1,sortDirection:'desc',itemsView:'summary'});assert.equal(b.calls[1].params.expectedTurnId,'observed-turn');
});
test('acknowledgement cannot cross role or thread boundaries',t=>{
 const b=fixture(t);b.eligiblePairs=()=>new Set(['test\tparent']);
 const ack=CodexBridge.prototype.acknowledgeDelivery.bind(b);
 assert.throws(()=>ack({threadId:'foreign',batches:[]}),/different thread/);
 assert.throws(()=>ack({threadId:b.threadId,batches:[{team:'test',name:'other',ids:['msg-1']}]}),/no longer eligible/);
});
