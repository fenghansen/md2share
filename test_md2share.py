"""PDF-only：图片内嵌、临时文件清理、输出路径和原 HTML 保留。"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import md2share


class PdfOnlyTest(unittest.TestCase):
    def test_paths_images_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / '说明.md'
            source.write_text('# 标题\n\n![图](image.png)\n')
            (root / 'image.png').write_bytes(b'image data')
            existing = source.with_suffix('.html')
            existing.write_text('已有 HTML')
            temporary = []

            def convert(html, pdf):
                temporary.append(html)
                self.assertIn('data:image/png;base64,', html.read_text())
                pdf.write_bytes(b'%PDF-test')
                return 'test'

            for extra, expected in [([], source.with_suffix('.pdf')),
                                    (['-o', str(root / 'sub' / '自选.pdf')], root / 'sub' / '自选.pdf')]:
                with patch.object(md2share, 'html_to_pdf', convert):
                    self.assertEqual(md2share.main([str(source), '--pdf-only', *extra]), 0)
                self.assertTrue(expected.exists())
                self.assertEqual(existing.read_text(), '已有 HTML')
                self.assertFalse(temporary[-1].parent.exists())

            def fail(html, pdf):
                temporary.append(html)
                raise RuntimeError('转换失败')

            with patch.object(md2share, 'html_to_pdf', fail), self.assertRaises(RuntimeError):
                md2share.main([str(source), '--pdf-only'])
            self.assertFalse(temporary[-1].parent.exists())
            self.assertEqual(existing.read_text(), '已有 HTML')
            with self.assertRaises(SystemExit):
                md2share.main([str(source), '--pdf-only', '--folder'])


class ListTest(unittest.TestCase):
    def test_continuations_and_numbering(self):
        source = '1. 第一项  \n续行一\n2. 第二项  \n续行二\n3. 第三项\n\n正文'
        result = md2share.render_blocks(md2share.parse_markdown(source))
        self.assertEqual(result.count('<ol>'), 1)
        self.assertEqual(result.count('<li>'), 3)
        self.assertIn('<li>第一项<br>\n续行一</li>', result)
        self.assertIn('<li>第二项<br>\n续行二</li>', result)
        self.assertIn('<p>正文</p>', result)
        self.assertIn('<ol start="4">', md2share.render_blocks(md2share.parse_markdown('4. 起始项')))
        mixed = md2share.render_blocks(md2share.parse_markdown('- 无序\n续行\n1. 有序\n# 标题'))
        self.assertIn('<li>无序 续行</li>', mixed)
        self.assertIn('</ul>\n\n<ol>', mixed)
        self.assertIn('<h1>标题</h1>', mixed)


class PrintLayoutTest(unittest.TestCase):
    def test_separators_code_and_continuous(self):
        source = '# 第一章\n\n```text\n# 代码里的标题\n```\n\n---\n\n# 第二章\n\n结尾'
        body = md2share.render_blocks(md2share.parse_markdown(source))
        html = md2share.build_html('测试', body, page_break_on_hr=True)
        self.assertEqual(html.count('<section class="print-section">'), 2)
        self.assertIn('<hr class="chapter-separator">', html)
        self.assertIn('代码里的标题', html)
        continuous = md2share.build_html('测试', body, paginate=False, page_break_on_hr=True)
        self.assertNotIn('beforeprint', continuous)
        self.assertNotIn('class="print-section"', continuous)
        self.assertIn('<hr>', continuous)

    def test_independent_heading_and_separator_breaks(self):
        source = '# 标题一\n\n正文\n\n# 标题二\n\n正文'
        html = md2share.build_html('测试', md2share.render_blocks(md2share.parse_markdown(source)))
        self.assertEqual(html.count('<section class="print-section">'), 2)
        source = '第一页\n\n---\n\n第二页\n\n```text\n---\n```'
        body = md2share.render_blocks(md2share.parse_markdown(source))
        default = md2share.build_html('测试', body)
        self.assertEqual(default.count('<section class="print-section">'), 1)
        self.assertIn('<hr>', default)
        html = md2share.build_html('测试', body, page_break_on_hr=True)
        self.assertEqual(html.count('<section class="print-section">'), 2)
        self.assertEqual(html.count('<hr class="chapter-separator">'), 1)
        self.assertIn('---', html)


if __name__ == '__main__':
    unittest.main()
