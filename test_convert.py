"""convert.py のテスト — 個人情報除去・リンク書き換え・セクションフィルタリング."""

import re

import pytest

from convert import (
    CHAPTER_MAP,
    filter_sections,
    inject_mermaid,
    rewrite_links,
    convert_md_to_html,
    enhance_html,
    MERMAID_DIAGRAMS,
    OUTPUT_DIR,
)


# === 1. 個人情報サニタイズ ===

PERSONAL_PATTERNS = [
    "yn4416",
    "fukukei",
    "GLM-5.1",
    "GLM-4.7",
    "GLM-4.5-Air",
    "00_SYSTEM/",
    # glm_ask / minimax_ask はガイドに公開掲載するツール名のため除外
]


class TestNoPersonalInfoInOutput:
    """生成済みHTMLに個人情報が含まれないことを検証."""

    @pytest.fixture(autouse=True)
    def _generate(self):
        main = __import__("convert", fromlist=["main"]).main
        main()

    @pytest.mark.parametrize("pattern", PERSONAL_PATTERNS)
    def test_no_personal_info_in_chapters(self, pattern):
        for html_file in sorted((OUTPUT_DIR / "chapters").glob("*.html")):
            content = html_file.read_text(encoding="utf-8")
            # 意図的に含まれる公開URL（footer/OGP）は除外
            body = re.sub(r'<footer.*?</footer>', '', content, flags=re.DOTALL)
            body = re.sub(r'<meta property="og:.*?">', '', body)
            body = re.sub(r'<a href="https://github\.com/[^"]*">', '', body)
            assert pattern not in body, (
                f"{pattern} found in {html_file.name}"
            )

    @pytest.mark.parametrize("pattern", PERSONAL_PATTERNS)
    def test_no_personal_info_in_index(self, pattern):
        index = OUTPUT_DIR / "index.html"
        if not index.exists():
            pytest.skip("index.html not found")
        content = index.read_text(encoding="utf-8")
        body = re.sub(r'<footer.*?</footer>', '', content, flags=re.DOTALL)
        body = re.sub(r'<meta property="og:.*?">', '', body)
        body = re.sub(r'<a href="https://github\.com/[^"]*">', '', body)
        assert pattern not in body, f"{pattern} found in index.html"

    def test_no_anata_in_output(self):
        for html_file in sorted((OUTPUT_DIR / "chapters").glob("*.html")):
            content = html_file.read_text(encoding="utf-8")
            assert "あなたの" not in content, (
                f"「あなたの」found in {html_file.name}"
            )


# === 2. セクションフィルタリング ===

class TestFilterSections:
    """filter_sections() の単体テスト."""

    def test_removes_kanren_section(self):
        md = "## 本文\nhello\n## 関連\n- [link](x.md)\n## 次セクション\nok"
        result = filter_sections(md)
        assert "## 関連" not in result
        assert "[link](x.md)" not in result
        assert "## 次セクション" in result

    def test_removes_anata_h2_section(self):
        md = "## 本文\nok\n## あなたのLLMルーティング\nsecret\n## 次セクション\nok2"
        result = filter_sections(md)
        assert "あなたのLLMルーティング" not in result
        assert "secret" not in result
        assert "## 次セクション" in result

    def test_removes_anata_h3_section(self):
        md = "## 本文\nok\n### あなたのMCP設定\nsecret\n## 次セクション\nok2"
        result = filter_sections(md)
        assert "あなたのMCP設定" not in result
        assert "secret" not in result

    def test_sanitizes_username(self):
        assert "yn4416" not in filter_sections("path: /home/yn4416/")
        assert "fukukei" not in filter_sections("user: fukukei")

    def test_sanitizes_glm_routing(self):
        result = filter_sections("GLM-5.1にルーティング")
        assert "GLM" not in result
        assert "API経由" in result or "プロバイダー" in result

    def test_sanitizes_anata_in_table(self):
        result = filter_sections("| あなたの設定 | `secret` |")
        assert "あなたの設定" not in result

    def test_sanitizes_internal_path(self):
        result = filter_sections("→ `00_SYSTEM/共通ルール/LLMルーティング.md`")
        assert "00_SYSTEM" not in result

    def test_preserves_normal_content(self):
        md = "## コマンド一覧\n`/clear` でリセット\n### 使い方\n説明"
        result = filter_sections(md)
        assert "## コマンド一覧" in result
        assert "`/clear`" in result
        assert "### 使い方" in result


# === 3. リンク書き換え ===

class TestRewriteLinks:
    """rewrite_links() の単体テスト."""

    def test_md_links_to_html(self):
        html = '<a href="01_基礎概念.md">link</a>'
        result = rewrite_links(html)
        assert 'href="01-basics.html"' in result
        assert ".md" not in result

    def test_md_link_with_anchor(self):
        html = '<a href="02_コマンド一覧.md#clear">link</a>'
        result = rewrite_links(html)
        assert 'href="02-commands.html#clear"' in result

    def test_url_encoded_md_links(self):
        html = '<a href="11_%E7%8F%BE%E5%A0%B4%E3%81%AE%E7%9F%A5%E8%A6%8B.md">link</a>'
        result = rewrite_links(html)
        assert ".md" not in result
        assert "11-tips.html" in result

    def test_unknown_md_links_to_hash(self):
        html = '<a href="unknown_file.md">link</a>'
        result = rewrite_links(html)
        assert 'href="#"' in result

    def test_removes_relative_links(self):
        html = '<a href="../other/file.md">link</a>'
        result = rewrite_links(html)
        assert 'href="#"' in result

    def test_all_chapter_slugs_valid(self):
        html = "".join(f'<a href="{f}"></a>' for f in CHAPTER_MAP)
        result = rewrite_links(html)
        for info in CHAPTER_MAP.values():
            assert f'{info["slug"]}.html' in result


# === 4. Mermaid注入 ===

class TestMermaidInjection:
    """inject_mermaid() の単体テスト."""

    def test_injects_diagram(self):
        html = "<h2>アーキテクチャ</h2><p>text</p>"
        result = inject_mermaid(html, "01_基礎概念.md")
        assert "mermaid-wrapper" in result
        assert "graph TD" in result

    def test_no_injection_for_unknown_file(self):
        html = "<h2>Test</h2>"
        result = inject_mermaid(html, "99_存在しない.md")
        assert "mermaid-wrapper" not in result

    def test_mermaid_no_personal_info(self):
        for filename, diagrams in MERMAID_DIAGRAMS.items():
            for heading, code in diagrams:
                for pattern in ["GLM", "MiniMax"]:
                    assert pattern not in code, (
                        f"{pattern} found in Mermaid diagram for {filename}"
                    )


# === 5. HTML生成の整合性 ===

class TestBuildIntegrity:
    """生成されたHTMLの構造チェック."""

    @pytest.fixture(autouse=True)
    def _generate(self):
        main = __import__("convert", fromlist=["main"]).main

    def test_all_chapters_generated(self):
        for info in CHAPTER_MAP.values():
            assert (OUTPUT_DIR / "chapters" / f'{info["slug"]}.html').exists()

    def test_index_generated(self):
        assert (OUTPUT_DIR / "index.html").exists()

    def test_all_chapters_have_nav(self):
        for html_file in (OUTPUT_DIR / "chapters").glob("*.html"):
            content = html_file.read_text(encoding="utf-8")
            assert "chapter-nav-bottom" in content
            assert "sidebar" in content

    def test_all_chapters_have_ogp(self):
        for html_file in (OUTPUT_DIR / "chapters").glob("*.html"):
            content = html_file.read_text(encoding="utf-8")
            assert "og:title" in content
            assert "og:image" in content
            assert "ogp.png" in content

    def test_no_broken_md_links(self):
        for html_file in (OUTPUT_DIR / "chapters").glob("*.html"):
            content = html_file.read_text(encoding="utf-8")
            # href内の.mdリンクのみ検出（ファイル名としての言及は除外）
            md_links = re.findall(r'href="[^"]*\.md[^"]*"', content)
            assert len(md_links) == 0, (
                f".md href links found in {html_file.name}: {md_links}"
            )

    def test_mermaid_rendered(self):
        files_with_diagrams = set(MERMAID_DIAGRAMS.keys())
        for md_name in files_with_diagrams:
            slug = CHAPTER_MAP[md_name]["slug"]
            html_file = OUTPUT_DIR / "chapters" / f"{slug}.html"
            if html_file.exists():
                content = html_file.read_text(encoding="utf-8")
                assert "mermaid" in content.lower()
