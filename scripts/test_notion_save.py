"""test_notion_save.py - ダミーデータで save_to_notion() の動作確認

実行方法:
  cd /Users/user/projects/harinature-fb-agent
  NOTION_TOKEN=ntn_xxx NOTION_FB_HISTORY_DB_ID=xxx python3 scripts/test_notion_save.py
"""

import os
import sys
from datetime import date
from pathlib import Path

# Streamlit が無くても動くようにする(import 時のエラー回避)
sys.modules.setdefault("streamlit", type(sys)("streamlit"))

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coaching import coaching_analyzer

# env からトークン上書き
coaching_analyzer.NOTION_TOKEN = os.environ.get("NOTION_TOKEN", coaching_analyzer.NOTION_TOKEN)
coaching_analyzer.NOTION_FB_HISTORY_DB_ID = os.environ.get(
    "NOTION_FB_HISTORY_DB_ID", coaching_analyzer.NOTION_FB_HISTORY_DB_ID
)

if not coaching_analyzer.NOTION_TOKEN or not coaching_analyzer.NOTION_FB_HISTORY_DB_ID:
    print("❌ NOTION_TOKEN or NOTION_FB_HISTORY_DB_ID 未設定")
    sys.exit(1)

dummy_result = {
    "scores": {"hearing": 4, "proposal": 3, "closing": 2, "tone": 5},
    "session_summary": "**【テスト】** 30代女性、看護師、顔のむくみとたるみの悩み。施術後は爽快感あり、3ヶ月提案するも未入会。",
    "good_points": "- 親近感ある声のトーンで安心感を演出\n- 鍼の説明を丁寧に行い恐怖心を緩和\n- 施術後のBA確認で爽快感を引き出した",
    "improvements": "- **危機感トーク不足**: 「7つの感」の中で危機感の伝え方が弱かった。「このまま放置すると顔のたるみが進行する」など、放置した未来を具体的に伝えるとよい\n- **「ハリナチュレじゃなくてもいい」フレーズなし**: 営業感を消すために必ずセットで言うこと",
    "transcript": "(これはテスト用のダミー文字起こしです)",
    "contract": "なし",
    "course": "—",
    "store": "吉祥寺",
    "questions": "危機感トークがうまく入れられない、タイミング教えてください",
    "customer_info": {
        "age": "30代",
        "job": "看護師(夜勤あり)",
        "concerns": "顔のむくみ、肌のたるみ",
        "history": "なし",
    },
}

print("🧪 Notion保存テスト実行中...")
url = coaching_analyzer.save_to_notion(
    staff_name="【テスト】未来",
    session_date=date.today(),
    result=dummy_result,
)

if url:
    print(f"\n✅ 保存成功")
    print(f"   URL: {url}")
else:
    print("\n❌ 保存失敗 (ログ参照)")
    sys.exit(1)
