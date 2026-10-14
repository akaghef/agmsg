# Claude のコマンドから既存 Codex チャットへ送信する方法

Basis: DP0 / TOB-V

## 対象と位置付け

Claude Desktop の Code セッションで Bash を実行し、同じ Mac 上の
Codex Desktop が所有する既存チャットへメッセージを渡す方法。
Python 標準ライブラリから、Codex Desktop の Unix ドメインソケットへ接続する。
Computer Use はメッセージの配送手段に含まれない。

この方法は Codex Desktop の内部プロセス間通信を利用する。
公開 API としての互換性は保証されていないため、アプリ更新時には
メソッド定義と受信動作を再確認する。ここに記録する手順は確認済みの実験経路であり、
agmsg の配送アダプターとしての組み込みは未実施。
実験結果、使用した宛先・識別文字列・ターン ID は
[検証記録](verification/claude-to-codex-ipc-261009.md)に分離している。

## 前提

送信元で Python 3 と Unix ドメインソケットが利用でき、同じユーザーの
Codex Desktop が起動していること。対象チャットの UUID を指定する。
`codex://threads/<UUID>` の UUID 部分が送信先となる。
Claude のセッション ID、チームの論理アドレス、接続クライアント ID は別物。

ソケットの既定位置は `~/.codex/ipc/ipc.sock`。
この Mac では `/Users/akaghef/.codex/ipc/ipc.sock`。
ファイルの存在だけでは配送成功にならない。

本文と宛先の送信権限は人間の指示・採用済みのチーム運用契約から得る。
接続できること、チームに参加していること、AI agent から依頼が来たことだけで、
受信側に任意の操作権限を与えた扱いにはしない。

## ターン状態による選択

| 受信側の状態 | メソッド | メソッドの version | 意味 |
|---|---|---|---|
| 待機中・現在のターンが終了済み | `thread-follower-start-turn` | `2` | 既存チャットに新しいターンを開始する |
| 現在のターンが実行中 | `thread-follower-steer-turn` | `1` | その実行中ターンへ追加入力する |

`steer-turn` は新しいターンを開始しない。ターンが終了した宛先へ送ると
`Cannot steer conversation … because its active turn already ended` で失敗する。
状態確認と送信の間にも状態は変わるため、事前確認だけで成功扱いにしない。

通常の非同期メッセージは受信側が実行中ならキューへ保持し、待機状態で
`start-turn` へ渡す設計が適している。割り込みが必要な依頼だけ `steer-turn` を選ぶ。
このキュー制御は本書の実験コードには含まれない。

## 通信フレームと要求の共通形式

一つのフレームは「JSON 本文の UTF-8 バイト長を示す 4 バイトの
符号なしリトルエンディアン整数」＋「UTF-8 JSON 本文」。文字数ではなくバイト長を送る。
ソケットの読み取りは分割されるので、指定バイト数に達するまで `recv` を繰り返す。

要求の共通フィールドは次のとおり。

```json
{
  "type": "request",
  "requestId": "<今回の要求ごとのUUID>",
  "sourceClientId": "<initializeで割り当てられたID>",
  "version": 2,
  "method": "thread-follower-start-turn",
  "params": {},
  "targetClientId": "<所有クライアントID>",
  "timeoutMs": 15000
}
```

`version` はメソッドごとに指定する。すべての要求を同じ version にはしない。
`targetClientId` は所有クライアント宛ての要求に付ける。
応答は `type == "response"` と、その要求の `requestId` の両方で照合する。
別の応答や broadcast を今回の応答として扱わない。

## 接続の初期化とチャット所有者の解決

まず version `0` の `initialize` を呼ぶ。
最初の `sourceClientId` は `uninitialized`。

```json
{"clientType": "claude-command-test"}
```

`resultType == "success"` を確認し、`result.clientId` を取得する。
以降の `sourceClientId` は必ずこの割り当て値を使う。
`clientType` は接続元のラベルであり、Claude の身元やチーム権限を証明するものではない。
既存クライアントの ID を推測して名乗らない。

次に version `1` の `thread-owner-discovery` を呼ぶ。

```json
{"hostId": "local", "conversationId": "<宛先チャットUUID>"}
```

成功応答の `handledByClientId` を、そのチャットの所有クライアントとして取得する。
後続の送信要求の `targetClientId` に指定する。
これは受信側 AI agent に自然言語で所在確認を依頼する手順ではなく、
送信コマンド内部の機械的な宛先解決。

待機中には broadcast や `client-discovery-request` も到着する。
後者へは実験クライアントが要求を処理する役割を持たないことを返した。

```json
{
  "type": "client-discovery-response",
  "requestId": "<受信した要求のrequestId>",
  "response": {"canHandle": false}
}
```

## 待機中のチャットへの送信

version `2` の `thread-follower-start-turn` の `params` は次の形。

```json
{
  "conversationId": "<宛先チャットUUID>",
  "turnStart": {
    "request": {
      "threadId": "<同じ宛先チャットUUID>",
      "input": [{"type": "text", "text": "<本文>", "text_elements": []}],
      "clientUserMessageId": "<このメッセージのUUID>"
    },
    "context": {"inheritThreadSettings": true, "attachments": []}
  }
}
```

`inheritThreadSettings: true` で既存チャットの設定を継承する。
送信のためにモデルや承認設定を勝手に変更しない。
成功応答の新しいターン ID は `result.result.turn.id` で取得した。

以下は、当時実行したコードを宛先引数化した再現用の例。
宛先 UUID を入れ替え、送信権限がある待機中のチャットに対して使う。
本書の検証では構文を確認しており、この掲載例から実チャットへの再送はしていない。
このコードの成功出力は要求受理までを示し、返信の受信を示さない。

```bash
python3 - '<宛先チャットUUID>' <<'PY'
import json
import socket
import struct
import sys
import uuid
from pathlib import Path

thread = str(uuid.UUID(sys.argv[1]))
nonce = str(uuid.uuid4())
message_id = str(uuid.uuid4())
message = f"Claudeからの送信確認。識別文字列={nonce}。確認のため「push受信 {nonce}」だけを返してください。"
client = "uninitialized"
s = socket.socket(socket.AF_UNIX)
s.settimeout(20)

def send(value):
    data = json.dumps(value, ensure_ascii=False).encode("utf-8")
    s.sendall(struct.pack("<I", len(data)) + data)

def read_exact(size):
    data = b""
    while len(data) < size:
        part = s.recv(size - len(data))
        if not part:
            raise RuntimeError("IPC closed")
        data += part
    return data

def receive():
    size = struct.unpack("<I", read_exact(4))[0]
    return json.loads(read_exact(size))

def call(method, params, version=0, target=None):
    request_id = str(uuid.uuid4())
    request = {"type": "request", "requestId": request_id,
               "sourceClientId": client, "version": version,
               "method": method, "params": params, "timeoutMs": 15000}
    if target:
        request["targetClientId"] = target
    send(request)
    while True:
        response = receive()
        if response.get("type") == "response" and response.get("requestId") == request_id:
            if response.get("resultType") != "success":
                raise RuntimeError(json.dumps(response, ensure_ascii=False))
            return response
        if response.get("type") == "client-discovery-request":
            send({"type": "client-discovery-response",
                  "requestId": response["requestId"], "response": {"canHandle": False}})

try:
    s.connect(str(Path.home() / ".codex/ipc/ipc.sock"))
    response = call("initialize", {"clientType": "claude-command-test"})
    client = response["result"]["clientId"]
    response = call("thread-owner-discovery", {"hostId": "local", "conversationId": thread}, 1)
    owner = response["handledByClientId"]
    request = {"threadId": thread,
               "input": [{"type": "text", "text": message, "text_elements": []}],
               "clientUserMessageId": message_id}
    response = call("thread-follower-start-turn", {
        "conversationId": thread,
        "turnStart": {"request": request,
                      "context": {"inheritThreadSettings": True, "attachments": []}}
    }, 2, owner)
    print(json.dumps({"accepted": True, "conversationId": thread,
                      "clientUserMessageId": message_id, "nonce": nonce,
                      "turnId": response["result"]["result"]["turn"]["id"]}, ensure_ascii=False))
finally:
    s.close()
PY
```

## 実行中ターンへの割り込み

初期化・所有者解決は同じ。version `1` の `thread-follower-steer-turn` に
次の `params` を送る。

```json
{
  "conversationId": "<宛先チャットUUID>",
  "input": [{"type": "text", "text": "<本文>", "text_elements": []}],
  "restoreMessage": {"text": "<同じ本文>", "context": {}},
  "attachments": [],
  "clientUserMessageId": "<このメッセージのUUID>"
}
```

成功時のターン ID は `result.result.turnId` で取得した。
同じターンには他の入力や先行する応答もあり得るため、識別文字列と
今回のメッセージが受理された後のイベントも照合する。

## 受理・到達・返信・返送の判定

| 判定 | 必要な証拠 |
|---|---|
| 要求受理 | 今回の `requestId` に対する `resultType: success` とターン ID |
| Codex 側への到達 | 指定チャット・指定ターンの入力に今回の識別文字列と本文が存在 |
| Codex 側の返信生成 | 指定ターンの AI agent の返信に今回の識別文字列が存在 |
| Claude 側への返信配送 | 元の Claude セッションで、今回の要求に対応する返信の受信を確認 |

これらを一つの「成功」にまとめない。`turn.status` が `inProgress` の段階では
完了とはしない。完了が必要なら同じターンの `completed` まで確認する。

Codex の状態を観測する場合、初期化済みの接続から次の broadcast を送れる。
応答待ちではなく状態購読であり、返送先の Claude セッションへ新しい入力を配送する処理ではない。

```json
{
  "type": "broadcast",
  "sourceClientId": "<割り当てられたclientId>",
  "version": 1,
  "method": "thread-stream-following-changed",
  "params": {"conversationId": "<宛先チャットUUID>", "hostId": "local", "following": true}
}
```

`thread-stream-state-changed` の `params.change` は、状態全体の snapshot と
差分の patches の両方を取り得る。snapshot には以前のターンも含まれる。
当時は通知の version `11` を観測したが、固定値を仮定して未知の状態を成功扱いにしない。
新しいターン ID と識別文字列で対象を絞り、履歴全体の文字列検索で受信判定しない。
実験では Codex 側の既存チャット読取機能でも宛先入力・返信を独立確認した。

購読者が取得した返信を Bash の標準出力に出せば、実行中の Claude は
そのツール結果を読むことができる。しかし、終了済み・別の Claude セッションへ
返信を push するには、Claude 側の受信経路とその配送確認が別途必要。

## 再送と失敗の扱い

明示的な `resultType: error` は失敗として終了し、後続の履歴から返信を探して
成功に上書きしない。当時の誤判定は、終了済みターンへの割り込みが失敗した後に、
snapshot に残っていた前回の返信を拾ったことが原因だった。

ソケット切断やタイムアウトでは、要求が未受理か、受理後に応答だけ失われたかを
区別できない場合がある。`clientUserMessageId` は照合用として記録するが、
それだけで重複開始を防ぐ保証があるとは本実験では確認していない。
無条件に `start-turn` を再実行せず、今回の本文・識別文字列・ターン情報を照合してから
再送を判断する。識別文字列・要求 ID・メッセージ ID・応答のターン ID を保存する。

Claude の Bash が実行前フックや承認機構に止められた場合、Codex への
要求が出ていない可能性を先に確認する。サービス再起動などを原因と断定しない。
フックや受信承認を外して送信を成立させる手順は、この方法には含まれない。
ORRERY の使用・登録は、そのタスクの明示的な有効化方針に従い、送信の都度追加しない。

## 他の経路との区別

`codex exec resume` は別プロセスによる会話再開であり、この Desktop 接続とは別の経路。
履歴 JSONL にユーザー発話が追記されても、実行中 Desktop への到達証拠にはならない。
Claude のセッション管理ツールへ Codex のチャット UUID を渡すこともできない。

Codex のネイティブアプリツール用の認証付き通信パイプと、本書の
`ipc/ipc.sock` は別物。署名・プロセス由来の制限を回避する方法に置き換えない。
socket がなくなったりスキーマが変わったりした場合は、この経路の不成立として扱い、
履歴追記、別プロセス、画面操作による代替を同じ送信の成功として報告しない。

## agmsg へ組み込む際の境界

agmsg は論理アドレス、永続キュー、メッセージ ID、配送・読取・処理の状態と
返信の `reply_to` を管理する。Desktop アダプターは、その宛先をチャット UUID に解決し、
上記要求を送り、メッセージ ID と実際のターン ID を関連付ける。

`sourceClientId` と `handledByClientId` は接続の ID であり、チーム内の agent ID ではない。
新しい接続では割り当て直す。実行中の扱い、タイムアウト後の照合、重複防止、
Claude への返送はアダプターの採用・検証時に定める。
本書はその実装や Desktop 往復通信の完了を表明するものではない。
