#!/usr/bin/env python3
"""将 Markdown 文件转为精美 HTML，再用 Chrome 打印 PDF
用法: python md2pdf.py <input.md> [output.pdf]
若省略 output.pdf，则输出到与 input.md 同名的 .pdf 文件
"""
import markdown, sys, os, subprocess

def md_to_pdf(md_path, pdf_path=None):
    if not pdf_path:
        pdf_path = os.path.splitext(md_path)[0] + '.pdf'
    
    html_path = os.path.splitext(md_path)[0] + '.html'
    
    # 读取 Markdown
    with open(md_path, 'r', encoding='utf-8') as f:
        md_content = f.read()
    
    # 转换 HTML
    md_html = markdown.markdown(
        md_content,
        extensions=['tables', 'fenced_code', 'nl2br']
    )
    
    css = """*{margin:0;padding:0;box-sizing:border-box}
body{font-family:"Microsoft YaHei","微软雅黑","SimHei",sans-serif;font-size:13px;color:#1a1a2e;line-height:1.8;max-width:210mm;margin:0 auto;padding:20mm 15mm;background:#fff}
h1{font-size:26px;color:#16213e;text-align:center;padding:20px 0 10px;border-bottom:3px solid #e94560;margin-bottom:24px}
h2{font-size:18px;color:#0f3460;border-left:4px solid #e94560;padding-left:12px;margin:32px 0 14px}
h3{font-size:15px;color:#16213e;margin:20px 0 10px}
h4{font-size:13px;color:#333;margin:14px 0 8px}
p{margin:6px 0}
table{width:100%;border-collapse:collapse;margin:14px 0;font-size:12px;page-break-inside:avoid}
th{background:#0f3460;color:#fff;padding:8px 10px;text-align:left;font-weight:bold}
td{padding:8px 10px;border-bottom:1px solid #ddd}
tr:nth-child(even) td{background:#f0f4f8}
ul,ol{margin:8px 0 8px 20px}
li{margin:4px 0}
pre{background:#1a1a2e;color:#e0e0e0;padding:14px;border-radius:6px;margin:12px 0;font-size:12px;page-break-inside:avoid;white-space:pre-wrap;word-wrap:break-word}
code{background:#f0f0f0;padding:2px 6px;border-radius:3px;font-family:"Consolas","Courier New",monospace}
pre code{background:none;padding:0}
blockquote{border-left:4px solid #e94560;margin:12px 0;padding:10px 16px;background:#fff5f5}
hr{border:none;border-top:1px solid #ddd;margin:24px 0}
@page{size:A4;margin:20mm 15mm}
strong{color:#e94560}
a{color:#0f3460}
"""
    
    html_template = f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><style>{css}</style></head><body>{md_html}</body></html>'
    
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_template)
    print(f"[OK] HTML → {html_path}")
    
    # Chrome 打印 PDF
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    chrome = None
    for p in chrome_paths:
        if os.path.exists(p):
            chrome = p
            break
    
    if not chrome:
        print("[ERR] 未找到 Chrome 或 Edge 浏览器")
        return False
    
    print(f"[RUN] {os.path.basename(chrome)} → PDF ...")
    cmd = [chrome, '--headless=new', '--disable-gpu', '--no-sandbox',
           f'--print-to-pdf={pdf_path}', '--no-pdf-header-footer',
           f'file:///{html_path.replace(chr(92), "/")}']
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode == 0 and os.path.exists(pdf_path):
        size_kb = os.path.getsize(pdf_path) / 1024
        print(f"[OK] PDF → {pdf_path} ({size_kb:.0f} KB)")
        return True
    else:
        print(f"[ERR] Chrome failed: {result.stderr}")
        return False

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python md2pdf.py <input.md> [output.pdf]")
        sys.exit(1)
    md_to_pdf(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
