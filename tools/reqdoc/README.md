# 需求文档提取工具（只读、可重跑）

《个人成长档案系统需求文档 V1.0.docx》是需求来源，但它是二进制文档，且正文之外还有两张
用图片承载的架构图与数据关系图。这一组脚本负责把它的内容变成纯文本与可核对的产物，
供数据模型与实现比对使用（需求覆盖矩阵、规则条款都引用这里的文本）。

| 文件 | 作用 |
| --- | --- |
| `read_docx.py` | 按文档顺序导出行/段落/表格 |
| `inspect_docx_images.py` | 导出 `word/media` 里的图片并列出图片锚点 |
| `ocr_langs.ps1` / `ocr_images.ps1` / `ocr_tsv.ps1` | 调 Windows.Media.Ocr（`zh-Hans-CN`）识别图片，输出 `image/line/x/y/text` 的 TSV |
| `render_layout.py` | 把 OCR 词框按坐标还原成可读版面文本 |
| `out/doc_dump.txt` | **正文权威副本**：需求第 1–8 章的全部文字（271 段） |
| `out/ocr_words.tsv` | 图片文字识别的原始结果（412 行） |
| `out/layout_image*.txt` | 由 OCR 词框还原的两张架构图版面（第 4 章分层架构、第 5 章数据关系） |
| `out/docx_media/` | 从文档里导出的原始图片 |

注意：需求文档第 5 章正文只有一张分层示意图，图片承载的信息以 `out/layout_image2.txt` 为准。
脚本输出含中文，运行前请设 `PYTHONIOENCODING=utf-8`，否则重定向到文件会变成 GBK。
