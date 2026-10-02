"""将本次会话参考文章导入本地（不伪装成供应商生成，不改变历史记录）。"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from analysis_app.store import Store
from analysis_app.expert_profiles import seed_experts
from analysis_main import DEFAULT_EXPERTS

store = Store(ROOT / 'backend/data/analysis')
seed_experts(store, DEFAULT_EXPERTS)
transcript = store.get('851eb85f-fb91-464f-a4ab-38900419892f', 'transcript')
old = store.get('programmer-reference-851eb85f', 'analysis')
expert = store.get('programmer', 'expert')
text = (ROOT / 'artifacts/ai-interview-edited-article.md').read_text()

def reference(match):
    minute, second = map(int, match.group(1).split(':'))
    index = min(range(len(transcript['segments'])), key=lambda i: abs(transcript['segments'][i]['start'] - (minute * 60 + second)))
    actual = int(transcript['segments'][index]['start'])
    return f'[{actual//60:02}:{actual%60:02}](#segment-{index+1})'

text = re.sub(r'@(\d\d:\d\d)@', reference, text)
# 重复导入时将离线视频链接还原成工作台段落定位。
def restore_anchor(match):
    second = int(match.group(1))
    index = min(range(len(transcript['segments'])), key=lambda i: abs(transcript['segments'][i]['start'] - second))
    return f'(#segment-{index+1})'
text = re.sub(r'\(https://www\.bilibili\.com/video/BV1xQKp6bE4U/\?t=(\d+)\)', restore_anchor, text)
article_sections = []
for index, chapter in enumerate(text.split('\n## ')[1:]):
    heading, body = chapter.split('\n', 1)
    article_sections.append({'id': f'article-{index+1}', 'title': heading.strip(), 'text': body.strip()})
corrections = []
for original, suggestion, reason in [
    ('VOM', '推理框架（具体名称待确认）', '原稿在讨论现成推理框架，但不能仅凭转写确定名称。'),
    ('SGN', '推理框架（具体名称待确认）', '缺少完整专名，文章使用类目称呼，保留原始字幕。'),
    ('LAURA', '某种微调方法（可能是 LoRA，待回听）', '上下文涉及训练和微调，仅保留候选，不作确定校正。'),
    ('这种熵增的这种这种感觉', '复杂度和“熵”的工程类比', '上下文表达感受，并未给出数学定义或证明。'),
]:
    ids = [i+1 for i, s in enumerate(transcript['segments']) if original in s['text']]
    if ids:
        corrections.append({'original': original, 'suggestion': suggestion, 'reason': reason, 'status': 'uncertain' if original != '这种熵增的这种这种感觉' else 'applied', 'evidence_ids': ids[:8]})
sections = [s for s in old['sections'] if s['id'] != 'actions']
report = {**{k: v for k, v in old.items() if k != 'id'}, 'expert_id': 'programmer', 'expert_version': expert['version'],
          'expert_snapshot': expert, 'profile': expert['profile'], 'schema_version': 2,
          'sections': sections, 'text': '\n\n'.join('## '+s['title']+'\n\n'+s['text'] for s in sections),
          'article': {'title': text.splitlines()[0].removeprefix('# '), 'text': text, 'sections': article_sections, 'corrections': corrections}}
store.put('analysis', report, 'programmer-reference-v3-851eb85f')
# 独立文档可直接打开视频时间定位。
def offline(match):
    index = int(match.group(1)) - 1
    return '(https://www.bilibili.com/video/BV1xQKp6bE4U/?t='+str(int(transcript['segments'][index]['start']))+')'
reference_file = ROOT / 'artifacts/ai-interview-edited-article.md'
reference_file.write_text(re.sub(r'\(#segment-(\d+)\)', offline, text))
(ROOT / 'artifacts/programmer-interview-analysis.md').write_text(re.sub(r'\(#segment-(\d+)\)', offline, report['text']))
print({'分析章节': len(sections), '文章章节': len(article_sections), '文章字数': len(text), '校准记录': len(corrections)})
