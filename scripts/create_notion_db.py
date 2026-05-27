"""create_notion_db.py - Notion に「🪡 ハリナチュレ育成FB履歴」DB を新規作成

親ページ: 📋 まつざき秘書ノート (ID: 34eaf68b-7a63-80ea-afce-ea320e107e19)

実行方法:
  cd /Users/user/projects/harinature-fb-agent
  NOTION_TOKEN=ntn_xxx python3 scripts/create_notion_db.py
"""

import json
import os
import sys
import requests

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
PARENT_PAGE_ID = "34eaf68b-7a63-80ea-afce-ea320e107e19"
DB_NAME = "🪡 ハリナチュレ育成FB履歴"

STORE_OPTIONS = [
    "吉祥寺", "錦糸町", "新宿", "日吉", "梅田", "横浜駅前", "神戸元町",
    "大宮", "那覇", "西心斎橋", "北千住", "五反田", "札幌", "池袋",
    "町田", "名古屋", "南流山", "博多", "高崎",
]
COURSE_OPTIONS = [
    "—", "サブスク 月2回", "サブスク 月3回", "サブスク 月4回",
    "美容特化 月3回", "トライアル", "次回予約(HPB)",
]
AGE_OPTIONS = ["10代", "20代", "30代", "40代", "50代", "60代", "70代以上", "—"]
CONTRACT_OPTIONS = ["あり", "なし"]

if not NOTION_TOKEN:
    print("NOTION_TOKEN が未設定です")
    sys.exit(1)

H = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def _select_options(names, color="default"):
    return [{"name": n, "color": color} for n in names]


payload = {
    "parent": {"type": "page_id", "page_id": PARENT_PAGE_ID},
    "icon": {"type": "emoji", "emoji": "🪡"},
    "title": [{"type": "text", "text": {"content": DB_NAME}}],
    "properties": {
        "スタッフ名": {"title": {}},
        "セッション日": {"date": {}},
        "店舗": {"select": {"options": _select_options(STORE_OPTIONS, "green")}},
        "契約結果": {"select": {"options": [
            {"name": "あり", "color": "green"},
            {"name": "なし", "color": "gray"},
        ]}},
        "コース": {"select": {"options": _select_options(COURSE_OPTIONS, "default")}},
        "年齢": {"select": {"options": _select_options(AGE_OPTIONS, "default")}},
        "仕事": {"rich_text": {}},
        "悩み": {"rich_text": {}},
        "既往歴": {"rich_text": {}},
        "ヒアリング★": {"number": {"format": "number"}},
        "提案★": {"number": {"format": "number"}},
        "クロージング★": {"number": {"format": "number"}},
        "トーン★": {"number": {"format": "number"}},
        "平均★": {"number": {"format": "number"}},
        "振り返り要約": {"rich_text": {}},
        "良かった点": {"rich_text": {}},
        "改善点": {"rich_text": {}},
        "疑問点": {"rich_text": {}},
        "文字起こし全文": {"rich_text": {}},
    },
}

print(f"🪡 Notion DB「{DB_NAME}」を作成中...")
r = requests.post("https://api.notion.com/v1/databases", headers=H, json=payload, timeout=30)
if r.status_code == 200:
    data = r.json()
    db_id = data.get("id", "")
    url = data.get("url", "")
    print(f"\n✅ 作成成功")
    print(f"   DB ID: {db_id}")
    print(f"   URL: {url}")
    print(f"\n👉 この DB ID を NOTION_FB_HISTORY_DB_ID として Secrets に登録してね")
else:
    print(f"\n❌ 作成失敗 ({r.status_code})")
    print(json.dumps(r.json(), ensure_ascii=False, indent=2))
    sys.exit(1)
