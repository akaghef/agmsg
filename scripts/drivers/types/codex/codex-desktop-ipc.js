"use strict";

// Transport adapter for the existing CodexBridge. Queue ownership, the delivery
// journal and acknowledgements stay in that bridge; this class only implements
// its client interface using Desktop's documented native IPC protocol.
const net = require("node:net");
const crypto = require("node:crypto");
const { spawn } = require("node:child_process");

const STATE_VERSION = 11; // Installed Desktop schema; unknown versions fail closed.
const MAX_FRAME = 64 * 1024 * 1024;

function turnState(state, threadId) {
  if (!state || state.id !== threadId || !Array.isArray(state.turns)) {
    throw new Error("Desktop snapshot does not describe the requested conversation");
  }
  if (state.unconfirmedTurnSubmissions?.some((turn) => turn.terminal !== true)) {
    throw new Error("Desktop has a pending turn submission; inbox remains unread");
  }
  let turns = state.turns;
  if (state.turnHistory?.kind === "canonical") {
    const history = state.turnHistory.history;
    if (!Array.isArray(history?.islands) || !history.entitiesByKey) {
      throw new Error("Desktop canonical turn history is unavailable");
    }
    // Canonical islands are chronological; only the newest island establishes
    // current turn state. Never search old history for a success or active turn.
    const newest = history.islands.at(-1);
    if (!newest || newest.newerBoundary?.status !== "exhausted") {
      throw new Error("Desktop latest turn boundary is unknown");
    }
    if (!Array.isArray(newest.entries)) throw new Error("Desktop latest turn entries are malformed");
    turns = newest.entries.map((entry) => {
      if (!entry || typeof entry.value !== "string" || !Object.hasOwn(history.entitiesByKey, entry.value)) {
        throw new Error("Desktop latest turn entity is missing");
      }
      const turn = history.entitiesByKey[entry.value];
      if (!turn || typeof turn !== "object") throw new Error("Desktop latest turn entity is malformed");
      return turn;
    });
  }
  const last = turns.at(-1);
  if (last && !["inProgress", "completed", "failed", "interrupted"].includes(last.status)) {
    throw new Error("Desktop latest turn status is unknown");
  }
  const active = last?.status === "inProgress" || state.threadRuntimeStatus?.type === "active";
  if (active) {
    if (last?.status !== "inProgress" || typeof last.turnId !== "string" || !last.turnId) {
      throw new Error("Desktop active turn ID unavailable; inbox remains unread");
    }
    return { active: true, turnId: last.turnId };
  }
  if (state.resumeState !== "resumed" ||
      (state.threadRuntimeStatus && state.threadRuntimeStatus.type !== "idle")) {
    throw new Error("Desktop idle state is not established; inbox remains unread");
  }
  return { active: false, turnId: null };
}

class DesktopIpcClient {
  constructor(socketPath, opts = {}) {
    this.socketPath = socketPath;
    this.timeoutMs = opts.requestTimeoutMs || 15000;
    this.connectTimeoutMs = opts.connectTimeoutMs || 10000;
    this.clientId = "uninitialized";
    this.pending = new Map();
    this.handlers = new Map();
    this.children = new Map();
    this.buffer = Buffer.alloc(0);
    this.stopped = false;
  }

  on(method, handler) { this.handlers.set(method, handler); }
  onRequest() {} // Approval handling remains entirely with Desktop's owner.
  emit(method, params) { this.handlers.get(method)?.(params); }

  start() {
    this.readyPromise = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        const error = new Error("Desktop IPC connection timeout");
        reject(error); this.socket.destroy(error);
      }, this.connectTimeoutMs);
      this.socket = net.createConnection(this.socketPath);
      this.socket.once("connect", () => { clearTimeout(timer); resolve(); });
      this.socket.on("error", (error) => { clearTimeout(timer); reject(error); this.fail(error); });
      this.socket.on("close", () => this.fail(new Error("Desktop IPC connection closed")));
      this.socket.on("data", (data) => {
        try { this.receive(data); } catch (error) { this.fail(error); this.socket.destroy(); }
      });
    });
  }

  ready() { return this.readyPromise; }

  fail(error) {
    for (const pending of this.pending.values()) { clearTimeout(pending.timer); pending.reject(error); }
    this.pending.clear();
    if (this.snapshotWaiter) {
      clearTimeout(this.snapshotWaiter.timer);
      this.snapshotWaiter.reject(error);
      this.snapshotWaiter = null;
    }
  }

  write(value) {
    if (!this.socket || this.socket.destroyed) throw new Error("Desktop IPC is disconnected");
    const body = Buffer.from(JSON.stringify(value));
    const header = Buffer.alloc(4);
    header.writeUInt32LE(body.length);
    this.socket.write(Buffer.concat([header, body]));
  }

  receive(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    while (this.buffer.length >= 4) {
      const size = this.buffer.readUInt32LE(0);
      if (!size || size > MAX_FRAME) throw new Error("Invalid Desktop IPC frame length");
      if (this.buffer.length < size + 4) return;
      const message = JSON.parse(this.buffer.subarray(4, size + 4).toString("utf8"));
      this.buffer = this.buffer.subarray(size + 4);
      if (message.type === "client-discovery-request") {
        this.write({ type: "client-discovery-response", requestId: message.requestId, response: { canHandle: false } });
      } else if (message.type === "response") {
        const pending = this.pending.get(message.requestId);
        if (!pending) continue;
        clearTimeout(pending.timer); this.pending.delete(message.requestId);
        if (pending.owner && message.handledByClientId !== pending.owner) {
          pending.reject(new Error("Desktop response owner mismatch; outcome uncertain"));
        } else if (message.resultType === "error") {
          // A native error envelope can mean the router timed out AFTER
          // forwarding. Only a known pre-dispatch turn rejection is safe to
          // retry; unknown errors, disconnects and server timeouts keep the
          // sending journal. Never infer non-delivery from resultType alone.
          const confirmed = pending.method === "thread-follower-steer-turn" &&
            typeof message.error === "string" &&
            /^(?:Error: )?Cannot steer conversation \S+ because its active turn already ended$/.test(message.error);
          pending.reject(Object.assign(new Error(confirmed ? "Desktop request rejected" : "Desktop request failed; outcome uncertain"),
            { rpcRejected: confirmed, rpcError: message.error }));
        } else if (message.resultType !== "success") {
          pending.reject(new Error("Desktop response result type mismatch; outcome uncertain"));
        } else pending.resolve(message);
      } else if (message.type === "broadcast" && message.method === "thread-stream-state-changed") {
        const params = message.params || {};
        if (!this.snapshotWaiter || params.conversationId !== this.threadId || params.hostId !== "local" ||
            message.sourceClientId !== this.ownerId) continue;
        // Patches are never interpreted as a complete state. Each delivery
        // toggles the existing stream subscription to request a fresh snapshot.
        if (params.change?.type !== "snapshot") continue;
        const waiter = this.snapshotWaiter;
        this.snapshotWaiter = null; clearTimeout(waiter.timer);
        try {
          if (message.version !== STATE_VERSION) throw new Error("Unsupported Desktop state schema version");
          this.state = turnState(params.change.conversationState, this.threadId);
          waiter.resolve(this.state);
        } catch (error) { waiter.reject(error); }
      }
    }
  }

  call(method, params, version, owner, requestId = crypto.randomUUID()) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(requestId);
        reject(new Error(`Desktop ${method} timeout; outcome uncertain`));
      }, this.timeoutMs);
      this.pending.set(requestId, { resolve, reject, timer, owner, method });
      try {
        this.write({ type: "request", requestId, sourceClientId: this.clientId, version, method, params,
          ...(owner ? { targetClientId: owner } : {}), timeoutMs: this.timeoutMs });
      } catch (error) { clearTimeout(timer); this.pending.delete(requestId); reject(error); }
    });
  }

  following(value) {
    this.write({ type: "broadcast", sourceClientId: this.clientId, version: 1,
      method: "thread-stream-following-changed", params: { conversationId: this.threadId, hostId: "local", following: value } });
  }

  async refreshState(threadId) {
    this.threadId = threadId;
    // Owner discovery precedes any turn submission. Its failure (an error such
    // as no-client-found for a thread the Desktop has not loaded, a discovery
    // timeout, or a missing owner) is a confirmed non-delivery: the next
    // delivery path may take over without risking a duplicate turn.
    let response;
    try {
      response = await this.call("thread-owner-discovery", { hostId: "local", conversationId: threadId }, 1);
    } catch (error) {
      throw Object.assign(new Error(`Desktop conversation owner unavailable: ${error.rpcError || error.message}`),
        { preDispatch: true, rpcError: error.rpcError });
    }
    if (typeof response.handledByClientId !== "string" || !response.handledByClientId) {
      throw Object.assign(new Error("Desktop conversation owner unavailable"), { preDispatch: true });
    }
    this.ownerId = response.handledByClientId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.snapshotWaiter = null;
        reject(new Error("Desktop conversation state timeout; inbox remains unread"));
      }, this.timeoutMs);
      this.snapshotWaiter = { resolve, reject, timer };
      try { this.following(false); this.following(true); }
      catch (error) { clearTimeout(timer); this.snapshotWaiter = null; reject(error); }
    });
  }

  prepareDelivery() {
    return { transport: "desktop-ipc", requestId: crypto.randomUUID(), clientUserMessageId: crypto.randomUUID() };
  }

  async sendTurn(method, params) {
    const metadata = params.delivery;
    if (!metadata || params.threadId !== this.threadId) throw new Error("Desktop delivery lacks a matching journal");
    const active = method === "turn/steer";
    if (active !== this.state?.active || (active && params.expectedTurnId !== this.state.turnId)) {
      throw Object.assign(new Error("Desktop turn state changed before send"), { rpcRejected: true });
    }
    const text = params.input.map((item) => item.text).join("\n");
    const common = { conversationId: this.threadId };
    const nativeParams = active ? { ...common, input: params.input, restoreMessage: { text, context: {} },
      attachments: [], clientUserMessageId: metadata.clientUserMessageId } : { ...common,
      turnStart: { request: { threadId: this.threadId, input: params.input, clientUserMessageId: metadata.clientUserMessageId },
        context: { inheritThreadSettings: true, attachments: [] } } };
    const response = await this.call(active ? "thread-follower-steer-turn" : "thread-follower-start-turn",
      nativeParams, active ? 1 : 2, this.ownerId, metadata.requestId);
    const turnId = active ? response.result?.result?.turnId : response.result?.result?.turn?.id;
    if (typeof turnId !== "string" || !turnId || (active && turnId !== params.expectedTurnId)) {
      throw new Error("Desktop successful response lacks the matching turn ID; outcome uncertain");
    }
    return active ? { turnId } : { turn: { id: turnId } };
  }

  async request(method, params) {
    if (method === "initialize") {
      const result = await this.call("initialize", { clientType: "agmsg-codex-bridge" }, 0);
      if (typeof result.result?.clientId !== "string" || !result.result.clientId) throw new Error("Desktop initialize omitted client ID");
      this.clientId = result.result.clientId;
      return result.result;
    }
    if (method === "thread/resume") {
      const state = await this.refreshState(params.threadId);
      return { thread: { id: params.threadId, status: { type: state.active ? "active" : "idle" } } };
    }
    if (method === "thread/turns/list") return { data: this.state?.active ? [{ id: this.state.turnId, status: "inProgress" }] : [] };
    if (method === "turn/start" || method === "turn/steer") return this.sendTurn(method, params);
    if (method === "process/spawn") {
      // Reuse watch-once.sh exactly as app-server delivery does. Desktop IPC
      // has no process/spawn method; the adapter owns only that local child.
      const child = spawn(params.command[0], params.command.slice(1), { cwd: params.cwd,
        env: { ...process.env, CODEX_THREAD_ID: this.threadId }, stdio: ["ignore", "pipe", "pipe"] });
      this.children.set(params.processHandle, child);
      let stdout = "", stderr = "";
      child.stdout.on("data", (chunk) => { stdout = (stdout + chunk).slice(-8192); });
      child.stderr.on("data", (chunk) => { stderr = (stderr + chunk).slice(-8192); });
      const timer = setTimeout(() => child.kill(), params.timeoutMs);
      child.once("error", (error) => { stderr = error.message; });
      child.once("close", (code) => {
        clearTimeout(timer); this.children.delete(params.processHandle);
        if (!this.stopped) this.emit("process/exited", { processHandle: params.processHandle, exitCode: code ?? 1, stdout, stderr });
      });
      return {};
    }
    if (method === "process/kill") { this.children.get(params.processHandle)?.kill(); return {}; }
    throw new Error(`Desktop adapter does not support ${method}`);
  }

  notify() {} // app-server initialized has no Desktop equivalent.

  stop() {
    this.stopped = true;
    for (const child of this.children.values()) child.kill();
    this.children.clear();
    this.fail(new Error("Desktop adapter stopped"));
    this.socket?.destroy();
  }
}

module.exports = { DesktopIpcClient, turnState };
