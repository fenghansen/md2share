# md2share

把本地 Markdown 转成便于分享的 HTML 或 PDF。默认将本地图片内嵌到单个 HTML，支持代码高亮、表格和按一级标题分页。

## 安装

需要 Python 3.10 或更新版本。通过 GitHub 安装（私有仓库需先配置有访问权限的 SSH 密钥）：

```bash
python -m pip install git+ssh://git@github.com/fenghansen/md2share.git
```

也可以在源码目录安装：

```bash
python -m pip install .
# 可选：代码语法高亮
python -m pip install '.[highlight]'
```

也可安装构建好的 wheel：`python -m pip install dist/md2share-0.1.0-py3-none-any.whl`。

## 使用

```bash
md2share 文档.md                           # 单文件 HTML，本地图片内嵌
md2share 文档.md --pdf                     # HTML + PDF
md2share 文档.md --pdf-only -o 分享.pdf     # 只导出 PDF
md2share 文档.md --pdf-only --continuous   # 连续排版
md2share 文档.md --folder                  # 原文、HTML 和图片一起导出
md2share --help
```

HTML 导出无需额外 Python 依赖。PDF 需要系统安装 Chromium、Google Chrome 或 LibreOffice；也会查找 Linux 下的 Playwright Chromium 缓存。推荐在 Linux 上使用 Chromium，并安装中文字体。LibreOffice 是回退引擎，不执行图片自动缩放脚本；其他系统尚未验证。

PDF 默认按一级标题另起一页并尝试缩小图片，长章节仍可跨页。`--continuous` 关闭章节分页和图片自动适配。远程图片保留 URL，不会下载内嵌。

支持 Markdown 子集：标题、段落、引用、围栏代码块、表格、单层列表、分隔线、链接和图片；不保证完整 CommonMark 兼容。输入按可信本地文档处理，输出保留原始 HTML，不提供 HTML 清洗。

## 开发

```bash
python -m unittest -v
python -m pip wheel --no-deps . -w dist
```
