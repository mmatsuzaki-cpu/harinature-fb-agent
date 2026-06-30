# 🪡 HARI NATURE 育成FBシステム

定額制の美容鍼サロン「HARI NATURE」新人スタッフ向けの、新規カウンセリング録音からAIで育成FBを自動生成するシステム。

## 仕組み

1. スタッフが録音(m4a/mp3/wav)をアップロード
2. Gemini Flash 2.5 に音声を直接渡して文字起こし(大ファイルは ffmpeg で圧縮→5分チャンク並列処理)
3. Gemini Flash 2.5 でハリナチュレ哲学に沿った4項目評価+FB生成
   - ヒアリング / 提案 / クロージング / トーン
   - 「7つの感」「危機感トーク」「3ヶ月提案」「入会金無料」を必ずチェック
   - お客様情報(年齢/仕事/悩み/既往歴)は録音から自動抽出
4. Slack(#ハリナチュレ_新規振り返り)に投稿 + 松崎完了DM
5. Notion DB「🪡 ハリナチュレ育成FB履歴」に蓄積
6. 音声ファイルは処理後に即削除(個人情報保護)

## デプロイ

- Streamlit Cloud: https://harinature-fb.streamlit.app/
- スタッフ用URL: https://harinature-fb.streamlit.app/
  ※ パスワード認証なし(スタッフが即アクセスできるよう開放)。
    録音は処理後即削除・Notionには会員情報のみ保存で個人情報保護。

## 環境変数 (Streamlit Cloud Secrets / GitHub Secrets)

| Key | 用途 |
|-----|------|
| `GEMINI_API_KEY` | Gemini Flash 2.5 |
| `SLACK_BOT_TOKEN` | ハリナチュレ用 Slack Bot |
| `SLACK_FEEDBACK_CHANNEL_ID` | #ハリナチュレ_新規振り返り のチャンネルID |
| `SLACK_OWNER_USER_ID` | 松崎さんの Slack User ID |
| `NOTION_TOKEN` | Notion integration |
| `NOTION_FB_HISTORY_DB_ID` | 🪡 ハリナチュレ育成FB履歴 DB |
| `NOTION_LEADER_FB_DB_ID` | (任意) リーダーFB事例集 DB |
