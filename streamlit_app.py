"""streamlit_app.py - ハリナチュレ育成FBシステム(HARI NATURE ブランドデザイン)

Streamlit Cloud のエントリポイント。
新規カウンセリング録音をアップロード → 文字起こし → AI評価 → 育成FB生成。
"""

import streamlit as st
from datetime import date
from pathlib import Path


# ── ページ設定 ─────────────────────────────────────
st.set_page_config(
    page_title="FB SYSTEM | HARI NATURE",
    page_icon="🪡",
    layout="centered",
    initial_sidebar_state="collapsed",
)


# ── HARI NATURE ブランドCSS ────────────────────────
# カラーパレット:
#   モスグリーン(プライマリ)  #7A9560
#   ダークグレー(文字)        #4A4A4A
#   ライトグリーン(ハイライト) #A8C088
#   アイボリー(背景)          #FBFAF6
#   ベージュ(セカンダリ背景)  #F2EDE4
CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=Noto+Serif+JP:wght@300;400;500;700&family=Noto+Sans+JP:wght@300;400;500;700&display=swap');

    /* Streamlitヘッダー非表示 */
    [data-testid="stHeader"] { background: transparent; height: 0; }
    [data-testid="stToolbar"] { display: none; }
    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }

    /* 全体背景: アイボリー */
    .stApp {
        background: linear-gradient(180deg, #FBFAF6 0%, #F2EDE4 100%);
        font-family: 'Noto Sans JP', sans-serif;
    }

    /* メインコンテナ */
    .main .block-container {
        max-width: 760px;
        padding-top: 2rem;
        padding-bottom: 4rem;
    }

    /* ロゴ星 */
    .logo-star {
        text-align: center;
        font-family: serif;
        font-size: 3rem;
        background: linear-gradient(135deg, #A8C088 0%, #7A9560 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        line-height: 1;
        margin-bottom: 0.5rem;
    }

    /* ブランドロゴ */
    .brand-logo {
        text-align: center;
        font-family: 'Cormorant Garamond', serif;
        font-size: 2.75rem;
        font-weight: 500;
        background: linear-gradient(90deg, #7A9560 0%, #A8C088 50%, #7A9560 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        letter-spacing: 0.18em;
        line-height: 1.15;
        margin: 0;
    }
    .brand-logo .leaf {
        font-family: 'Cormorant Garamond', 'Times New Roman', serif;
        font-style: italic;
        font-weight: 300;
        font-size: 2.2rem;
        vertical-align: -0.02em;
        margin: 0 0.7rem;
        color: #A8C088;
        -webkit-text-fill-color: #A8C088;
        background: none;
        opacity: 0.8;
    }
    .brand-tagline {
        text-align: center;
        font-family: 'Noto Serif JP', serif;
        color: #7A9560;
        font-size: 0.95rem;
        letter-spacing: 0.5em;
        font-weight: 300;
        margin-top: 0.75rem;
    }

    /* ロゴ区切り線 */
    .brand-divider {
        width: 60px;
        height: 1px;
        background: linear-gradient(90deg, transparent 0%, #A8C088 50%, transparent 100%);
        margin: 1.5rem auto 2.5rem auto;
    }

    /* タイトル(ブランドロゴと統一: Cormorant Garamond + モスグリーングラデ) */
    .app-title {
        text-align: center;
        font-family: 'Cormorant Garamond', serif;
        font-size: 1.85rem;
        font-weight: 500;
        background: linear-gradient(90deg, #7A9560 0%, #A8C088 50%, #7A9560 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        letter-spacing: 0.25em;
        line-height: 1.2;
        margin: 0 0 0.5rem 0;
    }
    .app-subtitle {
        text-align: center;
        font-family: 'Noto Serif JP', serif;
        color: #7A9560;
        font-size: 0.85rem;
        margin-bottom: 2.5rem;
        font-weight: 300;
        letter-spacing: 0.08em;
    }

    /* セクション見出し */
    .section-title {
        font-family: 'Noto Serif JP', serif;
        font-size: 0.95rem;
        font-weight: 500;
        color: #4A4A4A;
        margin: 1.5rem 0 0.75rem 0;
        padding-bottom: 0.5rem;
        border-bottom: 1px solid rgba(168, 192, 136, 0.35);
        letter-spacing: 0.08em;
    }

    /* フォームカード */
    div[data-testid="stForm"] {
        background: #FBFAF6;
        padding: 2.5rem !important;
        border-radius: 4px;
        box-shadow: 0 4px 24px rgba(122, 149, 96, 0.10);
        border: 1px solid rgba(168, 192, 136, 0.20);
    }

    /* プライマリボタン */
    .stButton button[kind="primary"],
    .stFormSubmitButton button {
        background: linear-gradient(135deg, #7A9560 0%, #5F7A4A 100%) !important;
        color: #FBFAF6 !important;
        border: none !important;
        padding: 0.9rem 2rem !important;
        border-radius: 2px !important;
        font-weight: 500 !important;
        font-size: 0.95rem !important;
        font-family: 'Noto Serif JP', serif !important;
        letter-spacing: 0.15em !important;
        width: 100% !important;
        transition: all 0.3s !important;
        box-shadow: 0 4px 12px rgba(122, 149, 96, 0.25) !important;
    }
    .stButton button[kind="primary"]:hover,
    .stFormSubmitButton button:hover {
        background: linear-gradient(135deg, #5F7A4A 0%, #7A9560 100%) !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 8px 20px rgba(122, 149, 96, 0.35) !important;
    }

    /* 入力欄 */
    .stTextInput input,
    .stTextArea textarea,
    .stDateInput input {
        border-radius: 2px !important;
        border: 1px solid rgba(122, 149, 96, 0.25) !important;
        padding: 0.75rem 0.9rem !important;
        transition: all 0.2s !important;
        background: #FFFFFF !important;
        font-family: 'Noto Sans JP', sans-serif !important;
    }
    .stTextInput input:focus,
    .stTextArea textarea:focus,
    .stDateInput input:focus {
        border-color: #A8C088 !important;
        box-shadow: 0 0 0 3px rgba(168, 192, 136, 0.20) !important;
    }
    label, .stTextInput label, .stTextArea label, .stDateInput label {
        font-family: 'Noto Serif JP', serif !important;
        font-weight: 500 !important;
        color: #4A4A4A !important;
        font-size: 0.9rem !important;
        letter-spacing: 0.05em !important;
    }

    /* ファイルアップローダー */
    [data-testid="stFileUploaderDropzone"] {
        background: linear-gradient(135deg, rgba(168,192,136,0.06) 0%, rgba(122,149,96,0.08) 100%);
        border: 1px dashed rgba(122, 149, 96, 0.35) !important;
        border-radius: 4px !important;
        transition: all 0.25s !important;
    }
    [data-testid="stFileUploaderDropzone"]:hover {
        border-color: #A8C088 !important;
        background: rgba(168, 192, 136, 0.08);
    }

    /* メトリクス */
    [data-testid="stMetric"] {
        background: #FBFAF6;
        padding: 1.25rem 1rem;
        border-radius: 4px;
        box-shadow: 0 2px 8px rgba(122, 149, 96, 0.08);
        border: 1px solid rgba(168, 192, 136, 0.20);
        text-align: center;
    }
    [data-testid="stMetricLabel"] {
        font-family: 'Noto Serif JP', serif;
        font-size: 0.8rem;
        color: #7A9560;
        font-weight: 400;
        letter-spacing: 0.1em;
    }
    [data-testid="stMetricValue"] {
        font-family: 'Cormorant Garamond', serif;
        font-size: 1.75rem;
        color: #7A9560;
        font-weight: 600;
    }

    /* 結果カード */
    .result-card {
        background: #FBFAF6;
        padding: 1.5rem 1.75rem;
        border-radius: 4px;
        margin: 0.75rem 0;
        box-shadow: 0 2px 12px rgba(122, 149, 96, 0.08);
        border-left: 3px solid #A8C088;
        font-family: 'Noto Sans JP', sans-serif;
        color: #4A4A4A;
        line-height: 1.8;
    }
    .result-card.good { border-left-color: #A8C088; }
    .result-card.warn { border-left-color: #B89968; }
    .result-card.line { border-left-color: #7A9560; }

    /* code(LINE文面) */
    code, pre {
        font-family: 'Noto Sans JP', sans-serif !important;
        background: #FBFAF6 !important;
        color: #4A4A4A !important;
        border: 1px solid rgba(168, 192, 136, 0.25) !important;
        border-radius: 4px !important;
    }

    /* divider */
    hr {
        border: none !important;
        height: 1px !important;
        background: linear-gradient(90deg, transparent 0%, rgba(168,192,136,0.45) 50%, transparent 100%) !important;
        margin: 2rem 0 !important;
    }

    /* ログイン画面 */
    .login-wrapper {
        max-width: 420px;
        margin: 5rem auto 0 auto;
        text-align: center;
    }
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ── ロゴ表示 ──────────────────────────────────────
ASSETS_DIR = Path(__file__).parent / "assets"
LOGO_PATH = ASSETS_DIR / "logo.png"


def render_brand_header():
    """HARI NATURE ブランドヘッダー
    ロゴ画像が assets/logo.png にあればそれを表示、なければ CSS版を表示
    """
    if LOGO_PATH.exists():
        col_l, col_c, col_r = st.columns([1, 2, 1])
        with col_c:
            st.image(str(LOGO_PATH), use_container_width=True)
    else:
        st.markdown("""
        <h1 class="brand-logo">HARI <span class="leaf">✦</span> NATURE</h1>
        <p class="brand-tagline">定額制 美容鍼サロン</p>
        """, unsafe_allow_html=True)

    st.markdown('<div class="brand-divider"></div>', unsafe_allow_html=True)


# ── メイン画面 ────────────────────────────────────────
# パスワード認証は廃止(スタッフが手間なく即アクセスできるように)
# URL直アクセスで誰でも利用可能
# ※ 録音音声は処理後即削除・Notionには会員情報のみ保存 で個人情報保護

def main():
    render_brand_header()

    st.markdown('<h2 class="app-title">FB SYSTEM</h2>', unsafe_allow_html=True)
    st.markdown(
        '<p class="app-subtitle">新規カウンセリング録音をアップロード → AIが評価+FBを自動生成</p>',
        unsafe_allow_html=True,
    )

    COURSE_OPTIONS = [
        "—",
        "サブスク 月2回",
        "サブスク 月3回",
        "サブスク 月4回",
        "美容特化 月3回",
        "トライアル",
        "次回予約(HPB)",
    ]

    st.markdown('<div class="section-title">SESSION INFORMATION</div>', unsafe_allow_html=True)

    STORE_OPTIONS = [
        "吉祥寺", "錦糸町", "新宿", "日吉", "梅田", "横浜駅前", "神戸元町",
        "大宮", "那覇", "西心斎橋", "北千住", "五反田", "札幌", "池袋",
        "町田", "名古屋", "南流山", "博多", "高崎",
    ]

    col1, col2 = st.columns(2)
    with col1:
        store = st.selectbox("店舗", STORE_OPTIONS, index=0, key="store_select")
    with col2:
        staff_name = st.text_input("ハリザーブの名前", placeholder="例：松崎未来、MIRAI", key="staff_name_input")
    session_date = st.date_input("施術日", value=date.today(), key="session_date_input")

    st.markdown('<div class="section-title">CONTRACT RESULT</div>', unsafe_allow_html=True)
    col3, col4 = st.columns(2)
    with col3:
        contract = st.selectbox(
            "入会の有無",
            ["なし", "あり"],
            index=0,
            help="契約成立の有無を選んでね",
            key="contract_select",
        )
    with col4:
        is_contract = (contract == "あり")
        course = st.selectbox(
            "コース(入会ありの場合のみ)",
            COURSE_OPTIONS,
            index=0,
            disabled=not is_contract,
            help="入会ありの場合に選択",
            key="course_select",
        )
    # 「なし」を選んだら course を強制的に "—"
    if not is_contract:
        course = "—"

    with st.form("upload_form"):
        st.markdown('<div class="section-title">AUDIO FILE</div>', unsafe_allow_html=True)
        audio_file = st.file_uploader(
            "録音ファイル",
            type=["m4a", "mp3", "wav", "mp4", "aac"],
            label_visibility="collapsed",
            help=("新規カウンセリング・施術・クロージングの録音\n\n"
                  "⏱ 目安: 30分録音 → 約5〜15分 / 60分録音 → 約15〜40分の処理時間"),
        )

        st.markdown('<div class="section-title">QUESTIONS (OPTIONAL)</div>', unsafe_allow_html=True)
        questions = st.text_area(
            "疑問点(リーダー/研修担当に聞きたいこと)",
            placeholder="例: 危機感トークがうまく入れられない / 3ヶ月提案のタイミングは?",
            height=80,
            help="任意。リーダーや研修担当に相談したいことがあれば記入してね",
        )

        submitted = st.form_submit_button("GENERATE FB", type="primary")

    if submitted:
        errors = []
        if not staff_name:
            errors.append("ハリザーブの名前")
        if not audio_file:
            errors.append("録音ファイル")
        if errors:
            st.error(f"⚠️ 未入力: {', '.join(errors)} を入力してね💦")
            return

        # お客様情報は AI が音声から自動抽出するので入力不要
        customer_info = {}
        from coaching.coaching_analyzer import analyze_session, SINGLE_FILE_SIZE_LIMIT_MB, CHUNK_MINUTES, MAX_PARALLEL_WORKERS
        # ファイルサイズで処理方式を自動判定
        size_mb = audio_file.size / 1024 / 1024
        if size_mb <= SINGLE_FILE_SIZE_LIMIT_MB:
            mode_label = "🚀 一発処理モード"
            est_low = max(1, int(size_mb * 0.05))
            est_high = max(2, int(size_mb * 0.15))
            mode_detail = f"{size_mb:.1f}MB → 通常処理(文字起こし+評価を1回で完結)"
        else:
            mode_label = "⚡️ 並列チャンク処理モード"
            # チャンク数の推定: ファイルサイズ ≈ 1MB/分 (m4a 128kbps)
            est_chunks = max(2, int(size_mb / CHUNK_MINUTES) + 1)
            est_low = max(1, est_chunks // MAX_PARALLEL_WORKERS + 1)
            est_high = max(2, est_chunks // MAX_PARALLEL_WORKERS + 3)
            mode_detail = (
                f"{size_mb:.1f}MB → {CHUNK_MINUTES}分ごとに約{est_chunks}チャンクへ分割、"
                f"{MAX_PARALLEL_WORKERS}並列で文字起こし→評価生成"
            )

        spinner_msg = (
            f"{mode_label}: {size_mb:.1f}MB の音声を処理中... 予測 {est_low}〜{est_high}分💕\n\n"
            f"完了するとSlackに通知が届くから、このタブはそのまま開いておいてね"
        )
        st.info(
            f"⏱ **{mode_label}**\n\n"
            f"{mode_detail}\n\n"
            f"完了見込み: **約{est_low}〜{est_high}分** ✨"
        )
        with st.spinner(spinner_msg):
            try:
                result = analyze_session(
                    audio_file, staff_name, session_date,
                    customer_info=customer_info,
                    contract=contract, course=course, store=store,
                    questions=questions.strip(),
                )
            except Exception as e:
                st.error(f"処理失敗💦 {e}")
                return

        st.success("フィードバック生成完了")

        st.markdown('<div class="section-title">SESSION SUMMARY</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="result-card line">{result.get("session_summary", "(要約なし)")}</div>', unsafe_allow_html=True)

        st.markdown('<div class="section-title">EVALUATION</div>', unsafe_allow_html=True)
        scores = result.get("scores", {})
        col_a, col_b, col_c, col_d = st.columns(4)
        with col_a: st.metric("HEARING",  f"{scores.get('hearing', 0)} / 5")
        with col_b: st.metric("PROPOSAL", f"{scores.get('proposal', 0)} / 5")
        with col_c: st.metric("CLOSING",  f"{scores.get('closing', 0)} / 5")
        with col_d: st.metric("TONE",     f"{scores.get('tone', 0)} / 5")

        # ── ヒアリングチェックリスト表示 ──
        checklist = result.get("hearing_checklist", {}) or {}
        if checklist:
            achieved = sum(1 for v in checklist.values() if v)
            total = len(checklist)
            st.markdown(
                f'<div class="section-title">HEARING CHECKLIST  ({achieved}/{total})</div>',
                unsafe_allow_html=True,
            )
            # 3列でグリッド表示
            check_items = list(checklist.items())
            cols = st.columns(3)
            for i, (item, ok) in enumerate(check_items):
                with cols[i % 3]:
                    mark = "✅" if ok else "❌"
                    st.markdown(f"{mark} {item}")

        st.markdown('<div class="section-title">STRENGTHS</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="result-card good">{result.get("good_points", "(なし)")}</div>', unsafe_allow_html=True)

        st.markdown('<div class="section-title">IMPROVEMENTS</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="result-card warn">{result.get("improvements", "(なし)")}</div>', unsafe_allow_html=True)

        if questions.strip():
            st.markdown('<div class="section-title">QUESTIONS FOR LEADER</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="result-card line">{questions.strip()}</div>', unsafe_allow_html=True)

        st.divider()
        st.caption("Slack に 振り返り内容 + 評価 + FB + 疑問点 が自動投稿されました")

        notion_url = result.get("notion_url", "")
        if notion_url:
            st.caption(f"🪡 Notion蓄積完了 → [履歴ページを開く]({notion_url})")


if __name__ == "__main__":
    main()
