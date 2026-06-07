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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# 並列文字起こしの設定(Tier 1 + 暴走対策)
# 戦略:
#   - 5分チャンクで細かく分割(長尺音声でのモデル暴走/無限ループを防止)
#   - 各チャンクは max_output_tokens で出力上限を設定
#   - チャンク文字起こし → テキスト評価 の2段構えで安定化
CHUNK_MINUTES = 5   # 1チャンクの長さ(分) ※短くしてループ暴走防止
MAX_PARALLEL_WORKERS = 4  # 同時並列リクエスト数(Tier 1)
CHUNK_STAGGER_SECONDS = 2  # チャンク投入の時間差(秒)
SINGLE_FILE_SIZE_LIMIT_MB = 8  # これ以下のみ一発処理(長尺は必ずチャンク分割)
# 1チャンク(5分)の文字起こし上限トークン(暴走時の保険)
CHUNK_MAX_OUTPUT_TOKENS = 8000

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

※ お客様情報(年齢/仕事/悩み/既往歴)は録音から自動で読み取って評価に活かしてください

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
【ハリナチュレ 新規ヒアリング必須16項目】※ ヒアリング軸の評価基準
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

下記16項目を「聞けたか/触れたか」をチェックし、各項目を true/false で判定する。
ヒアリング★スコアは このチェック達成数 + 深掘りの質 で決定する。

【悩みヒアリング3段階】※ 必ず順番に深掘り
1. 悩みトップ3: お客様の悩みを3つ引き出せたか
2. 最優先深掘り: その3つの中で最優先の悩みを「原因」「体の仕組み」「放置した未来」まで深掘りしたか
3. 目的目標: その悩みの「先にある目的・目標」(例: 写真で気にせず笑いたい / 自信を取り戻したい等)を聞き出せたか

【ライフスタイル12項目】
4. 仕事: 職業・働き方・勤務時間など
5. 食事: 普段の食生活・偏り・自炊外食
6. アルコール: 飲酒頻度・量
7. 水分: 1日の水分摂取量
8. 睡眠: 睡眠時間・質・寝つき
9. 運動: 運動習慣の有無・頻度
10. 歩数: 1日の歩数・日常の活動量
11. 体重増減: 最近の体重変化・産後変化
12. お風呂: 入浴習慣(湯船 or シャワーのみ)
13. 既往歴: 既往症・体質・服薬
14. セルフケア: スキンケア・マッサージなど自宅ケア
15. 美容医療: 美容医療経験・他サロン併用状況

【提案統合】
16. プランニング: お客様の目標・3ヶ月/半年/1年後の理想像をヒアリングし、その達成に向けて鍼サロンとしてどう寄り添うかを一緒に組み立てたか

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【評価項目(各1〜5の★スコア)】
1. ヒアリング: 【上記16項目チェック達成数】+ 7つの感(親近感・安心感)+ 悩み深掘りの質、体の状態理解
   - 14-16個達成 → ★5
   - 11-13個達成 → ★4
   - 8-10個達成 → ★3
   - 5-7個達成 → ★2
   - 0-4個達成 → ★1
2. 提案: 美容鍼・経絡ケア・お肌診断の価値訴求、危機感トーク(放置した未来を伝える)、「ハリナチュレじゃなくてもいい」フレーズ、3ヶ月提案
3. クロージング: 「3ヶ月だけ任せてもらえませんか」スクリプト、入会金無料の伝え方(最後にお得情報として)、契約決断サポート
4. トーン: 寄り添い方、話し方、聞きやすさ、鍼への不安への配慮

【FB視点の使い分け】
- 契約「あり」の場合 → 「定着サポート視点」(継続モチベ・次回ゴール・3ヶ月後の中間カウンセリングへの繋ぎ方)
- 契約「なし」の場合 → 「失注分析視点」(7つの感のどれが弱かったか/危機感トークの不足/「他でもいい」フレーズの欠如/3ヶ月提案の言い切り不足/入会金無料の伝え方タイミング)

【FB生成時の必須チェック】
- ヒアリング14項目のうち「聞けてなかった項目」を必ず明示し、次回ヒアリングで聞くよう促す
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
  "customer_info": {{
    "age": "<音声から推定したお客様の年齢層 (10代/20代/30代/40代/50代/60代/70代以上/不明)>",
    "job": "<音声から聞き取ったお客様の仕事内容(分からなければ「不明」)>",
    "concerns": "<お客様が話していた悩み・主訴を箇条書き>",
    "history": "<お客様が話していた既往歴・体質(なければ「特記なし」)>"
  }},
  "hearing_checklist": {{
    "悩みトップ3": <true|false>,
    "最優先深掘り": <true|false>,
    "目的目標": <true|false>,
    "仕事": <true|false>,
    "食事": <true|false>,
    "アルコール": <true|false>,
    "水分": <true|false>,
    "睡眠": <true|false>,
    "運動": <true|false>,
    "歩数": <true|false>,
    "体重増減": <true|false>,
    "お風呂": <true|false>,
    "既往歴": <true|false>,
    "セルフケア": <true|false>,
    "美容医療": <true|false>,
    "プランニング": <true|false>
  }},
  "scores": {{"hearing": <int>, "proposal": <int>, "closing": <int>, "tone": <int>}},
  "session_summary": "<カウンセリング録音の要約(お客様の年齢/職業/主訴/提案内容/お客様の反応の流れを箇条書きで200〜400字程度・マークダウン)>",
  "good_points": "<良かったポイントを具体的に3つ箇条書き(マークダウン)。7つの感のどれが機能していたか言及>",
  "improvements": "<改善点を具体的に2つ箇条書き(マークダウン)。聞けなかったヒアリング項目を必ず先頭に列挙し、次回どう聞くかを具体例で示す。続けて7つの感・危機感トーク・3ヶ月提案・入会金無料・「他でもいい」フレーズのどれが不足していたかを必ず指摘し、松崎の上記スクリプトを引用しながらパーソナライズした改善案を提示>"
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


# ── 並列文字起こし用ヘルパー ──────────────────────

TRANSCRIBE_PROMPT = """添付の音声を日本語で正確に文字起こししてください。
発話者の区別は不要、自然な改行・段落分けを推奨。
文字起こしのみを返してください(他の説明・タイムコード・話者ラベルは不要)。
重要: 無音・雑音部分では何も書かないこと。同じ文を繰り返さないこと。"""


def _strip_loops(text: str) -> str:
    """モデル暴走で同じフレーズが連続したものを除去
    (例:「はい、HARI NATUREです。」×100回)
    """
    if not text:
        return text
    # 句点・改行で分割して、直前と同じ文が3回以上続いたら以降カット
    parts = re.split(r'(?<=[。\n])', text)
    cleaned = []
    prev = None
    repeat = 0
    for p in parts:
        ps = p.strip()
        if ps and ps == prev:
            repeat += 1
            if repeat >= 2:  # 同じ文が3回目以降はスキップ
                continue
        else:
            repeat = 0
            prev = ps
        cleaned.append(p)
    return "".join(cleaned)


def _gemini_call_with_retry(model, contents, generation_config=None, timeout=600, max_retries=5):
    """Gemini API呼び出し共通関数: 429リトライ対応"""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return model.generate_content(
                contents,
                generation_config=generation_config or {},
                request_options={"timeout": timeout},
            )
        except Exception as e:
            last_error = e
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower() or "ResourceExhausted" in err_str:
                if attempt >= max_retries:
                    raise RuntimeError(
                        f"Gemini APIレート制限が続いています💦 数分後にもう一度試してね\n"
                        f"継続するなら Google AI Studio で Tier 1 にアップグレード推奨\n"
                        f"詳細: {err_str[:200]}"
                    )
                wait_match = re.search(r"retry[_\s]*delay[^\d]*(\d+)", err_str)
                wait = int(wait_match.group(1)) + 5 if wait_match else 65
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"Gemini呼び出し失敗: {last_error}")


def compress_audio_if_large(audio_path: str, target_mb: float = 15.0) -> tuple:
    """ファイルが大きすぎたら ffmpegでビットレート下げて再エンコード
    - 32kbps モノラル AAC は人の声の文字起こしに十分(音楽用ではない)
    - 60分音声 56MB → 約14MB に圧縮
    返り値: (圧縮後パス, 元ファイル削除フラグ)
    """
    import subprocess
    size_mb = os.path.getsize(audio_path) / 1024 / 1024
    if size_mb <= target_mb:
        return audio_path, False

    output_path = f"{audio_path}.compressed.m4a"
    try:
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", audio_path,
            "-b:a", "32k",   # 音声ビットレート 32kbps
            "-ac", "1",      # モノラル化
            "-c:a", "aac",
            output_path,
        ], check=True, capture_output=True, timeout=180)
        new_size = os.path.getsize(output_path) / 1024 / 1024
        print(f"[Compress] {size_mb:.1f}MB → {new_size:.1f}MB (圧縮率 {(1-new_size/size_mb)*100:.0f}%)")
        return output_path, True
    except subprocess.TimeoutExpired:
        print(f"[Compress] タイムアウト、元ファイル使用")
        return audio_path, False
    except subprocess.CalledProcessError as e:
        print(f"[Compress] 失敗、元ファイル使用: {e}")
        return audio_path, False


def split_audio_to_chunks(audio_path: str, chunk_minutes: int = CHUNK_MINUTES) -> list:
    """音声ファイルを指定分数ごとのチャンクに分割
    ffmpeg を subprocess で直接呼ぶ(pydub不要、Python3.13対応)
    -c copy で再エンコードしないので超高速&メモリ消費小
    """
    import subprocess
    # ① 全体長(秒)を ffprobe で取得
    try:
        duration_str = subprocess.check_output([
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            audio_path,
        ], stderr=subprocess.STDOUT).decode().strip()
        duration_sec = float(duration_str)
    except (subprocess.CalledProcessError, ValueError) as e:
        raise RuntimeError(f"音声の長さ取得失敗(ffprobe): {e}")

    chunk_sec = chunk_minutes * 60
    chunks = []
    suffix = Path(audio_path).suffix.lstrip(".") or "m4a"

    chunk_count = int(duration_sec // chunk_sec) + (1 if duration_sec % chunk_sec else 0)
    for i in range(chunk_count):
        start = i * chunk_sec
        chunk_path = f"{audio_path}.chunk_{i:03d}.{suffix}"
        # -c copy: 再エンコードなし(コーデックそのまま、瞬時に分割)
        # -ss を -i の前に置くと高速シーク
        try:
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-ss", str(start),
                "-i", audio_path,
                "-t", str(chunk_sec),
                "-c", "copy",
                chunk_path,
            ], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            # -c copy が失敗した場合(m4a等で再エンコード必要)はフォールバック
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-ss", str(start),
                "-i", audio_path,
                "-t", str(chunk_sec),
                chunk_path,
            ], check=True, capture_output=True)
        chunks.append(chunk_path)
    return chunks


def transcribe_single_chunk(chunk_path: str, chunk_index: int = 0) -> str:
    """単一チャンクを Gemini Audio で文字起こし(並列実行される)"""
    import google.generativeai as genai
    # ① アップロード
    uploaded = genai.upload_file(path=chunk_path)
    for _ in range(60):
        if uploaded.state.name == "ACTIVE":
            break
        if uploaded.state.name == "FAILED":
            raise RuntimeError(f"チャンク{chunk_index}: ファイルアップロード失敗")
        time.sleep(2)
        uploaded = genai.get_file(uploaded.name)
    else:
        raise RuntimeError(f"チャンク{chunk_index}: アップロード タイムアウト")

    # ② 文字起こし(max_output_tokensで暴走時の出力上限を設定)
    model = genai.GenerativeModel("gemini-2.5-flash")
    response = _gemini_call_with_retry(
        model,
        [uploaded, TRANSCRIBE_PROMPT],
        generation_config={
            "temperature": 0.1,
            "max_output_tokens": CHUNK_MAX_OUTPUT_TOKENS,
        },
        timeout=300,
    )

    # ③ ファイル削除
    try:
        genai.delete_file(uploaded.name)
    except Exception:
        pass

    # ④ ループ暴走の除去
    try:
        text = response.text.strip()
    except Exception:
        # finish_reason が MAX_TOKENS 等で .text が取れない場合
        text = ""
        if response.candidates and response.candidates[0].content.parts:
            text = "".join(p.text for p in response.candidates[0].content.parts if hasattr(p, "text")).strip()
    return _strip_loops(text)


def transcribe_audio_parallel(audio_path: str, progress_callback=None) -> dict:
    """音声を分割→並列文字起こし→結合
    二重チェック機構:
      ① 並列実行(第1ラウンド)
      ② 失敗チャンクのみ直列リトライ(第2ラウンド)
      ③ それでも失敗したチャンクは明示マーカーで挿入
    返り値: {"transcript": str, "stats": {...}, "failed_chunks": [...]}
    """
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)

    chunks = split_audio_to_chunks(audio_path)
    chunk_count = len(chunks)
    if progress_callback:
        progress_callback(f"📦 {chunk_count}チャンクに分割完了")

    transcripts = [""] * chunk_count
    failed_first = []

    try:
        # ── 第1ラウンド: 並列実行(時間差スタッガで投入) ──
        completed = 0
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
            future_to_idx = {}
            for i, chunk in enumerate(chunks):
                future_to_idx[executor.submit(transcribe_single_chunk, chunk, i)] = i
                # 時間差投入: quota消費を平準化(2並列目以降のみ)
                if i > 0 and i < len(chunks) - 1:
                    time.sleep(CHUNK_STAGGER_SECONDS)
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    transcripts[idx] = future.result()
                    completed += 1
                    if progress_callback:
                        progress_callback(f"✓ チャンク {completed}/{chunk_count} 完了")
                except Exception as e:
                    failed_first.append(idx)
                    print(f"[Round1] Chunk {idx} failed: {e}")

        # ── 第2ラウンド: 失敗チャンクのみ直列リトライ ──
        failed_final = []
        if failed_first:
            if progress_callback:
                progress_callback(f"🔄 {len(failed_first)}件のチャンクを再試行中...")
            for idx in failed_first:
                try:
                    time.sleep(5)  # quota回復を待つ
                    transcripts[idx] = transcribe_single_chunk(chunks[idx], idx)
                    if progress_callback:
                        progress_callback(f"✓ チャンク {idx+1} リトライ成功")
                except Exception as e:
                    failed_final.append(idx)
                    transcripts[idx] = f"\n[⚠ チャンク{idx+1}: 文字起こし失敗 ({str(e)[:100]})]\n"
                    print(f"[Round2] Chunk {idx} failed: {e}")

        # 結合
        full_transcript = "\n\n".join(t for t in transcripts if t)

        stats = {
            "total_chunks": chunk_count,
            "success_chunks": chunk_count - len(failed_final),
            "failed_chunks": len(failed_final),
            "transcript_length": len(full_transcript),
        }
        return {
            "transcript": full_transcript,
            "stats": stats,
            "failed_chunks": failed_final,
        }
    finally:
        # チャンクファイル削除
        for chunk in chunks:
            try:
                os.unlink(chunk)
            except OSError:
                pass


REQUIRED_FIELDS = ["scores", "session_summary", "good_points", "improvements"]
REQUIRED_SCORES = ["hearing", "proposal", "closing", "tone"]


def _extract_json(text: str) -> str:
    """レスポンステキストからJSON部分を抽出"""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text


def _validate_result(result: dict) -> list:
    """評価結果に必須フィールドが揃っているか確認、欠けているフィールドのリストを返す"""
    missing = []
    for f in REQUIRED_FIELDS:
        if not result.get(f):
            missing.append(f)
    scores = result.get("scores", {})
    for s in REQUIRED_SCORES:
        if s not in scores:
            missing.append(f"scores.{s}")
    return missing


def _salvage_json(text: str) -> dict:
    """壊れたJSON(ループ暴走でtranscriptが途中切れ等)から
    必要フィールドを正規表現で救済抽出する最終手段"""
    result = {}
    # scores 抽出
    sm = re.search(r'"scores"\s*:\s*\{([^}]*)\}', text)
    if sm:
        scores = {}
        for k in REQUIRED_SCORES:
            km = re.search(rf'"{k}"\s*:\s*(\d+)', sm.group(1))
            if km:
                scores[k] = int(km.group(1))
        if scores:
            result["scores"] = scores
    # 各テキストフィールド抽出(最初の閉じない引用までを緩く)
    for field in ["session_summary", "good_points", "improvements"]:
        fm = re.search(rf'"{field}"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
        if fm:
            result[field] = fm.group(1).replace('\\n', '\n').replace('\\"', '"')
    return result


def _parse_with_retry(model, response, generation_config, original_prompt):
    """JSON パース失敗時に1回だけ再生成を試みる"""
    try:
        text = _extract_json(response.text)
    except Exception:
        text = ""
        if response.candidates and response.candidates[0].content.parts:
            text = _extract_json("".join(
                p.text for p in response.candidates[0].content.parts if hasattr(p, "text")
            ))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 再生成: テキストをパース可能な形に修正
        repair_prompt = (
            f"以下のテキストを有効なJSONに修正してください。"
            f"既存のキー名と値は保持し、構文エラーのみ直してください。JSONのみ出力:\n\n{text[:8000]}"
        )
        try:
            retry_response = _gemini_call_with_retry(
                model, [repair_prompt],
                generation_config=generation_config,
                timeout=180,
            )
            return json.loads(_extract_json(retry_response.text))
        except Exception:
            # 最終手段: 正規表現で必要フィールドを救済抽出
            salvaged = _salvage_json(text)
            if salvaged.get("scores") or salvaged.get("session_summary"):
                salvaged.setdefault("_warnings", []).append(
                    "JSON崩れのため一部フィールドを救済抽出しました"
                ) if isinstance(salvaged.get("_warnings"), list) else salvaged.update(
                    {"_warnings": ["JSON崩れのため一部フィールドを救済抽出しました"]}
                )
                return salvaged
            raise RuntimeError(
                f"Gemini JSON parse失敗(救済も失敗)\n"
                f"original_response_head: {text[:300]}"
            )


def evaluate_from_transcript(transcript: str, staff_name: str, session_date,
                              customer_info: dict = None,
                              contract: str = "なし", course: str = "—", store: str = "") -> dict:
    """文字起こしから評価 + FB を生成(音声不要) + 二重チェック"""
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)

    # ── 文字起こしの品質チェック ──
    transcript = (transcript or "").strip()
    if len(transcript) < 50:
        raise RuntimeError(
            f"文字起こしが短すぎます({len(transcript)}文字)。"
            f"録音内容を確認してください(無音 / 録音失敗の可能性)"
        )

    leader_fb = fetch_leader_fb_examples()
    contract_status = "🎉 契約獲得" if contract == "あり" else "🥲 契約なし(失注)"
    course_label = course if (contract == "あり" and course not in ("", "—", None)) else "(未入会)"

    audio_prompt = EVAL_PROMPT_TEMPLATE.format(
        store=store or "(未指定)",
        staff_name=staff_name,
        session_date=session_date,
        contract_status=contract_status,
        course_label=course_label,
        leader_fb_examples=leader_fb,
    )
    text_prompt = audio_prompt.replace(
        "添付された新人スタッフの新規カウンセリング録音を直接聴いて評価します。",
        "新人スタッフの新規カウンセリング文字起こしを評価します。"
    )
    text_prompt += f"\n\n【カウンセリング文字起こし】\n{transcript[:200000]}\n"
    # ★重要: transcriptは既に取得済みなので再出力させない(ループ暴走防止)
    text_prompt += (
        '\n\n【最重要・厳守】\n'
        '出力JSONに "transcript" フィールドは絶対に含めないでください。\n'
        '同じ文を繰り返さないでください。各フィールドは簡潔に1回だけ書いてください。\n'
        'customer_info / hearing_checklist / scores / session_summary / '
        'good_points / improvements のみを出力してください。'
    )

    model = genai.GenerativeModel("gemini-2.5-flash")
    gen_config = {"temperature": 0.2, "response_mime_type": "application/json", "max_output_tokens": 16000}

    # ── 第1試行 ──
    response = _gemini_call_with_retry(model, [text_prompt], generation_config=gen_config, timeout=600)
    result = _parse_with_retry(model, response, gen_config, text_prompt)

    # ── バリデーション(必須フィールドチェック) ──
    missing = _validate_result(result)
    if missing:
        # 第2試行: 不足フィールドを補完依頼
        repair_prompt = text_prompt + (
            f"\n\n【再生成依頼】前回のレスポンスで欠けていたフィールド: {missing}\n"
            f"必ず全フィールドを含めて JSON を返してください。"
        )
        retry_response = _gemini_call_with_retry(model, [repair_prompt], generation_config=gen_config, timeout=600)
        result = _parse_with_retry(model, retry_response, gen_config, repair_prompt)
        # 2度目のバリデーション
        missing_again = _validate_result(result)
        if missing_again:
            # フィールド不足でも処理は止めず、デフォルト値で補完
            scores = result.get("scores", {})
            for s in REQUIRED_SCORES:
                scores.setdefault(s, 0)
            result["scores"] = scores
            result.setdefault("session_summary", "(評価生成エラー: 要約取得失敗)")
            result.setdefault("good_points", "(評価生成エラー: 良かった点取得失敗)")
            result.setdefault("improvements", "(評価生成エラー: 改善点取得失敗)")

    return result


# ── メイン Gemini Audio 呼び出し ──────────────────

def call_gemini_with_audio(audio_path: str, staff_name: str, session_date,
                           customer_info: dict = None,
                           contract: str = "なし", course: str = "—", store: str = "") -> dict:
    """Gemini Flash 2.5 に音声ファイルを直接渡して、
    文字起こし + 評価 + FB生成 を1リクエストで完結する。
    faster-whisper を介さないので大幅高速化。
    """
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
        leader_fb_examples=leader_fb,
    )

    # ── ③ Gemini 呼び出し(音声 + プロンプト) - 429リトライ対応 ──
    model = genai.GenerativeModel("gemini-2.5-flash")
    gen_config = {"temperature": 0.2, "response_mime_type": "application/json", "max_output_tokens": 16000}
    response = _gemini_call_with_retry(model, [uploaded, prompt], generation_config=gen_config, timeout=600)

    # ── ④ ファイル削除(個人情報保護: Gemini側にも残さない) ──
    try:
        genai.delete_file(uploaded.name)
    except Exception:
        pass

    # ── ⑤ JSON パース + バリデーション(二重チェック) ──
    result = _parse_with_retry(model, response, gen_config, prompt)

    # 必須フィールド検証
    missing = _validate_result(result)
    if missing:
        # 第2試行: 不足フィールドを補完依頼
        repair_prompt = prompt + (
            f"\n\n【再生成依頼】前回のレスポンスで欠けていたフィールド: {missing}\n"
            f"必ず全フィールドを含めて JSON を返してください。"
        )
        retry_response = _gemini_call_with_retry(model, [repair_prompt], generation_config=gen_config, timeout=600)
        result = _parse_with_retry(model, retry_response, gen_config, repair_prompt)
        # それでも欠けてたらデフォルト補完
        for s in REQUIRED_SCORES:
            result.setdefault("scores", {}).setdefault(s, 0)
        result.setdefault("session_summary", "(評価生成エラー: 要約取得失敗)")
        result.setdefault("good_points", "(評価生成エラー: 良かった点取得失敗)")
        result.setdefault("improvements", "(評価生成エラー: 改善点取得失敗)")

    # 文字起こしの簡易検証(あれば50文字以上を期待)
    transcript_check = (result.get("transcript") or "").strip()
    if transcript_check and len(transcript_check) < 50:
        result["_warnings"] = result.get("_warnings", []) + [
            f"文字起こしが短い({len(transcript_check)}文字)。録音内容を確認してください"
        ]

    return result


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

    # ── ヒアリングチェックリスト整形 ──
    checklist = result.get("hearing_checklist", {}) or {}
    checklist_lines = []
    achieved = 0
    total = 0
    for item, ok in checklist.items():
        mark = "✅" if ok else "❌"
        checklist_lines.append(f"{mark} {item}")
        total += 1
        if ok:
            achieved += 1
    checklist_block = ""
    if checklist_lines:
        checklist_block = (
            f"\n\n━━━━━━━━━━━━━━\n"
            f"🔍 *ヒアリング項目チェック*  ({achieved}/{total}項目)\n"
            + "  ".join(checklist_lines)
        )

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
        f"{star_line}"
        f"{checklist_block}\n\n"
        f"━━━━━━━━━━━━━━\n"
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

    # ヒアリングチェックリストをテキスト化
    checklist = result.get("hearing_checklist", {}) or {}
    checklist_lines = [f"{'✅' if v else '❌'} {k}" for k, v in checklist.items()]
    hearing_achieved = sum(1 for v in checklist.values() if v)
    hearing_total = len(checklist) if checklist else 0
    checklist_text = ""
    if checklist_lines:
        checklist_text = f"達成: {hearing_achieved}/{hearing_total}\n" + "\n".join(checklist_lines)

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
        "ヒアリング達成数": {"number": hearing_achieved},
        "ヒアリングチェック": {"rich_text": _rich_text(checklist_text)},
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

    compressed_path = None
    try:
        # ── 自動圧縮: 大きいファイルは ffmpeg で 32kbps モノラルに ──
        original_size_mb = os.path.getsize(tmp_path) / 1024 / 1024
        processing_path, compressed = compress_audio_if_large(tmp_path, target_mb=SINGLE_FILE_SIZE_LIMIT_MB)
        if compressed:
            compressed_path = processing_path  # 後で削除
            compressed_size_mb = os.path.getsize(processing_path) / 1024 / 1024
        else:
            compressed_size_mb = original_size_mb

        # ファイルサイズに応じて単一処理 or 分割並列処理を自動振り分け
        size_mb = compressed_size_mb
        processing_stats = {
            "original_size_mb": round(original_size_mb, 1),
            "size_mb": round(size_mb, 1),
            "compressed": compressed,
            "mode": "",
            "chunks": 0,
            "failed_chunks": 0,
        }

        if size_mb <= SINGLE_FILE_SIZE_LIMIT_MB:
            # 小〜中ファイル: 一発処理(文字起こし+評価を1リクエスト)
            processing_stats["mode"] = "single"
            result = call_gemini_with_audio(processing_path, staff_name, session_date,
                                            customer_info=customer_info,
                                            contract=contract, course=course, store=store)
        else:
            # 大ファイル: 分割並列文字起こし → 評価生成
            print(f"[Chunked] {size_mb:.1f}MB → {CHUNK_MINUTES}分ごとに分割、{MAX_PARALLEL_WORKERS}並列で処理")
            transcribe_result = transcribe_audio_parallel(processing_path)
            transcript = transcribe_result["transcript"]
            processing_stats["mode"] = "chunked"
            processing_stats["chunks"] = transcribe_result["stats"]["total_chunks"]
            processing_stats["failed_chunks"] = transcribe_result["stats"]["failed_chunks"]
            processing_stats["transcript_length"] = transcribe_result["stats"]["transcript_length"]

            result = evaluate_from_transcript(transcript, staff_name, session_date,
                                              customer_info=customer_info,
                                              contract=contract, course=course, store=store)
            # transcript フィールドを上書き(評価レスポンスより並列文字起こしの方が高精度)
            result["transcript"] = transcript
            if transcribe_result["failed_chunks"]:
                result["_warnings"] = result.get("_warnings", []) + [
                    f"⚠ {len(transcribe_result['failed_chunks'])}件のチャンクで文字起こし失敗。"
                    f"該当時間帯の評価精度が低下している可能性があります"
                ]

        # ── 最終バリデーション(処理が確実に完了したか確認) ──
        final_missing = _validate_result(result)
        if final_missing:
            raise RuntimeError(f"最終バリデーション失敗。欠落フィールド: {final_missing}")

        # 文字起こし最終チェック
        final_transcript = (result.get("transcript") or "").strip()
        if not final_transcript:
            result["transcript"] = "(文字起こし取得失敗)"
            result["_warnings"] = result.get("_warnings", []) + ["文字起こし全文が取得できませんでした"]

        result["processing_stats"] = processing_stats
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
        # 圧縮版も削除
        if compressed_path:
            try:
                os.unlink(compressed_path)
            except OSError:
                pass
