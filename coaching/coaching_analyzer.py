"""coaching_analyzer.py - 録音 → 文字起こし → AI評価 → FB生成 (ハリナチュレ版)

【処理フロー】
1. アップロードされた音声を一時保存
2. faster-whisper でローカル文字起こし(オープンソース・無料)
3. Gemini Flash で4項目評価(ヒアリング/提案/クロージング/トーン)+ FB生成
4. Slack(チャンネル投稿 + 松崎完了通知DM)+ Notion保存
5. 一時音声ファイルを削除(個人情報保護)

【依存ライブラリ】
- faster-whisper: 軽量Whisper(モデル "tiny" or "base")
- google-generativeai: Gemini Flash API
"""

import json
import os
import re
import tempfile
from pathlib import Path

# 環境変数読み込み(Streamlit Cloud では st.secrets、ローカルでは .env)
try:
    import streamlit as st
    GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
    NOTION_TOKEN = st.secrets.get("NOTION_TOKEN", "")
    NOTION_LEADER_FB_DB_ID = st.secrets.get("NOTION_LEADER_FB_DB_ID", "")
    NOTION_FB_HISTORY_DB_ID = st.secrets.get("NOTION_FB_HISTORY_DB_ID", "")
    SLACK_BOT_TOKEN = st.secrets.get("SLACK_BOT_TOKEN", "")
    SLACK_FEEDBACK_CHANNEL_ID = st.secrets.get("SLACK_FEEDBACK_CHANNEL_ID", "C0B1WQ495EV")
    SLACK_OWNER_USER_ID = st.secrets.get("SLACK_OWNER_USER_ID", "")
except Exception:
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
    NOTION_LEADER_FB_DB_ID = os.environ.get("NOTION_LEADER_FB_DB_ID", "")
    NOTION_FB_HISTORY_DB_ID = os.environ.get("NOTION_FB_HISTORY_DB_ID", "")
    SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
    SLACK_FEEDBACK_CHANNEL_ID = os.environ.get("SLACK_FEEDBACK_CHANNEL_ID", "C0B1WQ495EV")
    SLACK_OWNER_USER_ID = os.environ.get("SLACK_OWNER_USER_ID", "")


# ── 1. 文字起こし(faster-whisper) ────────────────

def transcribe_audio(audio_path: str) -> str:
    """faster-whisper で音声を文字起こし
    モデルは "base"(74MB、日本語OK、Streamlit Cloud 1GBメモリで動く)
    """
    from faster_whisper import WhisperModel
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, info = model.transcribe(audio_path, language="ja", vad_filter=True)
    text = "".join(seg.text for seg in segments)
    return text.strip()


# ── 2. AI評価 + FB生成(Gemini Flash) ──────────────

EVAL_PROMPT_TEMPLATE = """あなたは定額制の美容鍼サロン「HARI NATURE」の教育担当として、新人スタッフの新規カウンセリング録音を評価します。

【店舗】 {store}
【スタッフ名】 {staff_name}
【セッション日】 {session_date}
【契約結果】 {contract_status}
【コース】 {course_label}

【お客様情報】
- 年齢: {customer_age}
- 仕事: {customer_job}
- 悩み: {customer_concerns}
- 既往歴: {customer_history}

【カウンセリング録音(文字起こし)】
{transcript}

【参考にするリーダーFB事例集(過去類似ケース)】
{leader_fb_examples}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【ハリナチュレの新規対応哲学(評価軸の基礎)】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

■ 根本思想
新規対応で大事なのは「入会＝信頼感」。
お客様は効果ではなく「この人なら任せてもいい」「自分の悩みを理解してくれている」
「このまま放置したらまずいから、ちゃんと始めよう」と思えた時に入会する。
新規対応は施術の60分ではなく「お客様に信頼してもらうための60分」。

■ 7つの感(信頼感を作るフレームワーク)
1. 清潔感: 髪型・爪・服装・匂い・店内環境
2. 安心感: 声のトーン・話すスピード・鍼への不安への説明
3. 親近感: 「この人わかってくれる」共感
4. 爽快感: 施術後の体感を一緒に言語化
5. 満足感: 期待値超え
6. 達成感: 鍼が怖い方が「受けきれた」体験
7. 危機感(最重要): 「このまま何もしなかったら悪くなる」「今から何か始めた方がいい」

■ 危機感の伝え方(順番厳守)
悩みを聞く → 原因を一緒に考える → 体の仕組みを説明 →
放置した場合の未来を伝える → 「何かしら始めた方がいい」と伝える

■ 「ハリナチュレじゃなくてもいい」テク(営業感を消す)
危機感を伝える時に必ずセットで:
- 「ハリナチュレじゃなくても大丈夫」
- 「美容医療でもいい」
- 「何かしら始めた方がいい」

■ 悩み+目的を聞く
悩みだけでなく、その先の目的まで聞く。
例:「むくみが改善されたら、その先にこうなりたいみたいな目的ってありますか？」

■ 3ヶ月提案(クロージング鉄板スクリプト)
「美容鍼は合う方と合わない方がいます。今日1回では判断できないので、
一度3ヶ月だけ続けてみるのがすごく良いと思います。
3ヶ月後に中間カウンセリングも入らせていただきます。
まずは3ヶ月だけ、僕(私)に任せてもらえませんか？」

■ 入会金無料の伝え方(最後にお得情報として)
最初から押さない。「やりたい」「必要だ」「任せたい」と思ってもらってから:
「本日ご入会の場合は入会金が0円になります。
今日の施術料金も0円になるので、かなりお得に始めていただけます。」

■ 最低限意識すべき3つ(完璧じゃなくてOK)
1. 悩みだけで終わらず、その悩みの原因まで説明する
2. このまま何もしなかった場合の危機感を伝える
3. 「ハリナチュレじゃなくてもいいので、何かしら始めた方がいい」と伝える

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【評価項目(各1〜5の★スコア)】
1. ヒアリング: 7つの感の中の「親近感・安心感」+ お悩み深掘り(悩み+目的+原因まで聞けているか)、体の状態理解
2. 提案: 美容鍼・経絡ケア・お肌診断の価値訴求、危機感トーク(放置した未来を伝える)、「ハリナチュレじゃなくてもいい」フレーズ、3ヶ月提案
3. クロージング: 「3ヶ月だけ任せてもらえませんか」スクリプト、入会金無料の伝え方(最後にお得情報として)、契約決断サポート
4. トーン: 寄り添い方、話し方、聞きやすさ、鍼への不安への配慮

【FB視点の使い分け】
- 契約「あり」の場合 → 「定着サポート視点」(継続モチベ・次回ゴール・3ヶ月後の中間カウンセリングへの繋ぎ方)
- 契約「なし」の場合 → 「失注分析視点」(7つの感のどれが弱かったか/危機感トークの不足/「他でもいい」フレーズの欠如)

【FB生成時の必須チェック】
- 「7つの感」のどれが弱かったかを必ず1つ以上指摘
- 危機感トーク・3ヶ月提案・入会金無料トークが入っていたか言及
- 「ハリナチュレじゃなくてもいい」フレーズが入っていたか確認
- 改善提案は上記スクリプトをベースに、お客様の状況に合わせてパーソナライズ

【出力形式(JSON厳守)】
{{
  "scores": {{"hearing": <int>, "proposal": <int>, "closing": <int>, "tone": <int>}},
  "session_summary": "<カウンセリング録音の要約(お客様の年齢/職業/主訴/提案内容/お客様の反応の流れを箇条書きで200〜400字程度・マークダウン)>",
  "good_points": "<良かったポイントを具体的に3つ箇条書き(マークダウン)。7つの感のどれが機能していたか言及>",
  "improvements": "<改善点を具体的に2つ箇条書き(マークダウン)。7つの感・危機感トーク・3ヶ月提案・入会金無料・「他でもいい」フレーズのどれが不足していたかを必ず指摘し、松崎の上記スクリプトを引用しながらパーソナライズした改善案を提示>"
}}

JSONのみ出力。コメントや説明は不要。
"""


def fetch_leader_fb_examples(transcript: str, n: int = 3) -> str:
    """Notion リーダーFB事例集から類似ケースを取得して要約"""
    if not NOTION_TOKEN or not NOTION_LEADER_FB_DB_ID:
        return "(リーダーFB事例なし)"
    try:
        import requests
        H = {
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }
        r = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_LEADER_FB_DB_ID.replace('-', '')}/query",
            headers=H,
            json={"page_size": n, "sorts": [{"timestamp": "created_time", "direction": "descending"}]},
        )
        examples = []
        for p in r.json().get("results", [])[:n]:
            props = p.get("properties", {})
            situation = "".join([t.get("plain_text", "") for t in props.get("状況", {}).get("rich_text", [])])
            fb = "".join([t.get("plain_text", "") for t in props.get("FB本文", {}).get("rich_text", [])])
            if situation or fb:
                examples.append(f"・状況: {situation[:100]}\n  FB: {fb[:200]}")
        return "\n\n".join(examples) if examples else "(類似事例なし)"
    except Exception as e:
        return f"(取得失敗: {e})"


def call_gemini(transcript: str, staff_name: str, session_date,
                customer_info: dict = None,
                contract: str = "なし", course: str = "—", store: str = "") -> dict:
    """Gemini Flash で評価生成"""
    import google.generativeai as genai
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 未設定")
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")

    customer_info = customer_info or {}
    leader_fb = fetch_leader_fb_examples(transcript)
    contract_status = f"🎉 契約獲得" if contract == "あり" else "🥲 契約なし(失注)"
    course_label = course if (contract == "あり" and course not in ("", "—", None)) else "(契約なし)"
    prompt = EVAL_PROMPT_TEMPLATE.format(
        store=store or "(未指定)",
        staff_name=staff_name,
        session_date=session_date,
        contract_status=contract_status,
        course_label=course_label,
        customer_age=customer_info.get("age", "(未入力)"),
        customer_job=customer_info.get("job", "(未入力)"),
        customer_concerns=customer_info.get("concerns", "(未入力)"),
        customer_history=customer_info.get("history", "(未入力)"),
        transcript=transcript[:8000],
        leader_fb_examples=leader_fb,
    )

    response = model.generate_content(prompt)
    text = response.text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini JSON parse失敗: {e}\nresponse: {text[:500]}")


# ── 3. Slack通知 ──────────────────────────────────

def send_slack_notifications(staff_name: str, session_date, result: dict):
    """Slack に通知:
    ① #ハリナチュレ_新規振り返り チャンネル投稿(全員見れる)
    ② 松崎さん完了通知DM
    """
    import requests
    if not SLACK_BOT_TOKEN:
        return
    H = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json; charset=utf-8"}

    scores = result.get("scores", {})
    avg = sum(scores.values()) / max(len(scores), 1)
    star_line = f"ヒアリング★{scores.get('hearing',0)} / 提案★{scores.get('proposal',0)} / クロージング★{scores.get('closing',0)} / トーン★{scores.get('tone',0)}"

    contract = result.get("contract", "なし")
    course = result.get("course", "—")
    if contract == "あり" and course not in ("", "—", None):
        contract_line = f"🎉 *契約獲得* ({course})"
    elif contract == "あり":
        contract_line = "🎉 *契約獲得*"
    else:
        contract_line = "🥲 契約なし"

    session_summary = result.get("session_summary", "(要約なし)")

    store = result.get("store", "")
    store_line = f"🏠 {store}店  " if store else ""
    questions = (result.get("questions") or "").strip()
    questions_block = (
        f"\n\n━━━━━━━━━━━━━━\n"
        f"❓ *リーダー/研修担当への疑問点*\n{questions}"
        if questions else ""
    )
    channel_msg = (
        f"🪡 *新規カウンセリング振り返り*\n"
        f"{store_line}👤 {staff_name} さん  📅 {session_date}\n"
        f"{contract_line}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"🌿 *振り返り内容*\n"
        f"{session_summary}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"📊 *評価*  平均★{avg:.1f}/5\n"
        f"{star_line}\n\n"
        f"☘️ *良かった点*\n{result.get('good_points', '')}\n\n"
        f"🍃 *改善点*\n{result.get('improvements', '')}"
        f"{questions_block}"
    )
    requests.post("https://slack.com/api/chat.postMessage", headers=H,
                  json={"channel": SLACK_FEEDBACK_CHANNEL_ID, "text": channel_msg})

    if SLACK_OWNER_USER_ID:
        dm_open = requests.post("https://slack.com/api/conversations.open",
                                headers=H, json={"users": SLACK_OWNER_USER_ID}).json()
        if dm_open.get("ok"):
            dm_id = dm_open["channel"]["id"]
            requests.post("https://slack.com/api/chat.postMessage", headers=H,
                          json={"channel": dm_id,
                                "text": f"✅ *ハリナチュレ育成FB処理完了*\n{staff_name} さん({session_date})の評価が #ハリナチュレ_新規振り返り に投稿されました🪡"})


# ── 4. Notion 蓄積 ────────────────────────────────

def _rich_text(content: str, max_len: int = 2000) -> list:
    """Notion rich_text 形式に変換(2000文字制限あり)"""
    if not content:
        return []
    return [{"type": "text", "text": {"content": str(content)[:max_len]}}]


def save_to_notion(staff_name: str, session_date, result: dict) -> str:
    """評価結果を Notion DB「🪡 ハリナチュレ育成FB履歴」に保存
    返り値: 作成したページURL(失敗時は空文字)
    """
    if not NOTION_TOKEN or not NOTION_FB_HISTORY_DB_ID:
        return ""

    import requests
    H = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    scores = result.get("scores", {})
    hearing = int(scores.get("hearing", 0))
    proposal = int(scores.get("proposal", 0))
    closing = int(scores.get("closing", 0))
    tone = int(scores.get("tone", 0))
    avg = round((hearing + proposal + closing + tone) / 4, 2) if any([hearing, proposal, closing, tone]) else 0

    customer_info = result.get("customer_info") or {}
    age = customer_info.get("age", "—")
    job = customer_info.get("job", "")
    concerns = customer_info.get("concerns", "")
    history = customer_info.get("history", "")

    contract = result.get("contract", "なし")
    course = result.get("course", "—") or "—"
    store = result.get("store", "")
    questions = result.get("questions", "")
    transcript = result.get("transcript", "")
    summary = result.get("session_summary", "")
    good_points = result.get("good_points", "")
    improvements = result.get("improvements", "")

    if hasattr(session_date, "isoformat"):
        date_str = session_date.isoformat()
    else:
        date_str = str(session_date)

    properties = {
        "スタッフ名": {"title": [{"type": "text", "text": {"content": staff_name}}]},
        "セッション日": {"date": {"start": date_str}},
        "ヒアリング★": {"number": hearing},
        "提案★": {"number": proposal},
        "クロージング★": {"number": closing},
        "トーン★": {"number": tone},
        "平均★": {"number": avg},
        "仕事": {"rich_text": _rich_text(job)},
        "悩み": {"rich_text": _rich_text(concerns)},
        "既往歴": {"rich_text": _rich_text(history)},
        "振り返り要約": {"rich_text": _rich_text(summary)},
        "良かった点": {"rich_text": _rich_text(good_points)},
        "改善点": {"rich_text": _rich_text(improvements)},
        "疑問点": {"rich_text": _rich_text(questions)},
        "文字起こし全文": {"rich_text": _rich_text(transcript)},
    }

    if store:
        properties["店舗"] = {"select": {"name": store}}
    if contract:
        properties["契約結果"] = {"select": {"name": contract}}
    if course and course != "":
        properties["コース"] = {"select": {"name": course}}
    if age and age != "":
        properties["年齢"] = {"select": {"name": age}}

    payload = {
        "parent": {"database_id": NOTION_FB_HISTORY_DB_ID},
        "properties": properties,
    }

    try:
        r = requests.post("https://api.notion.com/v1/pages", headers=H, json=payload, timeout=30)
        if r.status_code == 200:
            return r.json().get("url", "")
        else:
            print(f"[Notion保存失敗] {r.status_code}: {r.text[:300]}")
            return ""
    except Exception as e:
        print(f"[Notion保存例外] {e}")
        return ""


# ── メイン関数 ────────────────────────────────────

def analyze_session(audio_file, staff_name: str, session_date,
                    customer_info: dict = None,
                    contract: str = "なし", course: str = "—", store: str = "",
                    questions: str = "") -> dict:
    """Streamlit から呼ばれるメインエントリ
    audio_file: streamlit UploadedFile
    customer_info: お客様情報 dict (age / job / concerns / history)
    contract: 契約結果("あり" / "なし")
    course: コース名(サブスク月X回 / 美容特化月3 / トライアル / 次回予約HPB / —)
    store: 店舗(19店舗のいずれか)
    questions: スタッフからの疑問点(任意・リーダー/研修担当に共有)
    """
    suffix = "." + audio_file.name.rsplit(".", 1)[-1]
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_file.read())
        tmp_path = tmp.name

    try:
        transcript = transcribe_audio(tmp_path)

        result = call_gemini(transcript, staff_name, session_date,
                             customer_info=customer_info,
                             contract=contract, course=course, store=store)
        result["transcript"] = transcript
        result["contract"] = contract
        result["course"] = course
        result["store"] = store
        result["questions"] = questions
        result["customer_info"] = customer_info or {}

        send_slack_notifications(staff_name, session_date, result)

        notion_url = save_to_notion(staff_name, session_date, result)
        if notion_url:
            result["notion_url"] = notion_url

        return result
    finally:
        # 個人情報保護: 音声ファイル即削除
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
