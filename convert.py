#!/usr/bin/env python3
"""Claude Code Textbook: Markdown → モバイル最適化HTML変換スクリプト."""

import re
import unicodedata
from pathlib import Path

from jinja2 import Template
from markdown_it import MarkdownIt

# --- 設定 ---

SOURCE_DIR = Path(__file__).parent / "source"
OUTPUT_DIR = Path(__file__).parent / "docs"

# 既存章の手動定義（タイトル・アイコン・説明をカスタマイズしたい場合に記載）
# ここに書かれていないファイルは source/ を自動スキャンして追加される
CHAPTER_MAP = {
    "00_さっとわかる版.md": {"slug": "00-quick", "title": "さっとわかる版", "icon": "⚡", "desc": "全章の重要概念を1ページにまとめた超入門"},
    "01_AIの基礎.md": {"slug": "01-ai-basics", "title": "AIの基礎", "icon": "🤖", "desc": "LLMの仕組み・ハルシネーション・コンテキストの基本"},
    "02_環境構築.md": {"slug": "02-setup", "title": "環境構築", "icon": "🏗️", "desc": "WSL2 + Claude Code CLI のセットアップ手順"},
    "03_Claude-Code使い方.md": {"slug": "03-usage", "title": "Claude Codeの使い方", "icon": "⚡", "desc": "基本コマンド・セッション・スキル・MCPの基礎"},
    "04_プロンプト工学.md": {"slug": "04-prompting", "title": "プロンプト工学", "icon": "💬", "desc": "良い指示の書き方・具体例・思考の連鎖"},
    "05_知識管理.md": {"slug": "05-knowledge", "title": "知識管理", "icon": "📚", "desc": "なぜ記録が必要・SSOTの概念・日記の書き方"},
    "06_自動化と拡張.md": {"slug": "06-automation", "title": "自動化と拡張", "icon": "⚙️", "desc": "フック・cron・MCPサーバー・スキル自作"},
    "07_安全な使い方.md": {"slug": "07-security", "title": "安全な使い方", "icon": "🔒", "desc": "APIキー管理・コスト意識・リスク対策"},
    "08_GitHub入門.md": {"slug": "08-github", "title": "GitHub入門", "icon": "🐙", "desc": "Git/GitHubの概念・基本操作・実践ガイド"},
    "別冊_コマンドリファレンス.md": {"slug": "ref-commands", "title": "コマンドリファレンス", "icon": "⌨️", "desc": "よく使うコマンド一覧"},
    "別冊_トラブルシューティング.md": {"slug": "ref-troubleshoot", "title": "トラブルシューティング", "icon": "🔧", "desc": "よくあるエラーと直し方"},
    "別冊_用語集.md": {"slug": "ref-glossary", "title": "用語集", "icon": "📖", "desc": "AI・Claude Code用語のはじめて解説"},
    "別冊_プロンプト例文集.md": {"slug": "ref-prompts", "title": "プロンプト例文集", "icon": "💬", "desc": "すぐ使えるテンプレート20選"},
}


# --- 自動スキャン ---

def _filename_to_slug(filename: str) -> str:
    """ファイル名からslugを生成: '13_glm-rate-proxy.md' → '13-glm-rate-proxy'"""
    stem = Path(filename).stem  # 拡張子除去
    # 先頭の数字+区切り文字を抽出: "13_foo" → "13-foo", "00_早見表" → "00-cheatsheet相当"
    # アンダースコアをハイフンに、日本語はASCIIに変換できないのでそのまま残す
    slug = stem.replace("_", "-", 1)  # 最初の _ のみハイフン化
    # 残りの _ もハイフン化
    slug = slug.replace("_", "-")
    # ASCII以外の文字を除去してslugを作る
    ascii_slug = ""
    for ch in slug:
        if ch.isascii():
            ascii_slug += ch.lower()
        elif ch == "-":
            ascii_slug += "-"
    # 連続ハイフン・末尾ハイフンを整理
    ascii_slug = re.sub(r"-+", "-", ascii_slug).strip("-")
    return ascii_slug or slug


def _extract_frontmatter(text: str) -> tuple[dict, str]:
    """YAMLフロントマターを抽出。なければ空dictとテキストをそのまま返す。"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_text = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")
    meta = {}
    for line in fm_text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta, body


def _extract_title_from_h1(text: str) -> str:
    """H1ヘッダーからタイトルを抽出。'# 13 GLM Rate Proxy — ...' → 'GLM Rate Proxy'"""
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            # 番号プレフィックスを除去: "13 GLM Rate Proxy" → "GLM Rate Proxy"
            title = re.sub(r"^\d+\s+", "", title)
            # ダッシュ以降の説明を除去: "GLM Rate Proxy — 説明" → "GLM Rate Proxy"
            title = re.split(r"\s+[—–-]\s+", title)[0].strip()
            return title
    return ""


def _extract_desc_from_h1(text: str) -> str:
    """H1ヘッダーのダッシュ以降を説明として抽出。"""
    for line in text.splitlines():
        if line.startswith("# "):
            parts = re.split(r"\s+[—–-]\s+", line[2:].strip(), maxsplit=1)
            if len(parts) > 1:
                return parts[1].strip()
    return ""


def build_chapter_map() -> dict:
    """source/ をスキャンして完全なCHAPTER_MAPを構築。
    CHAPTER_MAPに未登録のファイルは自動検出して追加する。"""
    result = dict(CHAPTER_MAP)

    for md_file in sorted(SOURCE_DIR.glob("*.md")):
        filename = md_file.name
        if filename.startswith("_"):
            continue  # _README.md等は除外
        if filename in result:
            continue  # 既登録はスキップ

        text = md_file.read_text(encoding="utf-8")
        meta, body = _extract_frontmatter(text)

        title = meta.get("title") or _extract_title_from_h1(text) or Path(filename).stem
        desc = meta.get("card_desc") or meta.get("desc") or _extract_desc_from_h1(text) or title
        icon = meta.get("icon", "📄")
        slug = meta.get("slug") or _filename_to_slug(filename)

        result[filename] = {"slug": slug, "title": title, "icon": icon, "desc": desc}
        print(f"AUTO: {filename} → {slug} ({title})")

    return result

REMOVE_SECTIONS = [
    "## 関連",
    "## 関連ドキュメント",
    "## 次の章",
    "## あなたの現在のフック構成",
    "## あなたの環境のメモリ構成",
    "## あなたの設定ファイル一覧",
    "## あなたのLLMルーティング",
    "## あなたの環境での使い方",
    "## あなたの環境の特記事項",
    "## あなたのMCPサーバー構成",
    "## あなたのフック一覧",
]

REMOVE_PATTERNS = [
    "あなたの",
]

INLINE_REPLACEMENTS = [
    # 個人ルーティング情報 → 汎用化
    (r"GLM-5\.1にルーティング", "Anthropic APIまたは代替プロバイダー経由で利用可能"),
    (r"GLM-4\.7にルーティング", "Anthropic APIまたは代替プロバイダー経由で利用可能"),
    (r"GLM-4\.5-Airにルーティング", "Anthropic APIまたは代替プロバイダー経由で利用可能"),
    (r"GLM-5\.1がデフォルト", "デフォルトモデルが自動選択"),
    (r"あなたの環境:\s*GLM-5\.1\s*→\s*MiniMax\s*→\s*Sonnet", "モデルは /model コマンドで切替可能"),
    (r"あなたの環境ではGLM-5\.1にルーティング", "API経由で利用可能"),
    (r"あなたの環境ではGLM-4\.7にルーティング", "API経由で利用可能"),
    (r"GLM-4\.5-Air に切替", "Haiku に切替"),
    (r"GLM-4\.7 に戻す", "Sonnet に戻す"),
    (r"通常タスク → 🟡 GLM-5\.1（glm_ask経由）", "通常タスク → Opus または Sonnet"),
    (r"フォールバック → 🟠 MiniMax（minimax_ask経由）", "フォールバック → Haiku"),
    (r"大量処理委譲 → 🟠 MiniMax（自動委譲）", "大量処理 → Haiku等の軽量モデル"),
    # 内部パス参照 → 除去
    (r"→ `00_SYSTEM/共通ルール/LLMルーティング\.md`", ""),
    (r"→ `00_SYSTEM/MCPツール使い分けガイド\.md`", ""),
    (r"あなたのobsidian-ssotリポジトリがこれに該当。", "単一リポジトリで一元管理する構成がこれに該当。"),
    (r"あなたのグローバルCLAUDE\.mdに含まれるもの:", "グローバルCLAUDE.mdに含まれるもの:"),
    (r"あなたの現在のメイン環境（WSL2）", "Linuxターミナル環境"),
    (r"LLMルーティング（GLM → MiniMax → Sonnet）", "モデルルーティング（上位モデル → バランス型 → 軽量型）"),
    (r"バッジ表示ルール（🟡\[GLM\]等）", "使用モデル表示ルール"),
    (r"GLM-5\.1", "Claude"),
    (r"GLM-4\.7", "Claude"),
    (r"GLM-4\.5-Air", "Claude"),
    (r"LLM（Claude / GLM / MiniMax）", "LLM（Claude）"),
    (r"Claude, GLM, MiniMax等", "Claude等"),
    (r"Opus/Sonnet/Haiku \+ GLM", "Opus / Sonnet / Haiku"),
    # MiniMax の残存（コードブロック・テーブル内）
    (r"MiniMax-M2\.7", "代替軽量モデル"),
    (r"MiniMax", "代替プロバイダー"),
    (r"minimax\.io", "fallback-provider.example"),
    (r"minimax", "フォールバック先"),
    # obsidian-ssot / 00_SYSTEM パス（スキル内コードブロック）
    (r"obsidian-ssot/00_SYSTEM/handoff/", "claude-code/handoff/"),
    (r"obsidian-ssot", "knowledge-base"),
    (r"00_SYSTEM/", "config/"),
    # 「あなたの設定」テーブル列 → 行ごと書き換え
    (r"\| あなたの設定 \|.*?\|", "| 備考 | なし |"),
]

TABLE_COL_SANITIZE = [
    # テーブルヘッダーから「あなたの設定」列を除去するパターン
    (r"\|\s*あなたの設定\s*\|", "| 備考 |"),
    (r"\|\s*`~/.secrets\.env`\s+からAPIキーを注入.*?\|", "| APIキーは環境変数で管理 |"),
    (r"\|\s*`check-command-safety\.py`\s+が危険コマンドを自動ブロック.*?\|", "| 危険コマンドを自動ブロック |"),
    (r"\|\s*MCP設定変更時の使い分けガイド自動更新.*?\|", "| 設定変更を自動検知 |"),
    (r"\|\s*セッション終了時のサマリー記録.*?\|", "| セッション終了時に記録 |"),
    (r"\|\s*Anthropic APIまたは代替プロバイダー経由で利用可能\s*\|", "| API経由で利用可能 |"),
]

MERMAID_DIAGRAMS = {
    "01_AIの基礎.md": [
        (
            "## コンテキストウィンドウ：有限の作業台",
            """graph LR
    subgraph "200K トークン コンテキストウィンドウ"
        A["システムプロンプト<br/>~3%"]
        B["ツール定義<br/>~20%"]
        C["メモリ・スキル<br/>~4%"]
        D["会話履歴<br/>~3%"]
        E["空き容量<br/>~70%"]
    end""",
        ),
    ],
    "03_Claude-Code使い方.md": [
        (
            "## 1. Claude Codeのはじまり方",
            """graph TD
    User["👤 ユーザー"] --> CLI["💻 Claude Code CLI"]
    CLI --> SP["📋 システムプロンプト"]
    CLI --> MCP["🔌 MCPツール定義"]
    CLI --> SK["🎯 スキル定義"]
    CLI --> MEM["🧠 メモリ読込"]
    CLI --> LLM["🤖 LLM"]
    LLM --> Tools["🔧 ツール実行"]
    Tools --> Files["📁 ファイル操作"]
    Tools --> Shell["💻 シェル実行"]
    Tools --> API["🌐 API呼出"]
    Tools --> Agent["🤖 サブエージェント"]
    LLM --> Resp["💬 レスポンス"]
    Resp --> User""",
        ),
    ],
    "05_知識管理.md": [
        (
            "## 04-6 応用：CLAUDE.md の 3 層メモリ構造",
            """graph TD
    subgraph "🧠 メモリシステム"
        AUTO["Auto Memory<br/>~/.claude/projects/"]
        USER["User Memory<br/>~/.claude/CLAUDE.md"]
        PROJ["Project Memory<br/>repo/CLAUDE.md"]
        IDX["MEMORY.md<br/>インデックス"]
    end
    AUTO --> T1["user: 役割・目標"]
    AUTO --> T2["feedback: 指導"]
    AUTO --> T3["project: 決定事項"]
    AUTO --> T4["reference: 外部参照"]
    IDX --> AUTO""",
        ),
    ],
    "06_自動化と拡張.md": [
        (
            "## 05-1 フック（Hooks）:自動化の核心",
            """sequenceDiagram
    participant U as ユーザー
    participant CC as Claude Code
    participant Pre as PreToolUse
    participant Tool as ツール
    participant Post as PostToolUse

    Note over CC: 🔄 SessionStart Hook発火
    U->>CC: リクエスト送信
    CC->>Pre: ツール実行前チェック
    alt チェックOK
        Pre->>Tool: ✅ ツール実行
        Tool->>Post: 実行完了
        Post->>CC: ログ記録
    else チェックNG
        Pre-->>CC: 🚫 ブロック
    end
    CC->>U: レスポンス
    Note over CC: 🔄 Stop Hook発火""",
        ),
    ],
}

# --- HTMLテンプレート ---

CHAPTER_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="ja" data-theme="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} — AI×Claude Code 教科書</title>
    <meta name="description" content="AI×Claude Code 教科書 {{ title }}の解説 — 高校生向けAIコーディング入門">
    <meta property="og:title" content="{{ title }} — AI×Claude Code 教科書">
    <meta property="og:description" content="AI×Claude Code 教科書 {{ title }}の解説">
    <meta property="og:type" content="article">
    <meta property="og:url" content="https://fukukei23.github.io/claude-code-textbook/chapters/{{ slug }}.html">
    <meta property="og:image" content="https://fukukei23.github.io/claude-code-textbook/assets/ogp.png">
    <meta name="twitter:card" content="summary_large_image">
    <link rel="stylesheet" href="../assets/style.css">
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>⚡</text></svg>">
</head>
<body>
    <header class="site-header">
        <button class="menu-toggle" aria-label="メニュー" id="menuToggle">
            <span></span><span></span><span></span>
        </button>
        <a href="../index.html" class="site-title">📚 AI×Claude Code 教科書</a>
        <button class="theme-toggle" id="themeToggle" aria-label="テーマ切替">
            <span class="icon-light">☀️</span>
            <span class="icon-dark">🌙</span>
        </button>
    </header>

    <nav class="sidebar" id="sidebar">
        <div class="sidebar-header">
            <a href="../index.html">🏠 ホーム</a>
        </div>
        {% for ch in chapters %}
        <a href="{{ ch.slug }}.html"
           class="sidebar-link{{ ' active' if ch.slug == current_slug }}">
            <span class="sidebar-icon">{{ ch.icon }}</span>
            {{ ch.title }}
        </a>
        {% endfor %}
    </nav>
    <div class="sidebar-overlay" id="sidebarOverlay"></div>

    <main class="content">
        <div class="chapter-nav-top">
            <a href="../index.html" class="nav-home">🏠 ホーム</a>
            {% if prev_ch %}
            <a href="{{ prev_ch.slug }}.html" class="nav-prev">← {{ prev_ch.title }}</a>
            {% endif %}
            {% if next_ch %}
            <a href="{{ next_ch.slug }}.html" class="nav-next">{{ next_ch.title }} →</a>
            {% endif %}
        </div>

        <article class="chapter-body">
            {{ content|safe }}
        </article>

        <nav class="chapter-nav-bottom">
            {% if prev_ch %}
            <a href="{{ prev_ch.slug }}.html" class="nav-card prev">
                <span class="nav-label">← 前の章</span>
                <span class="nav-title">{{ prev_ch.icon }} {{ prev_ch.title }}</span>
            </a>
            {% endif %}
            <a href="../index.html" class="nav-card home">
                <span class="nav-label">🏠</span>
                <span class="nav-title">ホームに戻る</span>
            </a>
            {% if next_ch %}
            <a href="{{ next_ch.slug }}.html" class="nav-card next">
                <span class="nav-label">次の章 →</span>
                <span class="nav-title">{{ next_ch.icon }} {{ next_ch.title }}</span>
            </a>
            {% endif %}
        </nav>
    </main>

    <script src="../assets/script.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
    <script>
        mermaid.initialize({
            startOnLoad: true,
            theme: document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'default',
            themeVariables: { fontSize: '14px' }
        });
    </script>
</body>
</html>
""", autoescape=True)

INDEX_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="ja" data-theme="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI×Claude Code 教科書</title>
    <meta name="description" content="高校生向け AI×Claude Code 入門教科書 — 基礎から実践までやさしく解説">
    <meta property="og:title" content="AI×Claude Code 教科書">
    <meta property="og:description" content="高校生向け AI×Claude Code 入門教科書 — 基礎から実践までやさしく解説">
    <meta property="og:type" content="website">
    <meta property="og:url" content="https://fukukei23.github.io/claude-code-textbook/">
    <meta property="og:image" content="https://fukukei23.github.io/claude-code-textbook/assets/ogp.png">
    <meta name="twitter:card" content="summary_large_image">
    <link rel="stylesheet" href="assets/style.css">
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>⚡</text></svg>">
</head>
<body class="index-page">
    <header class="site-header">
        <span class="site-title">📚 AI×Claude Code 教科書</span>
        <button class="theme-toggle" id="themeToggle" aria-label="テーマ切替">
            <span class="icon-light">☀️</span>
            <span class="icon-dark">🌙</span>
        </button>
    </header>

    <main class="content">
        <section class="hero">
            <h1>AI×Claude Code 教科書</h1>
            <p>高校生向け AIコーディング入門 —<br>基礎知識から実践テクニックまでやさしく解説</p>
        </section>

        <section class="chapter-grid">
            {% for ch in chapters %}
            <a href="chapters/{{ ch.slug }}.html" class="chapter-card">
                <div class="card-icon">{{ ch.icon }}</div>
                <div class="card-number">第{{ ch.number }}章</div>
                <h2 class="card-title">{{ ch.title }}</h2>
                <p class="card-desc">{{ ch.desc }}</p>
            </a>
            {% endfor %}
        </section>

        <section class="features">
            <h2>📖 この教科書の特徴</h2>
            <div class="feature-grid">
                <div class="feature-item">
                    <span class="feature-icon">🎯</span>
                    <h3>初心者向け</h3>
                    <p>専門用語は初出時に説明。前提知識不要</p>
                </div>
                <div class="feature-item">
                    <span class="feature-icon">📊</span>
                    <h3>図解付き</h3>
                    <p>アーキテクチャやフローをMermaid図で視覚化</p>
                </div>
                <div class="feature-item">
                    <span class="feature-icon">📱</span>
                    <h3>モバイル対応</h3>
                    <p>スマホからいつでも見返せるレスポンシブデザイン</p>
                </div>
                <div class="feature-item">
                    <span class="feature-icon">🌙</span>
                    <h3>ダークモード</h3>
                    <p>目に優しいテーマ切替対応</p>
                </div>
            </div>
        </section>
    </main>

    <footer class="site-footer">
        <p>AI×Claude Code 教科書 — <a href="https://github.com/fukukei23/claude-code-textbook">GitHub</a></p>
    </footer>

    <script src="assets/script.js"></script>
</body>
</html>
""", autoescape=True)


# --- フィルタリング ---

def filter_sections(text: str) -> str:
    """教材の個人情報・内部参照・非公開セクションをサニタイズ.

    - 非公開H2セクション（## 関連 / ## あなたの…）を次のH2まで削除
    - 非公開H3セクション（### あなたの…）を次のH2/H3まで削除
    - INLINE_REPLACEMENTS: 個人ルーティング情報→汎用化・内部パス除去
    - TABLE_COL_SANITIZE: テーブル列の個人設定→汎用化
    - ユーザー名・ID（yn4416/fukukei）除去
    """
    # 1. 非公開 H2 セクション削除（次の H2 または文末まで）
    text = re.sub(
        r'^## (関連|あなたの).*?(?=^## |\Z)',
        '',
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    # 2. 非公開 H3 セクション削除（次の H2/H3 または文末まで）
    text = re.sub(
        r'^### あなたの.*?(?=^## |^### |\Z)',
        '',
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    # 3. インライン置換（個人ルーティング情報→汎用化・内部パス除去）
    for pattern, replacement in INLINE_REPLACEMENTS:
        text = re.sub(pattern, replacement, text)
    # 4. テーブル列サニタイズ
    for pattern, replacement in TABLE_COL_SANITIZE:
        text = re.sub(pattern, replacement, text)
    # 5. ユーザー名・ID 除去
    for secret_id in ("yn4416", "fukukei"):
        text = text.replace(secret_id, "")
    return text


# --- Markdown → HTML変換 ---

def convert_md_to_html(md_text: str) -> str:
    """MarkdownをHTMLに変換."""
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    return md.render(md_text)


def inject_mermaid(html: str, filename: str) -> str:
    """Mermaid図を指定位置に挿入."""
    diagrams = MERMAID_DIAGRAMS.get(filename, [])
    if not diagrams:
        return html

    for heading, diagram_code in diagrams:
        # HTMLの見出しタグを検索（<a id>タグ込みも対応）
        heading_text = heading.replace("## ", "").strip()
        mermaid_block = (
            f'<div class="mermaid-wrapper">'
            f'<div class="mermaid">\n{diagram_code}\n</div>'
            f'</div>'
        )

        # <h2>テキスト</h2> または <h2><a ...></a>テキスト</h2> の前に挿入
        pattern = f"(<h2>(?:<a[^>]*></a>)?{re.escape(heading_text)}</h2>)"
        if re.search(pattern, html):
            html = re.sub(pattern, mermaid_block + r"\1", html, count=1)

    return html


def rewrite_links(html: str, chapter_map: dict | None = None) -> str:
    """内部リンクをHTML URLに書き換え."""
    from urllib.parse import quote, unquote

    cmap = chapter_map or CHAPTER_MAP

    for filename, info in cmap.items():
        # [テキスト](XX_YY.md) → XX-yy.html
        html = html.replace(f'href="{filename}', f'href="{info["slug"]}.html')
        # [テキスト](XX_YY.md#anchor) → XX-yy.html#anchor
        html = re.sub(
            rf'href="{re.escape(filename)}#',
            f'href="{info["slug"]}.html#',
            html,
        )

        # URLエンコードされたリンク（例: 11_%E7%8F%BE%E5%A0%B4...）も処理
        encoded_name = quote(filename, safe='')
        if encoded_name != filename:
            html = html.replace(f'href="{encoded_name}', f'href="{info["slug"]}.html')
            html = re.sub(
                rf'href="{re.escape(encoded_name)}#',
                f'href="{info["slug"]}.html#',
                html,
            )

    # 未変換の.mdリンクをすべて処理
    def replace_md_link(match):
        href = match.group(1)
        for filename, info in cmap.items():
            decoded = unquote(href)
            if filename in decoded or filename in href:
                anchor = ""
                if "#" in href:
                    anchor = "#" + href.split("#", 1)[1]
                elif "#" in decoded:
                    anchor = "#" + decoded.split("#", 1)[1]
                return f'href="{info["slug"]}.html{anchor}"'
        return f'href="#"'

    html = re.sub(r'href="([^"]*\.md[^"]*)"', replace_md_link, html)

    # 外部リンク（obsidian-ssot内の他ファイル）を除去
    html = re.sub(r'href="\.\./[^"]*"', 'href="#"', html)
    html = re.sub(r'href="01_DECISIONS[^"]*"', 'href="#"', html)

    return html


def enhance_html(html: str) -> str:
    """HTMLに装飾を追加（テーブルラップ・コールアウト等）."""
    # テーブルをスクロールラッパーで囲む
    html = re.sub(
        r"(<table[^>]*>.*?</table>)",
        r'<div class="table-wrapper">\1</div>',
        html,
        flags=re.DOTALL,
    )

    # 引用ブロックをコールアウトに変換
    def callout_replace(match):
        content = match.group(1)
        if "注意" in content or "⚠" in content:
            return f'<div class="callout callout-warn"><p>{content}</p></div>'
        if "重要" in content:
            return f'<div class="callout callout-danger"><p>{content}</p></div>'
        if "現場の知見" in content or "💡" in content or "Tip" in content:
            return f'<div class="callout callout-tip"><p>{content}</p></div>'
        return f'<div class="callout callout-info"><p>{content}</p></div>'

    html = re.sub(r"<blockquote>\s*<p>(.*?)</p>\s*</blockquote>", callout_replace, html, flags=re.DOTALL)

    return html


# --- メイン ---

def main():
    # ディレクトリ準備
    chapters_dir = OUTPUT_DIR / "chapters"
    assets_dir = OUTPUT_DIR / "assets"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    # 古い生成物をクリア（CHAPTER_MAPから外れた章の残骸を除去し、クリーンビルドを保証）
    for stale in chapters_dir.glob("*.html"):
        stale.unlink()

    # 章リストを構築（自動スキャン込み）
    effective_map = build_chapter_map()
    chapters = []
    for filename, info in sorted(effective_map.items()):
        chapters.append({
            "number": info["slug"][:2],
            "slug": info["slug"],
            "title": info["title"],
            "icon": info["icon"],
            "desc": info["desc"],
            "filename": filename,
        })

    # 各章を変換
    for i, ch in enumerate(chapters):
        src = SOURCE_DIR / ch["filename"]
        if not src.exists():
            print(f"SKIP: {ch['filename']} not found")
            continue

        md_text = src.read_text(encoding="utf-8")
        md_text = filter_sections(md_text)
        html_body = convert_md_to_html(md_text)
        html_body = inject_mermaid(html_body, ch["filename"])
        html_body = rewrite_links(html_body, effective_map)
        html_body = enhance_html(html_body)

        prev_ch = chapters[i - 1] if i > 0 else None
        next_ch = chapters[i + 1] if i < len(chapters) - 1 else None

        full_html = CHAPTER_TEMPLATE.render(
            title=ch["title"],
            slug=ch["slug"],
            current_slug=ch["slug"],
            content=html_body,
            chapters=chapters,
            prev_ch=prev_ch,
            next_ch=next_ch,
        )

        out = chapters_dir / f"{ch['slug']}.html"
        out.write_text(full_html, encoding="utf-8")
        print(f"OK: {ch['slug']}.html")

    # index.html 生成
    index_html = INDEX_TEMPLATE.render(chapters=chapters)
    (OUTPUT_DIR / "index.html").write_text(index_html, encoding="utf-8")
    print("OK: index.html")

    print(f"\n完了: {len(chapters)}章 + index → {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
