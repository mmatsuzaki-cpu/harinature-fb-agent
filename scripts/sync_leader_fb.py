"""sync_leader_fb.py - Slackスレッド返信 → Notion「リーダーFB」フィールドに自動同期

【処理フロー】
1. Notion DB「🪡 ハリナチュレ育成FB履歴」から、過去14日以内のページを取得
2. 各ページの「Slack ts」を見て、Slack の conversations.replies API でスレッド返信取得
3. 親メッセージ(Bot自身)を除いた返信のみを「リーダーFB」フィールドに上書き保存
4. 「リーダーFB最終同期」フィールドに同期日時を記録

【実行】
ローカル:
  NOTION_TOKEN=xxx NOTION_FB_HISTORY_DB_ID=xxx SLACK_BOT_TOKEN=xxx \\
    SLACK_FEEDBACK_CHANNEL_ID=C0B1WQ495EV python3 scripts/sync_leader_fb.py

GitHub Actions:
  毎日 10:00 JST に自動実行(.github/workflows/sync_leader_fb.yml)
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import requests

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_FB_HISTORY_DB_ID = os.environ.get("NOTION_FB_HISTORY_DB_ID", "")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_FEEDBACK_CHANNEL_ID = os.environ.get("SLACK_FEEDBACK_CHANNEL_ID", "C0B1WQ495EV")

# 過去何日分のページを対象にするか(古いページはスレ閉まってる前提でスキップ)
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "14"))

if not all([NOTION_TOKEN, NOTION_FB_HISTORY_DB_ID, SLACK_BOT_TOKEN]):
    print("❌ NOTION_TOKEN / NOTION_FB_HISTORY_DB_ID / SLACK_BOT_TOKEN いずれか未設定")
    sys.exit(1)

NH = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}
SH = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)


def fetch_target_pages():
    """同期対象ページを Notion から取得(過去 LOOKBACK_DAYS 日以内 & Slack ts ありのもの)"""
    cutoff = (NOW - timedelta(days=LOOKBACK_DAYS)).date().isoformat()
    payload = {
        "filter": {
            "and": [
                {"property": "セッション日", "date": {"on_or_after": cutoff}},
                {"property": "Slack ts", "rich_text": {"is_not_empty": True}},
            ]
        },
        "page_size": 100,
    }
    pages = []
    has_more = True
    cursor = None
    while has_more:
        if cursor:
            payload["start_cursor"] = cursor
        r = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_FB_HISTORY_DB_ID.replace('-', '')}/query",
            headers=NH, json=payload, timeout=30,
        )
        if r.status_code != 200:
            print(f"❌ Notion query failed ({r.status_code}): {r.text[:300]}")
            sys.exit(1)
        data = r.json()
        pages.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        cursor = data.get("next_cursor")
    return pages


def get_thread_replies(ts: str) -> list:
    """Slack のスレッド返信を取得(親メッセージは除く)"""
    if not ts:
        return []
    r = requests.get(
        "https://slack.com/api/conversations.replies",
        headers=SH,
        params={"channel": SLACK_FEEDBACK_CHANNEL_ID, "ts": ts, "limit": 50},
        timeout=30,
    )
    data = r.json()
    if not data.get("ok"):
        return []
    msgs = data.get("messages", [])
    # 1件目は親メッセージなので除外
    return msgs[1:] if len(msgs) > 1 else []


# Slack ユーザーID → 表示名のキャッシュ(API節約)
_user_cache: dict = {}

def get_user_name(user_id: str) -> str:
    if not user_id:
        return "(不明)"
    if user_id in _user_cache:
        return _user_cache[user_id]
    r = requests.get(
        "https://slack.com/api/users.info",
        headers=SH, params={"user": user_id}, timeout=15,
    )
    data = r.json()
    if data.get("ok"):
        u = data["user"]
        name = (u.get("profile", {}).get("display_name")
                or u.get("real_name")
                or u.get("name") or user_id)
    else:
        name = user_id
    _user_cache[user_id] = name
    return name


def format_replies(replies: list) -> str:
    """スレッド返信を Notion 用テキストに整形"""
    if not replies:
        return ""
    lines = []
    for m in replies:
        # Bot 自身(=Bot招待されたAI投稿元の同じBot)の返信もスキップ
        # ただし「リーダーが共有用に追加投稿した」場合は含める判断が難しい
        # → bot_id を持つメッセージは全てスキップ(リーダー=人間の発言のみ拾う)
        if m.get("bot_id") or m.get("subtype") == "bot_message":
            continue
        user_id = m.get("user", "")
        name = get_user_name(user_id)
        ts_str = m.get("ts", "")
        try:
            dt = datetime.fromtimestamp(float(ts_str), JST).strftime("%m/%d %H:%M")
        except Exception:
            dt = ""
        text = (m.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"【{name} {dt}】\n{text}")
    return "\n\n".join(lines)


def update_notion_page(page_id: str, leader_fb_text: str):
    """Notion ページの「リーダーFB」と「リーダーFB最終同期」を更新"""
    sync_iso = NOW.isoformat()
    props = {
        "リーダーFB最終同期": {"date": {"start": sync_iso}},
    }
    # リーダーFB は2000文字制限
    props["リーダーFB"] = {"rich_text": [
        {"type": "text", "text": {"content": leader_fb_text[:2000]}}
    ]} if leader_fb_text else {"rich_text": []}

    r = requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=NH, json={"properties": props}, timeout=30,
    )
    return r.status_code == 200, r.text[:300] if r.status_code != 200 else ""


def main():
    print(f"🪡 リーダーFB同期開始 ({NOW.isoformat()})")
    pages = fetch_target_pages()
    print(f"   対象ページ: {len(pages)} 件 (過去{LOOKBACK_DAYS}日以内)")

    updated = 0
    skipped = 0
    failed = 0
    for p in pages:
        page_id = p["id"]
        props = p.get("properties", {})
        # スタッフ名(title)
        title_arr = props.get("スタッフ名", {}).get("title", [])
        staff = "".join(t.get("plain_text", "") for t in title_arr) or "(無名)"
        # Slack ts
        ts_arr = props.get("Slack ts", {}).get("rich_text", [])
        ts = "".join(t.get("plain_text", "") for t in ts_arr).strip()
        if not ts:
            skipped += 1
            continue

        replies = get_thread_replies(ts)
        leader_fb_text = format_replies(replies)
        ok, err = update_notion_page(page_id, leader_fb_text)
        if ok:
            updated += 1
            n_replies = len([r for r in replies if not r.get("bot_id")])
            print(f"   ✓ {staff}: {n_replies}件のリーダーFB同期")
        else:
            failed += 1
            print(f"   ✗ {staff}: 更新失敗 {err}")

    print(f"\n✅ 完了: 更新{updated} / スキップ{skipped} / 失敗{failed}")


if __name__ == "__main__":
    main()
