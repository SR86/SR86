"""Offline Markdown/LaTeX -> standalone HTML with native MathML."""
import html
import json
import os
from pathlib import Path
import re
import uuid
from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin
from latex2mathml.converter import convert

CSS='''body{max-width:960px;margin:24px auto;padding:0 22px 60px;font:16px/1.85 system-ui,"Microsoft YaHei",sans-serif;color:#203830;background:#fff}h1,h2,h3{line-height:1.4;color:#195f54}h1{font-size:28px}h2{font-size:22px;margin-top:32px}p{overflow-wrap:anywhere}table{border-collapse:collapse;display:block;overflow-x:auto;margin:18px 0;font-size:14px}th,td{border:1px solid #cddbd3;padding:9px 12px;min-width:95px;vertical-align:top}th{background:#edf4ef}blockquote{border-left:4px solid #a5bfae;margin-left:0;padding-left:18px;color:#547061}pre{overflow:auto;padding:12px;background:#f1f5f2}math{font-family:"Cambria Math","STIX Two Math",math,serif}math[display=block]{display:block;overflow-x:auto;padding:16px 0;margin:16px 0}.formula-error{color:#a23e26;background:#fff3ee;padding:10px;white-space:pre-wrap}.meta{font-size:13px;color:#65796e;border-bottom:1px solid #dce6df;padding-bottom:12px}a{color:#195f54}@media print{body{margin:0;font-size:11pt;max-width:none}table{display:table;width:100%}h2,h3{break-after:avoid}tr,math{break-inside:avoid}}'''

def render(text):
    counts={'formulas':0,'errors':0}
    def math_render(content, options):
        counts['formulas']+=1
        try:
            if len(content)>10000:raise ValueError()
            display='block' if options.get('display_mode') else 'inline'
            return convert(content,display=display)
        except Exception:
            counts['errors']+=1
            return '<code class="formula-error">公式需核对：'+html.escape(content)+'</code>'
    # Normalize common model delimiters outside fenced code blocks only.
    parts=re.split(r'(```[\s\S]*?```|~~~[\s\S]*?~~~)',text)
    for i in range(0,len(parts),2):
        parts[i]=re.sub(r'\\\[([\s\S]*?)\\\]',lambda m:'\n$$\n'+m[1].strip()+'\n$$\n',parts[i])
        parts[i]=re.sub(r'\\\((.*?)\\\)',lambda m:'$'+m[1]+'$',parts[i])
    md=MarkdownIt('commonmark',{'html':False}).enable('table')
    md.use(dollarmath_plugin,renderer=math_render)
    body=md.render(''.join(parts))
    warning=f"有 {counts['errors']} 处公式未成功排版，已明确标记，请核对原稿。" if counts['errors'] else '公式与表格已排版；内容和推导仍需人工核对。'
    document=('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
      '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;; base-uri &#39;none&#39;">'
      '<title>论文小站 · 阅读结果</title><style>'+CSS+'</style></head><body><p class="meta">论文小站 · '+html.escape(warning)+'</p>'+body+'</body></html>')
    return document,counts

def export_document(path):
    path=Path(path)
    text=path.read_text(encoding='utf-8-sig')
    document,counts=render(text)
    target=path.with_suffix('.html')
    temp=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(document,encoding='utf-8');os.replace(temp,target)
    path.with_suffix('.format.json').write_text(json.dumps(counts),encoding='utf-8')
    return target
