#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
md2share.py — 本地 Markdown → 单文件 HTML / PDF 分享方案
=========================================================
本机可用工具：
  - Python 3（仅标准库；有 Pygments 时自动语法高亮）
  - PDF：优先无头 Chromium（含 Playwright 缓存副本，CSS 保真），缺失时回退 LibreOffice

用法：
  python3 md2share.py 输入.md                    # 生成同名 .html（本地图片自动 base64 内嵌）
  python3 md2share.py 输入.md --pdf              # 生成同名 .html + .pdf
  python3 md2share.py 输入.md --folder           # 导出到 ./<输入名>_export/ 文件夹（含图片/原文）
  python3 md2share.py 输入.md --folder --outdir ~/exports --pdf
"""
import argparse
import base64
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

try:
    from pygments import highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import get_lexer_by_name, TextLexer
    HAVE_PYGMENTS = True
except Exception:
    HAVE_PYGMENTS = False


# ---------------------------------------------------------------------------
# 图片处理上下文（单文件内嵌 base64 / 文件夹模式复制图片）
# ---------------------------------------------------------------------------

_IMG_CTX = {
    'base_dir': Path('.'),
    'embed': True,
    'out_dir': '.',
    'copied': {},   # 源路径 -> 输出相对路径
}


def _reset_image_context(base_dir: Path, embed: bool):
    _IMG_CTX['base_dir'] = base_dir
    _IMG_CTX['embed'] = embed
    _IMG_CTX['copied'] = {}


def _mime_for(suffix: str) -> str:
    suffix = suffix.lower()
    return {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.svg': 'image/svg+xml',
        '.bmp': 'image/bmp',
        '.ico': 'image/x-icon',
        '.avif': 'image/avif',
    }.get(suffix, 'application/octet-stream')


def _copy_image_to_output(p: Path) -> str:
    """把本地图片复制到输出目录的 images/ 下，返回相对 HTML 的路径。"""
    src_key = str(p.resolve())
    if src_key in _IMG_CTX['copied']:
        return _IMG_CTX['copied'][src_key]

    # 尽可能保留 md 旁边的目录结构，避免同名图片互相覆盖
    try:
        rel = p.relative_to(_IMG_CTX['base_dir'])
    except ValueError:
        rel = Path(p.name)
    clean_parts = [re.sub(r'[^A-Za-z0-9._\-\u4e00-\u9fff]+', '_', part)
                   for part in rel.parts if part not in ('', '.', '..')]
    rel_out = Path('images') / Path(*clean_parts)
    dest = Path(_IMG_CTX['out_dir']) / rel_out
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dest)
    _IMG_CTX['copied'][src_key] = rel_out.as_posix()
    return rel_out.as_posix()


def _image_html(target: str, alt: str) -> str:
    """根据图片目标生成 <img>，单文件模式转 data URI，文件夹模式复制到 images/。"""
    target = target.strip()
    # 去掉 Markdown 常见的 "title" 后缀
    m = re.match(r'^(\S+?)(?:\s+["\'].*["\'])?$', target)
    if m:
        target = m.group(1)
    if target.startswith('<') and target.endswith('>'):
        target = target[1:-1]

    attr_alt = html.escape(alt, quote=True)
    is_remote = bool(re.match(r'^(https?://|//|data:|mailto:|#)', target, re.I))
    if is_remote:
        return f'<img src="{html.escape(target, quote=True)}" alt="{attr_alt}" loading="lazy">'

    p = Path(target)
    if not p.is_absolute():
        p = _IMG_CTX['base_dir'] / p
    if not p.exists() or not p.is_file():
        # 找不到就保留原路径，至少能看到占位
        return f'<img src="{html.escape(target, quote=True)}" alt="{attr_alt}" loading="lazy">'

    if _IMG_CTX['embed']:
        try:
            data = p.read_bytes()
        except Exception:
            return f'<img src="{html.escape(target, quote=True)}" alt="{attr_alt}" loading="lazy">'
        mime = _mime_for(p.suffix)
        uri = f'data:{mime};base64,{base64.b64encode(data).decode("ascii")}'
        return f'<img src="{uri}" alt="{attr_alt}" loading="lazy">'

    rel = _copy_image_to_output(p)
    return f'<img src="{html.escape(rel, quote=True)}" alt="{attr_alt}" loading="lazy">'


# ---------------------------------------------------------------------------
# Markdown 解析（支持标题、段落、引用、代码块、表格、列表、分隔线、图片）
# ---------------------------------------------------------------------------

def esc(text: str) -> str:
    return html.escape(text, quote=False)


def inline_md(text: str) -> str:
    """行内格式化：`code`、**bold**、*italic*、[text](url)、![alt](img)。"""
    # 先处理行内代码，避免代码内容被后续规则误转
    code_spans = []

    def stash(m):
        code_spans.append(esc(m.group(1)))
        return f"\x00CODE{len(code_spans)-1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)

    # 图片优先于链接（避免 ! 和链接互相干扰）
    def img_repl(m):
        return _image_html(m.group(2), m.group(1) or '')

    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", img_repl, text)

    # 链接（放在加粗之前，避免 URL 中的 * 干扰）
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    # 加粗
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    # 斜体
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", text)

    def unstash(m):
        return f"<code>{code_spans[int(m.group(1))]}</code>"

    text = re.sub(r"\x00CODE(\d+)\x00", unstash, text)
    return text


def is_block_start(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    if s.startswith('```'):
        return True
    if s.startswith('#'):
        return True
    if s.startswith('>'):
        return True
    if s.startswith('|'):
        return True
    if re.match(r'^(---+|\*\*\*+|___+)\s*$', s):
        return True
    if re.match(r'^(\s*[-*+]\s+|\s*\d+\.\s+)', s):
        return True
    return False


def render_code(lang: str, code: str) -> str:
    code = code.rstrip('\n')
    if HAVE_PYGMENTS and lang:
        try:
            lexer = get_lexer_by_name(lang)
        except Exception:
            lexer = TextLexer()
        try:
            body = highlight(code, lexer, HtmlFormatter(nowrap=True, style='friendly'))
        except Exception:
            body = esc(code)
    elif HAVE_PYGMENTS:
        try:
            body = highlight(code, TextLexer(), HtmlFormatter(nowrap=True, style='friendly'))
        except Exception:
            body = esc(code)
    else:
        body = esc(code)
    lang_cls = f' class="language-{esc(lang)}"' if lang else ''
    return f'<pre class="code-block"><code{lang_cls}>{body}</code></pre>\n'


def render_table(rows):
    if not rows:
        return ''
    rows = [r.strip() for r in rows]
    parsed = []
    for r in rows:
        cell_text = r.strip()
        if cell_text.startswith('|'):
            cell_text = cell_text[1:]
        if cell_text.endswith('|'):
            cell_text = cell_text[:-1]
        parsed.append([c.strip() for c in cell_text.split('|')])
    if len(parsed) >= 2 and all(re.match(r'^:?-{2,}:?$', c) or re.match(r'^:?-+$', c) for c in parsed[1]):
        header = parsed[0]
        body = parsed[2:]
        thead = '<thead><tr>' + ''.join(f'<th>{inline_md(c)}</th>' for c in header) + '</tr></thead>\n'
        tbody = '<tbody>\n' + ''.join(
            '<tr>' + ''.join(f'<td>{inline_md(c)}</td>' for c in row) + '</tr>\n' for row in body
        ) + '</tbody>\n'
    else:
        thead = ''
        tbody = '<tbody>\n' + ''.join(
            '<tr>' + ''.join(f'<td>{inline_md(c)}</td>' for c in row) + '</tr>\n' for row in parsed
        ) + '</tbody>\n'
    return f'<div class="table-wrap"><table>\n{thead}{tbody}</table></div>\n'


def parse_markdown(text: str):
    lines = text.splitlines()
    blocks = []
    i = 0
    n = len(lines)

    while i < n:
        s = lines[i].strip()

        # 围栏代码块
        if s.startswith('```'):
            lang = s[3:].strip()
            i += 1
            code_lines = []
            while i < n and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            if i < n:
                i += 1  # 跳过结束围栏
            blocks.append(('code', lang, '\n'.join(code_lines)))
            continue

        # 引用块
        if s.startswith('>'):
            quote_lines = []
            while i < n and lines[i].strip().startswith('>'):
                content = lines[i].strip()
                if content.startswith('>'):
                    content = content[1:].strip()
                quote_lines.append(content)
                i += 1
            blocks.append(('quote', quote_lines))
            continue

        # 表格
        if s.startswith('|'):
            table_rows = []
            while i < n and lines[i].strip().startswith('|'):
                table_rows.append(lines[i])
                i += 1
            blocks.append(('table', table_rows))
            continue

        # 标题
        m = re.match(r'^(#{1,6})\s+(.*)$', s)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            blocks.append(('heading', level, text))
            i += 1
            continue

        # 分隔线
        if re.match(r'^(---+|\*\*\*+|___+)\s*$', s):
            blocks.append(('hr',))
            i += 1
            continue

        # 列表（简单的一层列表）
        lm = re.match(r'^(\s*[-*+]|\s*\d+\.)\s+(.*)$', s)
        if lm:
            items = []
            ordered = bool(re.match(r'^\s*\d+\.', s))
            while i < n:
                line = lines[i]
                m2 = re.match(r'^(\s*)([-*+]|\d+\.)\s+(.*)$', line)
                if not m2 or bool(re.match(r'\d+\.', m2.group(2))) != ordered:
                    break
                marker, content = m2.group(2), m2.group(3)
                i += 1
                # 无空行的普通续行属于当前列表项；保留 Markdown 双空格硬换行。
                while i < n and lines[i].strip() and not is_block_start(lines[i]):
                    separator = '<br>\n' if content.endswith('  ') else ' '
                    content = content.rstrip() + separator + lines[i].lstrip()
                    i += 1
                items.append((marker, content.rstrip()))
            blocks.append(('list', ordered, items))
            continue

        # 普通段落（允许段落里含图片；单张图片也按段落处理）
        para = []
        while i < n:
            cur = lines[i].strip()
            if cur == '' or is_block_start(cur):
                break
            para.append(cur)
            i += 1
        while i < n and lines[i].strip() == '':
            i += 1
        if para:
            blocks.append(('para', ' '.join(para)))
            continue
        # 没有普通段落时，说明刚才只是连续空行；不要额外跳过下一行
        # （否则会吞掉紧跟空行后的代码块/标题/引用等块级元素）
        continue

    return blocks


def render_blocks(blocks) -> str:
    out = []
    for block in blocks:
        kind = block[0]
        if kind == 'code':
            _, lang, code = block
            out.append(render_code(lang, code))
        elif kind == 'quote':
            _, lines = block
            parts = []
            for line in lines:
                if line:
                    parts.append(f'<p>{inline_md(line)}</p>')
            out.append('<blockquote>\n' + '\n'.join(parts) + '\n</blockquote>\n')
        elif kind == 'table':
            out.append(render_table(block[1]))
        elif kind == 'heading':
            _, level, text = block
            out.append(f'<h{level}>{inline_md(text)}</h{level}>\n')
        elif kind == 'hr':
            out.append('<hr>\n')
        elif kind == 'list':
            _, ordered, items = block
            tag = 'ol' if ordered else 'ul'
            body = ''.join(f'<li>{inline_md(text)}</li>\n' for _, text in items)
            start = f' start="{int(items[0][0][:-1])}"' if ordered and int(items[0][0][:-1]) != 1 else ''
            out.append(f'<{tag}{start}>\n{body}</{tag}>\n')
        elif kind == 'para':
            _, text = block
            out.append(f'<p>{inline_md(text)}</p>\n')
    return '\n'.join(out)


# ---------------------------------------------------------------------------
# 页面模板
# ---------------------------------------------------------------------------

CSS = """
:root {
  --text: #24292f;
  --muted: #57606a;
  --bg: #ffffff;
  --panel: #f6f8fa;
  --border: #d0d7de;
  --accent: #0969da;
  --quote-bg: #f6f8fa;
  --code-bg: #f6f8fa;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  padding: 2.2rem 1.2rem 4rem;
  background: var(--bg);
  color: var(--text);
  font-family: "Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans CN", "WenQuanYi Micro Hei", "Microsoft YaHei", "PingFang SC", -apple-system, sans-serif;
  font-size: 16px;
  line-height: 1.75;
}
main {
  max-width: 900px;
  margin: 0 auto;
  background: var(--bg);
}
h1, h2, h3, h4, h5, h6 {
  margin: 1.8em 0 0.7em;
  line-height: 1.3;
  font-weight: 700;
}
h1 { font-size: 1.9em; border-bottom: 1px solid var(--border); padding-bottom: .35em; margin-top: .4em; }
h2 { font-size: 1.45em; border-bottom: 1px solid var(--border); padding-bottom: .3em; margin-top: 2em; }
h3 { font-size: 1.2em; }
h4 { font-size: 1.05em; }
p { margin: 0.8em 0; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
blockquote {
  margin: 1em 0;
  padding: .6em 1.1em;
  border-left: 4px solid var(--accent);
  background: var(--quote-bg);
  color: var(--muted);
  border-radius: 6px;
}
blockquote p { margin: .35em 0; }
code {
  font-family: "JetBrains Mono", "Fira Code", "Noto Sans Mono CJK SC", Consolas, "Liberation Mono", monospace;
  font-size: .875em;
  background: rgba(175,184,193,.2);
  padding: .15em .4em;
  border-radius: 4px;
}
pre.code-block {
  margin: 1em 0;
  padding: .9em 1.1em;
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow-x: auto;
  line-height: 1.55;
}
pre.code-block code {
  background: transparent;
  padding: 0;
  font-size: 1em;
}
img {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 1em auto;
  border-radius: 6px;
}
table {
  width: 100%;
  border-collapse: collapse;
  margin: 1em 0;
  font-size: .95em;
}
th, td {
  border: 1px solid var(--border);
  padding: .5em .8em;
  text-align: left;
  vertical-align: top;
}
th { background: var(--panel); font-weight: 700; }
.table-wrap { overflow-x: auto; }
hr {
  border: none;
  border-top: 2px solid var(--border);
  margin: 2.2em 0;
}
ul, ol { padding-left: 1.6em; margin: .8em 0; }
li { margin: .3em 0; }

@media print {
  body { padding: 0; font-size: 11pt; line-height: 1.6; }
  main { max-width: 100%; }
  h1 { font-size: 1.6em; }
  h2 { font-size: 1.3em; margin-top: 1.4em; }
  h3 { font-size: 1.1em; }
  pre.code-block { break-inside: avoid; white-space: pre-wrap; word-break: break-word; font-size: 10pt; line-height: 1.5; }
  h1, h2, h3, h4, h5, h6 { break-after: avoid; }
  a { color: inherit; }
  blockquote { break-inside: avoid; }
  img { break-inside: avoid; max-width: 100%; max-height: 88vh; width: auto; }
  table { font-size: 9pt; }
  tr { break-inside: avoid; }
}
@page { size: A4; margin: 14mm 12mm; }
"""


def pygments_css() -> str:
    if not HAVE_PYGMENTS:
        return ''
    try:
        return HtmlFormatter(style='friendly').get_style_defs('.code-block')
    except Exception:
        return ''


PRINT_LAYOUT = """
<style>
@media print {
  body { font-size:10pt; line-height:1.48; }
  h1 { margin:0 0 4mm; font-size:19pt; }
  h2 { margin:4mm 0 2mm; font-size:12pt; }
  h3 { margin:3mm 0 1mm; font-size:11pt; }
  p { margin:2mm 0; }
  td, th { padding:1.7mm 2mm; }
  pre.code-block { font-size:8.4pt; line-height:1.3; padding:2.5mm; }
  .print-section { break-before:auto; }
  .print-section ~ .print-section { break-before:page; }
  .chapter-separator { display:none; }
  img { max-height:220mm; object-fit:contain; margin:2mm auto; }
}
@page { @bottom-right { content:counter(page); font-size:8pt; color:#64748b; } }
</style>
<script>
// Fit images only; long text retains its font size and can continue onto another page.
const fittedImages = new Map();
window.addEventListener('beforeprint', () => {
  const ruler = document.createElement('div');
  ruler.style.cssText = 'height:269mm;position:absolute;visibility:hidden';
  document.body.append(ruler);
  const pageHeight = ruler.getBoundingClientRect().height - 8;
  ruler.remove();
  document.querySelectorAll('.print-section').forEach(section => {
    const images = [...section.querySelectorAll('img')];
    for (let attempt = 0; attempt < 4; attempt++) {
      const overflow = section.getBoundingClientRect().height - pageHeight;
      if (overflow <= 0 || !images.length) break;
      const total = images.reduce((sum, img) => sum + img.getBoundingClientRect().height, 0);
      const scale = Math.max(0, (total - overflow - 8) / total);
      let changed = false;
      images.forEach(img => {
        const height = img.getBoundingClientRect().height;
        const next = Math.max(96, height * scale);
        if (next >= height) return;
        if (!fittedImages.has(img)) fittedImages.set(img, img.style.maxHeight);
        img.style.maxHeight = next + 'px';
        changed = true;
      });
      if (!changed) break;
    }
  });
});
window.addEventListener('afterprint', () => {
  fittedImages.forEach((value, img) => { img.style.maxHeight = value; });
  fittedImages.clear();
});
</script>
"""


def print_sections(body_html: str) -> str:
    """一级标题和分割线均分页；相邻标记不生成空白页。"""
    sections = []
    for part in re.split(r'(<hr>)|(?=<h1>)', body_html):
        if not part or not part.strip():
            continue
        if part == '<hr>':
            sections.append('<hr class="chapter-separator">')
        else:
            sections.append(f'<section class="print-section">{part.strip()}</section>')
    return '\n'.join(sections)


def build_html(title: str, body_html: str, paginate: bool = True) -> str:
    extra_css = pygments_css()
    layout = PRINT_LAYOUT if paginate else ''
    if paginate:
        body_html = print_sections(body_html)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>
{CSS}
{extra_css}
</style>
{layout}
</head>
<body>
<main>
{body_html}
</main>
</body>
</html>
"""


def get_title(text: str, fallback: str) -> str:
    m = re.search(r'^#\s+(.+)$', text, re.M)
    if m:
        return m.group(1).strip()
    return fallback


def find_chrome() -> Optional[str]:
    """定位可用于打印 PDF 的无头 Chromium（含 Playwright 缓存的副本）。"""
    candidates = []
    pw = Path.home() / '.cache' / 'ms-playwright'
    if pw.is_dir():
        candidates += sorted(pw.glob('chromium_headless_shell-*/chrome-*/chrome-headless-shell'))
        candidates += sorted(pw.glob('chromium_headless_shell-*/chrome-*/headless_shell'))
        candidates += sorted(pw.glob('chromium-*/chrome-linux*/chrome'))
    for name in ('chromium', 'chromium-browser', 'google-chrome', 'google-chrome-stable', 'microsoft-edge'):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def html_to_pdf(html_path: Path, pdf_path: Path) -> str:
    """HTML → PDF；优先无头 Chromium（CSS 保真），缺失时回退 LibreOffice。返回所用引擎。"""
    chrome = find_chrome()
    if chrome:
        cmd = [
            chrome, '--headless', '--disable-gpu', '--no-sandbox',
            '--no-pdf-header-footer', '--virtual-time-budget=15000',
            f'--print-to-pdf={pdf_path}', f'file://{html_path.resolve()}',
        ]
        print('[RUN] ' + ' '.join(cmd))
        try:
            with tempfile.TemporaryDirectory(prefix='md2share-chrome-') as profile:
                cmd.insert(1, f'--user-data-dir={profile}')
                cmd.insert(1, '--disable-dev-shm-usage')
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except Exception as e:
            print(f'[WARN] Chromium PDF 失败，回退 LibreOffice: {e}')
            r = None
        if r is not None and r.returncode == 0 and pdf_path.exists():
            return 'chromium'
        if r is not None:
            print(f'[WARN] Chromium 返回 {r.returncode}，回退 LibreOffice:\n{r.stderr}')
    cmd = [
        'libreoffice', '--headless', '--convert-to', 'pdf',
        '--outdir', str(pdf_path.parent), str(html_path)
    ]
    print('[RUN] ' + ' '.join(cmd))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception as e:
        sys.exit(f'PDF 转换失败: {e}')
    if r.returncode != 0:
        sys.exit(f'PDF 转换失败（LibreOffice 返回 {r.returncode}）:\n{r.stderr}')
    generated_pdf = pdf_path.parent / (html_path.stem + '.pdf')
    if generated_pdf != pdf_path and generated_pdf.exists():
        os.replace(generated_pdf, pdf_path)
    return 'libreoffice'


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Markdown → HTML/PDF，默认生成单文件 HTML（图片自动 base64 内嵌）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例：
  md2share.py 指南.md                 # 单文件 HTML，图片内嵌
  md2share.py 指南.md --pdf           # 单文件 HTML + PDF
  md2share.py 指南.md --folder        # 导出到 ./<指南>_export/ 文件夹
  md2share.py 指南.md --folder --outdir ~/exports --pdf
'''
    )
    parser.add_argument('input', help='输入 .md 文件')
    parser.add_argument('-o', '--output', help='输出 .html 路径；--pdf-only 时为 .pdf 路径；--folder 时为导出目录')
    parser.add_argument('--continuous', action='store_true', help='PDF 连续排版，不按一级标题或分割线分页，也不自动适配图片')
    parser.add_argument('--pdf', action='store_true', help='同时生成 PDF（优先无头 Chromium，缺失时回退 LibreOffice）')
    parser.add_argument('--pdf-only', action='store_true', help='仅生成 PDF，-o 可指定 PDF 路径；临时 HTML 自动清理')
    parser.add_argument('--folder', action='store_true', help='导出为独立文件夹（index.html + 图片 + 原 md + 可选 PDF）')
    parser.add_argument('--outdir', default='.', help='--folder 时导出文件夹的父目录（默认当前目录）')
    parser.add_argument('--no-embed-images', action='store_true', help='不把本地图片转成 base64，改用相对路径引用')
    parser.add_argument('--no-pygments', action='store_true', help='禁用 Pygments 语法高亮')
    args = parser.parse_args(argv)

    if args.pdf_only and (args.folder or args.no_embed_images):
        parser.error('--pdf-only 不支持 --folder 或 --no-embed-images')

    src = Path(args.input)
    if not src.exists():
        sys.exit(f'找不到输入文件: {src}')

    text = src.read_text(encoding='utf-8')
    title = get_title(text, src.stem)
    if args.no_pygments:
        global HAVE_PYGMENTS
        HAVE_PYGMENTS = False

    if args.pdf_only:
        pdf_path = (Path(args.output) if args.output else src.with_suffix('.pdf')).resolve()
        if pdf_path.suffix.lower() != '.pdf' or pdf_path == src.resolve():
            parser.error('--pdf-only 的输出须为 .pdf 文件且不能覆盖输入')
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='md2share-pdf-') as folder:
            html_path = Path(folder) / (pdf_path.stem + '.html')
            _IMG_CTX['out_dir'] = folder
            _reset_image_context(src.parent, True)
            body = render_blocks(parse_markdown(text))
            html_path.write_text(build_html(title, body, paginate=not args.continuous), encoding='utf-8')
            engine = html_to_pdf(html_path, pdf_path)
            if not pdf_path.exists():
                sys.exit('未找到生成的 PDF，请检查转换输出。')
        print(f'[OK] PDF ({engine}): {pdf_path}')
        return 0

    # 决定输出位置与图片模式
    if args.folder:
        if args.output:
            export_dir = Path(args.output)
        else:
            export_dir = Path(args.outdir) / f'{src.stem}_export'
        export_dir.mkdir(parents=True, exist_ok=True)
        html_path = export_dir / 'index.html'
        pdf_path = export_dir / f'{src.stem}.pdf'
        embed = False
        # 原 md 也放进任务文件夹，方便后续修改
        shutil.copy2(src, export_dir / f'{src.stem}.md')
    else:
        html_path = Path(args.output) if args.output else src.with_suffix('.html')
        pdf_path = html_path.with_suffix('.pdf')
        embed = not args.no_embed_images
        html_path.parent.mkdir(parents=True, exist_ok=True)

    _IMG_CTX['out_dir'] = str(html_path.parent)
    _reset_image_context(src.parent, embed)

    blocks = parse_markdown(text)
    body = render_blocks(blocks)
    html_path.write_text(build_html(title, body, paginate=not args.continuous), encoding='utf-8')
    print(f'[OK] HTML: {html_path}')
    if args.folder and _IMG_CTX['copied']:
        print(f'[OK] 图片: {len(_IMG_CTX["copied"])} 张复制到 {html_path.parent / "images"}')

    if args.pdf:
        engine = html_to_pdf(html_path, pdf_path)
        if not pdf_path.exists():
            sys.exit('未找到生成的 PDF，请检查转换输出。')
        print(f'[OK] PDF ({engine}): {pdf_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
