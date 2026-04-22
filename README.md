# HA×SH / ジチタイワークス 新着PDF要約ボット

この仕組みは、`https://hash.jichitai.works` の新着記事をチェックし、新しい記事が見つかった場合に資料PDFをダウンロードして要約し、翌朝8時ごろにLINEへ送るためのたたき台です。

## できること
- 新着記事一覧（新着順）を確認
- 新しいサービス記事だけをキューに追加
- 会員ログイン後に資料PDFのダウンロードを試行
- OpenAI APIで日本語要約
- LINE Messaging APIでスマホに送信

## 先に知っておくこと
- PDFダウンロードは会員ログイン前提です
- サイト側のHTML構造が変わると、ダウンロード部分は修正が必要です
- GitHub Actionsで動かす場合、Secrets登録が必要です
- このコードは公式提供物ではなく、自動化用のカスタム実装です

## 1. GitHubに置くファイル
このフォルダごとリポジトリに置いてください。

## 2. GitHub Secrets に入れるもの
リポジトリの `Settings > Secrets and variables > Actions` で追加します。

- `OPENAI_API_KEY`
- `OPENAI_MODEL` → 例: `gpt-5`
- `HASH_EMAIL`
- `HASH_PASSWORD`
- `LINE_CHANNEL_ACCESS_TOKEN`
- `LINE_USER_ID`

## 3. LINE_USER_ID の取り方
### いちばん簡単
- LINE公式アカウントを作成
- Messaging APIチャネルを作成
- Botを自分のLINEで友だち追加
- Webhookで自分から1回メッセージを送る
- 受信イベントのJSONから `userId` を確認

## 4. 実行タイミング
ワークフローは `Asia/Tokyo` の **毎朝 7:55** に動く設定です。少し前倒しにしているのは、GitHub Actionsのスケジュール実行が混み合う時間に遅れることがあるためです。

必要なら 8:00 ぴったりにも変更できます。

## 5. ローカルで試す方法
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
```

`.env` を作ったら、例えば次で実行できます。
```bash
export $(grep -v '^#' .env | xargs)
python hash_digest_bot.py
```

## 6. 改良案
- 前日分だけ送るように厳密化する
- 要約結果をGoogleスプレッドシートにも保存する
- LINEではなくメールやSlackにも送る
- 要約に「猪名川町で使えるか」の観点を追加する
