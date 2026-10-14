# Claude → Codex Desktop のコマンド送信：検証記録

Basis: TOB-V

実験日: 2026-10-09 JST。文書化日: 2026-10-14 JST。
本記録は、このチャットの実行記録から確認済み事項を抽出したもの。
文書化のための新規送信はしていない。

## 確認済みの実行

Claude Desktop の Code セッションの Bash から、同じ Mac の
`/Users/akaghef/.codex/ipc/ipc.sock` へ Python で接続した。
`initialize` → `thread-owner-discovery` → `thread-follower-start-turn` を呼んだ。
最後の要求の version は `2`。画面操作は Claude への実験依頼の受け渡しに使われたが、
メッセージ配送そのものは Bash からのソケット通信だった。

| 項目 | 観測値 |
|---|---|
| 宛先 | `codex://threads/01a11c5a-8f8d-70e1-9335-8364d42f77c0` |
| 当時のチャット名 | `msg送受信master` |
| 識別文字列 | `fe5e5531-daa1-401d-ad81-e4e735cf4b60` |
| 新しいターン ID | `01a11c7a-5ac6-7f70-8d09-cba9ccec409c` |
| 受理応答 | `resultType: success`、所有クライアントの `handledByClientId` |
| Codex 側の返信 | `push受信 fe5e5531-daa1-401d-ad81-e4e735cf4b60` |

送信直後の状態は `inProgress`。Codex 側の既存チャット読取と完了確認により、
同じ新規ターンの入力、識別文字列付き返信、`completed` を独立確認した。
Claude で実行した当該 start-turn コード自体には返信観測処理が含まれていなかった。

このチャット
`codex://threads/01a11c5a-5a6e-74d1-b3d8-8589740ed356`
へは、実行中ターンに version `1` の `thread-follower-steer-turn` で送信し、
「Claudeコマンド受信確認 261009」という返信を観測した別の実験もある。

## 確認の限界と失敗

元の Claude セッションへの返信配送は、この実験では完了確認していない。
Codex 側で返信を生成したことを、往復配送の成功とは扱わない。

終了済みターンへ steer を再送した試験では、サーバーが error を返した。
当時の観測コードはその error で終了せず、状態 snapshot の過去の返信を検索したため、
前回の返信を今回の返信として誤認した。start-turn 試験ではその観測コードを除き、
新しい識別文字列と実際のターン ID による独立確認に変更した。

別経路の `codex exec resume` は CLI 0.139.0 からモデル `gpt-6.1-sol` を
使おうとして HTTP 400 になった。ユーザー発話の履歴追記はあったが、
その操作から Desktop への到達・応答生成が成立したとは確認していない。

## 文書化時の確認

2026-10-14 に、インストールされた Codex の
`/Applications/Codex.app/Contents/Resources/app.asar` 内のメソッド定義を読み取った。
package version は `26.1007.71326`、メソッド定義のファイルは
`.vite/build/src-DCNiwad_.js`。
`thread-owner-discovery: 1`、`thread-follower-start-turn: 2`、
`thread-follower-steer-turn: 1`、`thread-stream-following-changed: 1` が
当時の送信コードと一致していた。現在版での実配送再試験は行っていない。

主な原記録は、Codex チャットログ
`rollout-2026-10-09T01-37-23-01a11c5a-5a6e-74d1-b3d8-8589740ed356_01a11c60-6c56-7243-9e76-f1199bed35ed.jsonl`
にある。送信コードの依頼記録は `2026-10-08T17:04:45.502Z`、
Claude の受理報告は `2026-10-08T17:05:54.377Z`。
このログ全体をフォークへ複製していない。

要求形式と再現用コードは
[送信方法](../codex-desktop-ipc-send.md)を参照。
