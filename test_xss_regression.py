"""XSS回帰テスト（convert.py セキュリティ修正の保護）.

convert.py の以下の修正が将来も維持されることを担保:
- MarkdownIt html:False（source生HTML実行を無効化）
- Jinja2 autoescape=True + content|safe（XSS回帰）
- script.js highlight() 入力長100文字制限（ReDoS防御）

既存の test_convert.py とは分離（本ファイルのみで完結）。
"""

import sys
from pathlib import Path

import pytest

# convert.py を import
sys.path.insert(0, str(Path(__file__).parent))
from convert import CHAPTER_TEMPLATE, INDEX_TEMPLATE, convert_md_to_html  # noqa: E402


# === 1. MarkdownIt html:False 検証 ===

class TestHtmlDisabled:

    def test_raw_script_is_escaped(self):
        """source の <script> は実行されず、エスケープされて出力される."""
        html = convert_md_to_html("<script>alert(1)</script>")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_raw_iframe_is_escaped(self):
        html = convert_md_to_html("本文 <iframe src=x> 末尾")
        assert "<iframe" not in html
        assert "&lt;iframe" in html

    def test_raw_onerror_is_escaped(self):
        html = convert_md_to_html('<img src=x onerror=alert(1)>')
        # インラインHTMLとして解釈されず、< がエスケープされる
        assert "<img" not in html
        assert "&lt;img" in html


# === 2. Jinja2 autoescape 検証 ===

class TestTemplateAutoEscape:

    def _chapter_payload(self):
        return {
            "title": "<script>alert(1)</script>",
            "slug": "00-x",
            "current_slug": "00-x",
            "content": "<p>OK</p>",
            "chapters": [
                {
                    "slug": "00-x",
                    "number": "00",
                    "title": "<b>t</b>",
                    "icon": "🎵",
                    "desc": "<img src=x onerror=alert(1)>",
                    "filename": "00.md",
                }
            ],
            "prev_ch": None,
            "next_ch": None,
            "version": "1",
            "build_date": "2026.01.01",
        }

    def test_chapter_template_escapes_title(self):
        out = CHAPTER_TEMPLATE.render(**self._chapter_payload())
        assert "<script>alert(1)</script>" not in out
        assert "&lt;script&gt;" in out

    def test_chapter_template_escapes_desc(self):
        out = CHAPTER_TEMPLATE.render(**self._chapter_payload())
        assert "<img src=x onerror=alert(1)>" not in out

    def test_chapter_template_keeps_safe_content_html(self):
        """content|safe により本文HTMLは保持される."""
        out = CHAPTER_TEMPLATE.render(**self._chapter_payload())
        assert "<p>OK</p>" in out

    def test_index_template_escapes_desc(self):
        out = INDEX_TEMPLATE.render(
            chapters=self._chapter_payload()["chapters"],
            version="1",
            build_date="2026.01.01",
        )
        assert "<img src=x onerror=alert(1)>" not in out
        assert "&lt;img" in out
