"""test_kentou_flow.py - 「検討」パターンでフル動作テスト
   Gemini評価 → Slack通知 → Notion保存 まで通す

実行方法:
  cd /Users/user/projects/harinature-fb-agent
  python3 scripts/test_kentou_flow.py
"""

import os
import sys
from datetime import date
from pathlib import Path

# Streamlit を mock(secrets を環境変数から読ませる)
sys.modules.setdefault("streamlit", type(sys)("streamlit"))

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 環境変数読み込み
def _load_env_file(p):
    if not os.path.exists(p):
        return
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)

_load_env_file("/Users/user/projects/pilates-rag-agent/config/.env")
_load_env_file("/Users/user/projects/harinature-rag-agent/config/.env")
os.environ["NOTION_FB_HISTORY_DB_ID"] = "36daf68b-7a63-8126-b7c1-f2b4328cd8b2"
os.environ["SLACK_FEEDBACK_CHANNEL_ID"] = "C0B1WQ495EV"
# Slack bot tokenは harinature-rag-agent から読む
with open("/Users/user/projects/harinature-rag-agent/config/slack_bot_token.txt") as f:
    os.environ["SLACK_BOT_TOKEN"] = f.read().strip()

from coaching import coaching_analyzer

# Streamlit secrets 経由で読まれた値を環境変数で上書き
for k in ("GEMINI_API_KEY", "NOTION_TOKEN", "NOTION_FB_HISTORY_DB_ID",
          "SLACK_BOT_TOKEN", "SLACK_FEEDBACK_CHANNEL_ID", "SLACK_OWNER_USER_ID"):
    setattr(coaching_analyzer, k, os.environ.get(k, ""))


# ──「検討」パターンの現実的なダミー文字起こし ─────
DUMMY_TRANSCRIPT = """
本日はお越しいただきありがとうございます。今日はカウンセリングと施術を1時間ほどさせていただきますね。
お悩みは顔のむくみとたるみということですが、いつ頃から気になり始めましたか?
そうなんですね、産後からですね、3人目を出産されてから1年くらいですか。
お仕事は看護師さんで、夜勤もされていると。睡眠時間が不規則だとお肌にも影響出やすいですよね。
今のスキンケアはどんな感じですか?なるほど、市販のスキンケアで。

それでは施術始めますね。鍼は初めてですか?ちょっとチクッとするかもしれませんが、痛かったらすぐ教えてください。
(施術中)
はい、終わりました。お顔触ってみていただいてもいいですか?どうですか?
あ、軽くなった感じありますね。よかったです。

今後についてなんですが、サブスクのご案内も少しさせていただきますね。
月3回コースが人気で、月額3万9千円です。週1で来ていただくのが理想なんですが、
お忙しいので月3回がおすすめです。
…
あ、検討されますか?わかりました、ぜひご家族とも相談されてみてください。
入会金は通常2万円ですが、本日ご入会の場合は無料になります。
今日中にLINEでも大丈夫なので、ご検討いただけたらと思います。
"""

CUSTOMER_INFO = {
    "age": "30代",
    "job": "看護師(夜勤あり)、産後1年",
    "concerns": "顔のむくみ、肌のたるみ、目の下のクマ",
    "history": "なし(3人目出産後)",
}

print("🧪 「検討」パターン フル動作テスト")
print("=" * 60)
print(f"店舗: 吉祥寺")
print(f"ハリザーブの名前: 【テスト】松崎 未来")
print(f"施術日: {date.today()}")
print(f"契約結果: 検討")
print(f"お客様情報: {CUSTOMER_INFO}")
print("=" * 60)
print()

# 1) Gemini評価
print("⏳ Gemini Flash 2.5 で評価中...")
result = coaching_analyzer.call_gemini(
    DUMMY_TRANSCRIPT, "【テスト】松崎 未来", date.today(),
    customer_info=CUSTOMER_INFO,
    contract="検討", course="—", store="吉祥寺",
)
result["transcript"] = DUMMY_TRANSCRIPT
result["contract"] = "検討"
result["course"] = "—"
result["store"] = "吉祥寺"
result["questions"] = "検討中で帰られた方への次回フォロー、LINEでどう追客すれば良いか教えてください"
result["customer_info"] = CUSTOMER_INFO

scores = result.get("scores", {})
print(f"\n📊 評価スコア:")
print(f"   ヒアリング: ★{scores.get('hearing', 0)}/5")
print(f"   提案:       ★{scores.get('proposal', 0)}/5")
print(f"   クロージング: ★{scores.get('closing', 0)}/5")
print(f"   トーン:     ★{scores.get('tone', 0)}/5")

print(f"\n🌿 振り返り要約:")
print(result.get("session_summary", "(なし)"))

print(f"\n☘️ 良かった点:")
print(result.get("good_points", "(なし)"))

print(f"\n🍃 改善点:")
print(result.get("improvements", "(なし)"))

# 2) Slack 通知 (ts/permalink を取得)
print("\n⏳ Slack に通知中...")
slack_meta = coaching_analyzer.send_slack_notifications(
    "【テスト】松崎 未来", date.today(), result
) or {}
print(f"✅ Slack 投稿成功")
print(f"   ts: {slack_meta.get('ts')}")
print(f"   permalink: {slack_meta.get('permalink')}")
result["slack_ts"] = slack_meta.get("ts", "")
result["slack_permalink"] = slack_meta.get("permalink", "")

# 3) Notion 保存
print("\n⏳ Notion に保存中...")
url = coaching_analyzer.save_to_notion(
    "【テスト】松崎 未来", date.today(), result
)
print(f"✅ Notion保存完了 → {url}")
print(f"\n👉 Slack のスレッドに何か返信してから次のコマンドで同期テスト:")
print(f"   python3 scripts/sync_leader_fb.py")
