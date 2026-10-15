const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const net = require('node:net');
const path = require('node:path');
const { Duplex, PassThrough } = require('node:stream');
const { DesktopIpcClient, turnState } = require('../scripts/drivers/types/codex/codex-desktop-ipc');
const { CodexBridge } = require('../scripts/drivers/types/codex/codex-bridge');

function conversation(active = false) {
  return { id: 'bound-thread', resumeState: 'resumed', threadRuntimeStatus: { type: active ? 'active' : 'idle' },
    turns: [{ turnId: 'existing-turn', status: active ? 'inProgress' : 'completed' }] };
}

async function fixture(t, { active = false, reply = 'success', state = conversation(active), version = 11 } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'aipc-'));
  const socketPath = path.join(dir, 's');
  const requests = [], discoveries = [], connections = new Set();
  function frame(value) {
    const data = Buffer.from(JSON.stringify(value));
    const header = Buffer.alloc(4); header.writeUInt32LE(data.length);
    return Buffer.concat([header, data]);
  }
  const handleSocket = socket => {
    connections.add(socket); socket.on('close', () => connections.delete(socket));
    let buffer = Buffer.alloc(0);
    function send(value, split = false) {
      const bytes = frame(value);
      if (split) { socket.write(bytes.subarray(0, 2)); setImmediate(() => socket.write(bytes.subarray(2))); }
      else socket.write(bytes);
    }
    socket.on('data', data => {
      buffer = Buffer.concat([buffer, data]);
      while (buffer.length >= 4 && buffer.length >= 4 + buffer.readUInt32LE(0)) {
        const size = buffer.readUInt32LE(0);
        const message = JSON.parse(buffer.subarray(4, size + 4)); buffer = buffer.subarray(size + 4);
        if (message.type === 'client-discovery-response') { discoveries.push(message); continue; }
        if (message.type === 'broadcast') {
          if (message.params.following) {
            // Distractors establish that conversation/source/method are checked,
            // and a patch is not accepted as the required full snapshot.
            send({ type: 'broadcast', method: 'thread-stream-state-changed', version: 11,
              sourceClientId: 'owner', params: { conversationId: 'other-thread', hostId: 'local',
                change: { type: 'snapshot', conversationState: conversation(!active) } } });
            send({ type: 'broadcast', method: 'thread-stream-state-changed', version: 11,
              sourceClientId: 'owner', params: { conversationId: 'bound-thread', hostId: 'local',
                change: { type: 'patches', patches: [] } } });
            send({ type: 'broadcast', method: 'thread-stream-state-changed', version,
              sourceClientId: 'owner', params: { conversationId: 'bound-thread', hostId: 'local',
                change: { type: 'snapshot', conversationState: state } } }, true);
          }
          continue;
        }
        requests.push(message);
        const response = { type: 'response', requestId: message.requestId, resultType: 'success' };
        if (message.method === 'initialize') {
          send({ type: 'client-discovery-request', requestId: 'discovery-question' });
          send({ ...response, requestId: 'unrelated', result: { clientId: 'wrong-client' } });
          send({ ...response, result: { clientId: 'assigned-client' } }, true);
        } else if (message.method === 'thread-owner-discovery') {
          send({ ...response, handledByClientId: 'owner', result: {} });
        } else if (message.method.startsWith('thread-follower-')) {
          if (reply === 'timeout') continue;
          if (reply === 'closed') { socket.destroy(); continue; }
          if (reply === 'error' || reply === 'wrong-owner-error') {
            send({ ...response, resultType: 'error', error: 'Cannot steer conversation bound-thread because its active turn already ended',
              handledByClientId: reply === 'wrong-owner-error' ? 'foreign-owner' : 'owner' }); continue;
          }
          if (reply.startsWith('envelope-')) {
            send({ ...response, resultType: 'error', error: reply.slice('envelope-'.length), handledByClientId: 'owner' }); continue;
          }
          const turnId = reply === 'wrong-turn' ? 'foreign-turn' : active ? 'existing-turn' : 'started-turn';
          send({ ...response, handledByClientId: reply === 'wrong-owner' ? 'foreign-owner' : 'owner',
            result: { result: reply === 'missing-turn' ? {} : active ? { turnId } : { turn: { id: turnId } } } }, true);
        }
      }
    });
  };
  let server;
  // Default is an in-process fake duplex socket: no sandbox network access is
  // required and the real framing/parser/request state machine runs unchanged.
  // AGMSG_TEST_UNIX_IPC=1 additionally exercises the native Unix socket syscall
  // on a host that permits bind/listen. It never connects to the live app.
  if (process.env.AGMSG_TEST_UNIX_IPC === '1') {
    server = net.createServer(handleSocket);
  } else {
    t.mock.method(net, 'createConnection', () => {
      const upstream = new PassThrough(), downstream = new PassThrough();
      const clientSocket = Duplex.from({ readable: downstream, writable: upstream });
      const serverSocket = Duplex.from({ readable: upstream, writable: downstream });
      clientSocket.on('error', () => {}); serverSocket.on('error', () => {});
      handleSocket(serverSocket);
      setImmediate(() => clientSocket.emit('connect'));
      return clientSocket;
    });
  }
  const client = new DesktopIpcClient(socketPath, { requestTimeoutMs: 150, connectTimeoutMs: 1000 });
  t.after(async () => {
    client.stop(); for (const connection of connections) connection.destroy();
    if (server?.listening) await new Promise(resolve => server.close(resolve));
    fs.rmSync(dir, { recursive: true, force: true });
  });
  if (server) await new Promise((resolve, reject) => { server.once('error', reject); server.listen(socketPath, resolve); });
  client.start(); await client.ready(); await client.request('initialize', {});
  const bridge = Object.create(CodexBridge.prototype);
  Object.assign(bridge, { opts: { desktopIpc: socketPath, inlineInbox: true, type: 'codex', project: dir, workspaceRoots: [], turnTimeout: 0 },
    threadId: 'bound-thread', turnActive: active, activeTurnId: active ? 'existing-turn' : null, threadIdle: !active,
    pendingWake: true, stopping: false, deliveryPromise: null, deliveryFile: path.join(dir, 'delivery.json'),
    identity: { team: 'sample', name: 'director' }, identities: [{ team: 'sample', name: 'director' }], client, acks: [], armed: 0 });
  bridge.eligiblePairs = () => new Set(['sample\tdirector']);
  bridge.peekInbox = () => [{ team: 'sample', name: 'director', rows: [{ id: 'message', at: '2026-10-15T00:00:00Z', from: 'builder', body: '結果 ready' }] }];
  bridge.acknowledgeDelivery = record => { bridge.acks.push(structuredClone(record)); fs.unlinkSync(bridge.deliveryFile); };
  bridge.armWatch = async () => { bridge.armed++; };
  return { bridge, client, requests, discoveries };
}

test('Desktop idle route uses owner discovery, start version 2 and matching success before ack', async t => {
  const { bridge, requests, discoveries } = await fixture(t);
  await bridge.tryStartTurn();
  const [init, owner, send] = requests;
  assert.equal(init.sourceClientId, 'uninitialized'); assert.equal(init.version, 0);
  assert.equal(owner.sourceClientId, 'assigned-client'); assert.equal(owner.version, 1);
  assert.deepEqual(owner.params, { hostId: 'local', conversationId: 'bound-thread' });
  assert.equal(send.method, 'thread-follower-start-turn'); assert.equal(send.version, 2);
  assert.equal(send.targetClientId, 'owner'); assert.equal(send.params.turnStart.request.threadId, 'bound-thread');
  assert.deepEqual(send.params.turnStart.context, { inheritThreadSettings: true, attachments: [] });
  assert.match(send.params.turnStart.request.input[0].text, /builder: 結果 ready/);
  assert.equal(bridge.acks.length, 1); assert.equal(bridge.acks[0].turnId, 'started-turn');
  assert.equal(bridge.acks[0].requestId, send.requestId);
  assert.equal(bridge.acks[0].clientUserMessageId, send.params.turnStart.request.clientUserMessageId);
  assert.equal(discoveries[0].response.canHandle, false);
});

test('Desktop active route steers the observed native turn using version 1', async t => {
  const { bridge, requests } = await fixture(t, { active: true });
  await bridge.tryStartTurn();
  const send = requests.at(-1);
  assert.equal(send.method, 'thread-follower-steer-turn'); assert.equal(send.version, 1);
  assert.equal(send.params.conversationId, 'bound-thread');
  assert.equal(send.params.restoreMessage.text, send.params.input[0].text);
  assert.deepEqual(send.params.attachments, []); assert.equal(bridge.acks[0].turnId, 'existing-turn');
});

test('Desktop explicit rejection leaves unread and removes only the sending journal', async t => {
  const { bridge } = await fixture(t, { active: true, reply: 'error' });
  await assert.rejects(bridge.tryStartTurn(), error => error.rpcRejected === true);
  assert.equal(bridge.acks.length, 0); assert.equal(bridge.pendingWake, true);
  assert.equal(fs.existsSync(bridge.deliveryFile), false);
});

for (const reply of ['timeout', 'closed', 'missing-turn', 'wrong-owner', 'wrong-owner-error', 'wrong-turn',
  'envelope-request-timeout', 'envelope-client-disconnected', 'envelope-server-closed',
  'envelope-App server request timed out', 'envelope-unknown native error']) {
  test(`Desktop ${reply} moves mail to the terminal admin inbox with correlation and never replays`, async t => {
    const { bridge, requests } = await fixture(t, { active: true, reply });
    const admin = []; let adminAcks = 0; const peek = bridge.peekInbox;
    bridge.adminInboxSend = body => { admin.push(JSON.parse(body)); return { status: 0 }; };
    bridge.adminInboxAck = () => { adminAcks++; return { status: 0 }; };
    bridge.peekInbox = () => adminAcks ? [] : peek();
    await bridge.tryStartTurn();
    assert.equal(admin.length, 1); assert.equal(admin[0].stage, 'direct-uncertain');
    const journal = admin[0].history[0].journal;
    assert.equal(journal.state, 'sending'); assert.equal(admin[0].history[0].path, 'desktop-ipc');
    assert.equal(journal.requestId, requests.at(-1).requestId); assert.ok(journal.clientUserMessageId);
    assert.equal(adminAcks, 1); assert.equal(bridge.acks.length, 0);
    assert.equal(fs.existsSync(bridge.deliveryFile), false);
    const turns = () => requests.filter(r => /turn/.test(r.method || '')).length;
    const previous = turns();
    bridge.pendingWake = true; await bridge.tryStartTurn(); assert.equal(turns(), previous);
  });
}

test('Desktop accepted input recovers a failed acknowledgement without another IPC request', async t => {
  const { bridge, requests } = await fixture(t);
  const acknowledge = bridge.acknowledgeDelivery;
  bridge.acknowledgeDelivery = () => { throw new Error('ack failed'); };
  await assert.rejects(bridge.tryStartTurn(), /ack failed/);
  const record = JSON.parse(fs.readFileSync(bridge.deliveryFile));
  assert.equal(record.state, 'accepted'); assert.equal(record.turnId, 'started-turn');
  const previous = requests.length;
  bridge.acknowledgeDelivery = acknowledge; bridge.recoverDelivery();
  assert.equal(requests.length, previous); assert.equal(bridge.acks.length, 1);
});

test('Desktop unbound session cannot perform owner discovery or send', async t => {
  const { bridge, requests } = await fixture(t);
  bridge.eligiblePairs = () => new Set();
  await assert.rejects(bridge.tryStartTurn(), /ACTIVE membership/);
  assert.deepEqual(requests.map(request => request.method), ['initialize']); assert.equal(bridge.acks.length, 0);
});

test('Desktop owner changed during state discovery cannot send the previously peeked inbox', async t => {
  const { bridge, requests } = await fixture(t);
  bridge.peekInbox = () => { bridge.eligiblePairs = () => new Set(); return [{ team: 'sample', name: 'director', rows: [{ id: 'message', at: '', from: 'builder', body: 'ready' }] }]; };
  await assert.rejects(bridge.tryStartTurn(), /ACTIVE membership/);
  assert.equal(requests.some(request => request.method.startsWith('thread-follower-')), false);
  assert.equal(bridge.acks.length, 0);
});

for (const options of [{ version: 12 }, { state: { id: 'bound-thread', turns: [] } },
  { state: { ...conversation(true), turns: [] } }]) {
  test(`Desktop unknown state fails closed: ${JSON.stringify(options)}`, async t => {
    const { bridge, requests } = await fixture(t, options);
    await assert.rejects(bridge.tryStartTurn());
    assert.equal(bridge.acks.length, 0); assert.equal(fs.existsSync(bridge.deliveryFile), false);
    assert.equal(requests.some(request => request.method.startsWith('thread-follower-')), false);
  });
}

test('Desktop canonical state uses newest complete boundary and rejects missing latest state', () => {
  const state = { ...conversation(), turnHistory: { kind: 'canonical', history: {
    islands: [{ entries: [{ value: 'old' }], newerBoundary: { status: 'available' } },
      { entries: [{ value: 'new' }], newerBoundary: { status: 'exhausted' } }],
    entitiesByKey: { old: { turnId: 'historical', status: 'inProgress' }, new: { turnId: 'latest', status: 'completed' } } } } };
  assert.deepEqual(turnState(state, 'bound-thread'), { active: false, turnId: null });
  state.turnHistory.history.islands[1].newerBoundary.status = 'available';
  assert.throws(() => turnState(state, 'bound-thread'), /boundary is unknown/);
  state.turnHistory.history.islands[1].newerBoundary.status = 'exhausted';
  delete state.turnHistory.history.entitiesByKey.new;
  assert.throws(() => turnState(state, 'bound-thread'), /entity is missing/);
  state.turnHistory.history.islands[1].entries = null;
  assert.throws(() => turnState(state, 'bound-thread'), /entries are malformed/);
});
