"""add_hearing_checklist_property.py
既存のNotion DB「🪡 ハリナチュレ育成FB履歴」に
「ヒアリング達成数(number)」「ヒアリングチェック(rich_text)」プロパティを追加

実行方法:
  cd /Users/user/projects/harinature-fb-agent
  NOTION_TOKEN=ntn_xxx python3 scripts/add_hearing_checklist_property.py
"""

import os
import sys
import json
import requests

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
DB_ID = "36daf68b-7a63-8126-b7c1-f2b4328cd8b2"

if not NOTION_TOKEN:
    print("❌ NOTION_TOKEN が未設定")
    sys.exit(1)

H = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

payload = {
    "properties": {
        "ヒアリング達成数": {"number": {"format": "number"}},
        "ヒアリングチェック": {"rich_text": {}},
    }
}

print(f"🔧 DB {DB_ID} にプロパティ追加中...")
r = requests.patch(
    f"https://api.notion.com/v1/databases/{DB_ID}",
    headers=H,
    json=payload,
    timeout=30,
)

if r.status_code == 200:
    print("✅ プロパティ追加成功")
    print("   - ヒアリング達成数 (number)")
    print("   - ヒアリングチェック (rich_text)")
else:
    print(f"❌ 失敗 ({r.status_code})")
    print(json.dumps(r.json(), ensure_ascii=False, indent=2))
    sys.exit(1)
