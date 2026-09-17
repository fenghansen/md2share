# md2share

把本地 Markdown 转成便于分享的 HTML 或 PDF。默认将本地图片内嵌到单个 HTML，支持代码高亮、表格和按一级标题分页，可选分割线强制分页。

## 安装

需要 Python 3.8 或更新版本。通过 PyPI 安装：

```bash
python -m pip install md2share
# 可选：代码语法高亮
python -m pip install 'md2share[highlight]'
```

[PyPI 项目页](https://pypi.org/project/md2share/)

也可通过 GitHub 安装（私有仓库需先配置有访问权限的 SSH 密钥）：

```bash
python -m pip install git+ssh://git@github.com/fenghansen/md2share.git
```

也可以在源码目录安装：

```bash
python -m pip install .
# 可选：代码语法高亮
python -m pip install '.[highlight]'
```

也可安装构建好的 wheel：`python -m pip install dist/md2share-0.1.2-py3-none-any.whl`。

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

PDF 默认只有一级标题自动分页，分割线保持可见且不强制分页。添加 `--page-break-on-hr` 后，Markdown 分割线（如 `---`）也会强制分页且在 PDF 中隐藏；它不依赖标题，与一级标题紧邻时不会产生额外空白页。程序尝试缩小页内图片，长段内容仍可跨页。`--continuous` 优先于 `--page-break-on-hr`，关闭标题/分割线分页和图片自动适配。远程图片保留 URL，不会下载内嵌。

支持 Markdown 子集：标题、段落、引用、围栏代码块、表格、单层列表、分隔线、链接和图片；不保证完整 CommonMark 兼容。输入按可信本地文档处理，输出保留原始 HTML，不提供 HTML 清洗。

## 开发

```bash
python -m unittest -v
python -m pip wheel --no-deps . -w dist
```

## 分页示例

[示例 Markdown](https://github.com/fenghansen/md2share/blob/main/examples/pagination.md) 演示启用 `--page-break-on-hr` 后的一级标题分页、分割线独立分页及两者相邻不产生空白页。默认不加该参数时，示例为 3 页；启用后为 4 页。

```bash
md2share examples/pagination.md --pdf --page-break-on-hr
# 可选：用 Poppler 把 PDF 转成逐页 JPG
pdftoppm -jpeg -r 110 examples/pagination.pdf examples/page
```

渲染结果：[第 1 页](https://github.com/fenghansen/md2share/blob/main/examples/page-1.jpg) · [第 2 页](https://github.com/fenghansen/md2share/blob/main/examples/page-2.jpg) · [第 3 页](https://github.com/fenghansen/md2share/blob/main/examples/page-3.jpg) · [第 4 页](https://github.com/fenghansen/md2share/blob/main/examples/page-4.jpg)

![启用 --page-break-on-hr 后的 4 页渲染总览](https://raw.githubusercontent.com/fenghansen/md2share/main/examples/pagination-overview.jpg)
