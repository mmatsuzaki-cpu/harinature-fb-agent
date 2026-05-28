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


# ── 1. AI評価 + FB生成(Gemini Flash 音声入力ネイティブ) ──

EVAL_PROMPT_TEMPLATE = """あなたは定額制の美容鍼サロン「HARI NATURE」の教育担当として、
添付された新人スタッフの新規カウンセリング録音を直接聴いて評価します。

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
- 契約「なし」の場合 → 「失注分析視点」(7つの感のどれが弱かったか/危機感トークの不足/「他でもいい」フレーズの欠如/3ヶ月提案の言い切り不足/入会金無料の伝え方タイミング)

【FB生成時の必須チェック】
- 「7つの感」のどれが弱かったかを必ず1つ以上指摘
- 危機感トーク・3ヶ月提案・入会金無料トークが入っていたか言及
- 「ハリナチュレじゃなくてもいい」フレーズが入っていたか確認
- 改善提案は上記スクリプトをベースに、お客様の状況に合わせてパーソナライズ

【処理手順】
1. 添付の音声ファイルを最初から最後まで聴いて、日本語で文字起こし
2. その文字起こしに基づいて評価項目4軸を採点
3. 振り返り要約・良かった点・改善点を生成
4. 全てを下記JSONで一度に出力

【出力形式(JSON厳守)】
{{
  "transcript": "<音声全体を日本語で正確に文字起こし(発話者の区別不要・段落分け推奨)>",
  "scores": {{"hearing": <int>, "proposal": <int>, "closing": <int>, "tone": <int>}},
  "session_summary": "<カウンセリング録音の要約(お客様の年齢/職業/主訴/提案内容/お客様の反応の流れを箇条書きで200〜400字程度・マークダウン)>",
  "good_points": "<良かったポイントを具体的に3つ箇条書き(マークダウン)。7つの感のどれが機能していたか言及>",
  "improvements": "<改善点を具体的に2つ箇条書き(マークダウン)。7つの感・危機感トーク・3ヶ月提案・入会金無料・「他でもいい」フレーズのどれが不足していたかを必ず指摘し、松崎の上記スクリプトを引用しながらパーソナライズした改善案を提示>"
}}

JSONのみ出力。コメントや説明は不要。
"""


def fetch_leader_fb_examples(n: int = 3) -> str:
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


def call_gemini_with_audio(audio_path: str, staff_name: str, session_date,
                           customer_info: dict = None,
                           contract: str = "なし", course: str = "—", store: str = "") -> dict:
    """Gemini Flash 2.5 に音声ファイルを直接渡して、
    文字起こし + 評価 + FB生成 を1リクエストで完結する。
    faster-whisper を介さないので大幅高速化。
    """
    import time
    import google.generativeai as genai
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 未設定")
    genai.configure(api_key=GEMINI_API_KEY)

    # ── ① 音声ファイルを Gemini File API にアップロード ──
    uploaded = genai.upload_file(path=audio_path)
    # ファイルが ACTIVE になるまで待機(通常 数秒)
    for _ in range(60):
        if uploaded.state.name == "ACTIVE":
            break
        if uploaded.state.name == "FAILED":
            raise RuntimeError("Gemini File アップロード失敗")
        time.sleep(2)
        uploaded = genai.get_file(uploaded.name)
    else:
        raise RuntimeError("Gemini File アップロード タイムアウト(120秒)")

    # ── ② プロンプト組み立て ──
    customer_info = customer_info or {}
    leader_fb = fetch_leader_fb_examples()
    contract_status = "🎉 契約獲得" if contract == "あり" else "🥲 契約なし(失注)"
    course_label = course if (contract == "あり" and course not in ("", "—", None)) else "(未入会)"
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
        leader_fb_examples=leader_fb,
    )

    # ── ③ Gemini 呼び出し(音声 + プロンプト) - 429リトライ対応 ──
    model = genai.GenerativeModel("gemini-2.5-flash")
    last_error = None
    response = None
    for attempt in range(4):
        try:
            response = model.generate_content(
                [uploaded, prompt],
                generation_config={
                    "temperature": 0.2,
                    "response_mime_type": "application/json",
                },
                request_options={"timeout": 600},  # 10分タイムアウト
            )
            break
        except Exception as e:
            last_error = e
            err_str = str(e)
            # 429 quota error は自動リトライ(最大3回)
            if "429" in err_str or "quota" in err_str.lower() or "ResourceExhausted" in err_str:
                if attempt >= 3:
                    raise RuntimeError(
                        f"Gemini APIレート制限が続いています💦 1分後にもう一度試してね\n"
                        f"詳細: {err_str[:200]}"
                    )
                # retry_delay秒数を抽出(なければ40秒)
                wait_match = re.search(r"retry[_\s]*delay[^\d]*(\d+)", err_str)
                wait = int(wait_match.group(1)) + 5 if wait_match else 40
                time.sleep(wait)
                continue
            # その他のエラーは即fail
            raise
    if response is None:
        raise RuntimeError(f"Gemini呼び出し失敗: {last_error}")

    # ── ④ ファイル削除(個人情報保護: Gemini側にも残さない) ──
    try:
        genai.delete_file(uploaded.name)
    except Exception:
        pass

    # ── ⑤ JSON パース ──
    text = response.text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini JSON parse失敗: {e}\nresponse: {text[:500]}")


# ── 3. Slack通知 ──────────────────────────────────

def send_slack_notifications(staff_name: str, session_date, result: dict) -> dict:
    """Slack に通知:
    ① #ハリナチュレ_新規振り返り チャンネル投稿(全員見れる)
    ② 松崎さん完了通知DM
    返り値: {"ts": "1234567890.123456", "permalink": "https://..."}
            (リーダーFB同期スクリプトが後でスレッド返信を引っ張ってくる用)
    """
    import requests
    if not SLACK_BOT_TOKEN:
        return {}
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
    post_res = requests.post(
        "https://slack.com/api/chat.postMessage", headers=H,
        json={"channel": SLACK_FEEDBACK_CHANNEL_ID, "text": channel_msg},
    ).json()
    ts = post_res.get("ts", "")
    permalink = ""
    if ts:
        pl_res = requests.get(
            "https://slack.com/api/chat.getPermalink",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
            params={"channel": SLACK_FEEDBACK_CHANNEL_ID, "message_ts": ts},
        ).json()
        permalink = pl_res.get("permalink", "")

    if SLACK_OWNER_USER_ID:
        dm_open = requests.post("https://slack.com/api/conversations.open",
                                headers=H, json={"users": SLACK_OWNER_USER_ID}).json()
        if dm_open.get("ok"):
            dm_id = dm_open["channel"]["id"]
            requests.post("https://slack.com/api/chat.postMessage", headers=H,
                          json={"channel": dm_id,
                                "text": f"✅ *ハリナチュレ育成FB処理完了*\n{staff_name} さん({session_date})の評価が #ハリナチュレ_新規振り返り に投稿されました🪡"})

    return {"ts": ts, "permalink": permalink}


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
    slack_ts = result.get("slack_ts", "")
    slack_permalink = result.get("slack_permalink", "")

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
        "Slack ts": {"rich_text": _rich_text(slack_ts)},
    }
    if slack_permalink:
        properties["Slackスレッド"] = {"url": slack_permalink}

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
        # Gemini Audio: 文字起こし + 評価を1リクエストで完結
        result = call_gemini_with_audio(tmp_path, staff_name, session_date,
                                        customer_info=customer_info,
                                        contract=contract, course=course, store=store)
        # transcript は Gemini が JSON で返してくる(キー名は "transcript")
        result["contract"] = contract
        result["course"] = course
        result["store"] = store
        result["questions"] = questions
        result["customer_info"] = customer_info or {}

        slack_meta = send_slack_notifications(staff_name, session_date, result) or {}
        result["slack_ts"] = slack_meta.get("ts", "")
        result["slack_permalink"] = slack_meta.get("permalink", "")

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
