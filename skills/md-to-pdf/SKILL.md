---
name: md-to-pdf
description: 将 Markdown 文件转换为精美排版的中文 PDF。当用户要求将报告、文档、分析等 Markdown 文件转成 PDF 格式时使用。触发关键词：转PDF、生成PDF、md转pdf、markdown转pdf、导出pdf、打印成pdf。
agent_created: true
---

# MD → PDF 转换技能

将 Markdown 文件转换为 A4 精排版 PDF，支持中文（微软雅黑/SimHei），内含表格、代码块、引用等样式。

## 工作流

### 步骤 1：检查前置条件

确认 `markdown` Python 包已安装：
```bash
python -c "import markdown; print('ok')"
```
若未安装，执行：
```bash
pip install markdown
```

### 步骤 2：复制并运行转换脚本

将 `scripts/md2pdf.py` 复制到目标 MD 文件所在目录，然后执行：

```bash
python md2pdf.py <输入.md> [输出.pdf]
```

脚本自动完成：
1. 读取 Markdown → 用 `markdown` 库转 HTML
2. 嵌入中文 CSS 样式（微软雅黑、A4 尺寸、专业配色）
3. 调用 Chrome headless 打印为 PDF

### 步骤 3：验证并交付

确认 PDF 文件已生成，使用 `open_result_view` 打开，再用 `deliver_attachments` 交付。

## 依赖

| 依赖 | 用途 | 安装 |
|------|------|------|
| Python `markdown` | MD → HTML 解析 | `pip install markdown` |
| Google Chrome | HTML → PDF 打印 | 系统自带 `C:\Program Files\Google\Chrome\Application\chrome.exe` |
| 中文字体 | 微软雅黑 msyh.ttc 或 SimHei simhei.ttf | 系统自带 `C:\Windows\Fonts\` |

## 配色方案

- 主题强调色: `#e94560`（红色）
- 标题深色: `#0f3460`
- 代码块背景: `#1a1a2e`
- 表格条纹: `#f0f4f8`

## 注意事项

- MD 文件必须 UTF-8 编码
- Chrome 使用 `--headless=new --no-sandbox` 模式
- 输出 PDF 为 A4 纸尺寸，页边距 20mm×15mm
- 表格和代码块设置了 `page-break-inside: avoid` 避免跨页断裂
