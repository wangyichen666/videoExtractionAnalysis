"""共享专家引擎：完整分片 → 证据/校准/成文 → 专家章节与文章编排。"""
import json
import re
import hashlib
from .expert_profiles import get_profile

CONTRACT_VERSION = 2
SOURCE_LIMIT = 6000
SYNTHESIS_LIMIT = 32000


def source_chunks(segments, limit=SOURCE_LIMIT):
    chunks, entries, size = [], [], 0
    for index, segment in enumerate(segments, 1):
        text = segment['text']
        for offset in range(0, max(len(text), 1), limit - 100):
            line = f"[S{index}] [{segment['start']:.1f}s] {text[offset:offset+limit-100]}"
            if entries and size + len(line) + 1 > limit:
                chunks.append(entries)
                entries, size = [], 0
            entries.append((index, line))
            size += len(line) + 1
    if entries:
        chunks.append(entries)
    return chunks


def read_json(raw):
    value = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip())
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        # 仅补完整顶层对象缺失的最后一个括号，内部 JSON 必须已经完整；不补正文或猜字段。
        if value.startswith('{') and value.endswith('}'):
            try:
                return json.loads(value + '}')
            except ValueError:
                pass
        raise ValueError('模型未返回有效 JSON，请使用支持结构化输出的模型后重试')


def structured_call(material, instruction, validator, call):
    # 至多一次修复请求，失败明确结束，不把不完整对象存成成功报告。
    last_error = None
    for attempt in range(2):
        repair = f'\n上次输出未符合约定：{last_error}。请严格按 JSON 结构及当前片段段号重新生成。' if attempt else ''
        raw = call(material, instruction + repair, 7000)
        try:
            return validator(raw)
        except ValueError as error:
            last_error = str(error)
    raise ValueError(last_error)


def require_text(value, maximum, label):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        if isinstance(value, str) and len(value) > maximum:
            raise ValueError(f'模型{label}实际{len(value)}字符，超过{maximum}字符；请合并重复、缩短解释后重试')
        raise ValueError(f'模型{label}为空或超出长度约定，请重试')
    return value.strip()


def validate_ids(ids, allowed):
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 1000
            or any(type(i) is not int or i not in allowed for i in ids)):
        raise ValueError('模型证据引用不属于当前文字片段，请重试')
    return list(dict.fromkeys(ids))


def parse_chunk(raw, entries, sections):
    data = read_json(raw)
    if not isinstance(data, dict):
        raise ValueError('模型输出应包含 notes 和 article 对象，请重试')
    allowed = {i for i, _ in entries}
    notes = data.get('notes')
    if not isinstance(notes, list) or not 1 <= len(notes) <= 40:
        raise ValueError('模型证据整理格式异常：每片段需 1 至 40 条笔记')
    categories = {k for k, _, _ in sections}
    for note in notes:
        if not isinstance(note, dict) or note.get('category') not in categories:
            raise ValueError('模型返回了当前专家未定义的章节，请重试')
        note['content'] = require_text(note.get('content'), 800, '证据笔记')
        note['evidence_ids'] = validate_ids(note.get('evidence_ids'), allowed)
    article = data.get('article')
    if not isinstance(article, dict):
        raise ValueError('模型没有生成整理文章，请重试')
    article['title'] = require_text(article.get('title'), 100, '文章章节标题')
    paragraphs = article.get('paragraphs')
    if not isinstance(paragraphs, list) or not 1 <= len(paragraphs) <= 20:
        raise ValueError('模型文章段落格式异常，请重试')
    for paragraph in paragraphs:
        if not isinstance(paragraph, dict):
            raise ValueError('模型文章段落格式异常，请重试')
        paragraph['text'] = require_text(paragraph.get('text'), 2500, '文章段落')
        paragraph['evidence_ids'] = validate_ids(paragraph.get('evidence_ids'), allowed)
    corrections = data.get('corrections', article.get('corrections', []))
    if not isinstance(corrections, list) or len(corrections) > 20:
        raise ValueError('模型校准记录格式异常，请重试')
    valid_corrections, warnings = [], []
    for correction in corrections:
        if not isinstance(correction, dict) or correction.get('status') not in ('applied', 'uncertain'):
            raise ValueError('模型校准记录缺少可靠性说明，请重试')
        for key in ('original', 'suggestion', 'reason'):
            correction[key] = require_text(correction.get(key), 500, '校准记录')
        correction['evidence_ids'] = validate_ids(correction.get('evidence_ids'), allowed)
        evidence = ''.join(line.split('] ', 2)[-1] for i, line in entries if i in correction['evidence_ids'])
        if correction['original'] not in evidence:
            warnings.append({'original': correction['original'], 'reason': '原词与引用字幕无法逐字对齐，未采用该校准记录', 'evidence_ids': correction['evidence_ids']})
            continue
        valid_corrections.append(correction)
    article['validation_warnings'] = warnings
    return notes, article, valid_corrections


def normalize_source_markers(text):
    # 中文模型可能使用全角括号，仍视为结构引用并严格校验，不让其变成无法点击的文字。
    return re.sub(r'[【［]S(\d+)[】］]', r'[S\1]', text)


def bind_sources(text, segments, allowed):
    text = normalize_source_markers(text)
    def replace(match):
        index = int(match.group(1))
        if index not in allowed or not 1 <= index <= len(segments):
            raise ValueError('模型报告引用了未提供的原文段落，请重试')
        seconds = int(segments[index - 1]['start'])
        return f'[{seconds//60:02}:{seconds%60:02}](#segment-{index})'
    # LLM 如自行为标记加链接，仍以服务端原文时间定位为准。
    bound = re.sub(r'\[S(\d+)\](?:\([^)]*\))?', replace, text)
    # 同时拒绝模型绕过 S 标记直接构造的页面锚点。
    for index in re.findall(r'#segment-(\d+)', bound):
        if int(index) not in allowed:
            raise ValueError('模型报告引用了未提供的原文段落，请重试')
    return bound


def edit_article(material, changes, entries, call):
    instruction = ('文章编辑：只输出 JSON {"title":"主题标题","paragraphs":[{"text":"书面自然段","evidence_ids":[整数段号]}]}。'
        '把材料写成围绕观点展开的文章，而非逐轮复述对话。直接表达主题、解释论证、接续原视频例子；'
        '禁止逐轮转述：不得写主持人问/嘉宾说/他说/本段讨论，不以主持人或嘉宾作为每段主语。'
        '写法示范（X/Y仅为占位符，不能写进正文）：不要“主持人问X，嘉宾说Y”，改为“X的关键在于Y。随后以原视频实例展开解释”。'
        '删掉开场寒暄、播放量、重复和口头填充；个人体验可写“在讨论者的使用体验中”，保留条件、分歧和预测语气。'
        '不能补充视频以外的知识、例子或事实；专名不确定时用模糊称呼并注明原稿歧义，不猜名称。'
        '参考校准建议，但不能把 uncertain 候选写成确定事实。各段只列1-3个真实原文段号；'
        '全片写600-1200个汉字，最多1800字符（包括标点），4-10个自然段，每段80-350字，不用要点列表；短材料相应缩短。')
    def validate(raw):
        data = read_json(raw)
        if not isinstance(data, dict):
            raise ValueError('文章编辑格式错误')
        data['title'] = require_text(data.get('title'), 100, '文章标题')
        paragraphs = data.get('paragraphs')
        if not isinstance(paragraphs, list) or not 1 <= len(paragraphs) <= 12:
            raise ValueError('文章编辑需输出1至12个自然段')
        allowed = {i for i, _ in entries}
        for paragraph in paragraphs:
            if not isinstance(paragraph, dict):
                raise ValueError('文章编辑段落格式错误')
            paragraph['text'] = normalize_source_markers(require_text(paragraph.get('text'), 600, '书面段落'))
            paragraph['evidence_ids'] = validate_ids(paragraph.get('evidence_ids'), allowed)
            inline_ids = [int(marker or anchor) for marker, anchor in
                          re.findall(r'\[S(\d+)\]|#segment-(\d+)', paragraph['text'])]
            if inline_ids:
                paragraph['evidence_ids'] = validate_ids(paragraph['evidence_ids'] + inline_ids, allowed)
        character_count = sum(len(p['text']) for p in paragraphs)
        if character_count > 3200:
            raise ValueError(f'文章编辑实际{character_count}字符，超过3200字符；请将每段缩为原来的一半，合并重复论据')
        prose = '\n'.join(p['text'] for p in paragraphs)
        if len(re.findall(r'主持人|嘉宾说|嘉宾解释|嘉宾举|嘉宾先|他说|非常非常|对对', prose)) > 2:
            raise ValueError('文章仍在复述对话：去掉主持人/嘉宾说等叙事框架，直接阐述观点并用原视频例子展开')
        return data
    # 不把口语初稿再次注入，避免编辑时照抄其句式；始终依据原稿和校准建议成文。
    payload = material + '\n<校准建议>\n' + json.dumps(changes, ensure_ascii=False)
    return structured_call(payload, instruction, validate, call)


def representative_ids(ids, limit=8):
    # 全部段号留在证据笔记/文章段落，显示与汇总只选均匀分布的定位点。
    if len(ids) <= limit:
        return ids
    return [ids[round(index*(len(ids)-1)/(limit-1))] for index in range(limit)]


def group_blocks(items, limit=SYNTHESIS_LIMIT):
    groups, current, size = [], [], 0
    for item in items:
        if len(item) > limit:
            raise ValueError('单条证据过长，无法在当前上下文限制中处理')
        if current and size + len(item) + 2 > limit:
            groups.append('\n\n'.join(current))
            current, size = [], 0
        current.append(item)
        size += len(item) + 2
    if current:
        groups.append('\n\n'.join(current))
    return groups


def synthesize_section(notes, section, segments, call, report, checkpoint):
    key, title, instruction = section
    relevant = [n for n in notes if n['category'] == key]
    if key in ('summary', 'engineering', 'finance', 'implications', 'questions', 'market', 'holdings', 'policy', 'risks', 'conclusions'):
        relevant = notes
    if not relevant:
        return {'id': key, 'title': title, 'text': '当前材料未整理出足够的相关证据，无法作可靠解读。'}
    allowed = {i for n in relevant for i in n['evidence_ids']}
    # 使用已经看过完整片段的证据笔记，避免重复注入长原段造成上下文爆炸。
    blocks = [n['content'] + ' ' + ' '.join(f'[S{i}]' for i in representative_ids(n['evidence_ids'])) for n in relevant]
    merge_round = 0
    while len(group_blocks(blocks)) > 1:
        batches = group_blocks(blocks)
        report(f'归纳{title} · {len(batches)} 组证据')
        def validated_call(material, instruction, tokens):
            for attempt in range(2):
                suffix = '\n上次存在非法引用。只使用本次材料明确列出的[S段号]，不要按时间或顺序推算段号。' if attempt else ''
                body = call(material, instruction + suffix, tokens)
                # 两个最大归纳结果仍能进入同一组，确保下一轮组数收敛。
                require_text(body, 14000, '中间归纳')
                try:
                    bind_sources(body, segments, allowed)
                    return body
                except ValueError:
                    if attempt:
                        raise
        blocks = [checkpoint(f'{key}-merge-v2-{merge_round}-{i}', lambda batch=batch: validated_call(batch,
            f'只整理“{title}”的证据笔记。{instruction} 保留主要依据、实例与[S段号]，不写其它章节，控制在1200字内。', 5000))
            for i, batch in enumerate(batches)]
        merge_round += 1
    report(f'生成专家解读 · {title}')
    available_refs = ' '.join(f'[S{i}]' for i in sorted(allowed))
    limit = 3000 if key == 'summary' else 8000 if key == 'glossary' else 6000
    instruction = f'可用原文段号：{available_refs}。段号是原稿标识，不是论点编号。\n输出“{title}”正文 Markdown，不重复本章标题。{instruction} 关键视频观点使用[S段号]引用。区分【视频观点】【专家补充】【待核实】；没有材料的内容明确说明，不给行动学习清单。输入是同一视频的分片笔记。选择最重要的6-10项，合并重复，目标{limit//2}个汉字，正文最多{limit}字符（含标点与引用），不要逐条穷举所有笔记。'
    last_error = ''
    for attempt in range(2):
        suffix = f'\n上次输出未符合约定：{last_error}。压缩重复解释、只保留核心项，严格遵守字符上限；引用只用明确列出的段号。' if attempt else ''
        body = call('\n\n'.join(blocks), instruction + suffix, 6000)
        try:
            require_text(body, limit, '章节正文')
            return {'id': key, 'title': title, 'text': bind_sources(body, segments, allowed)}
        except ValueError as error:
            last_error = str(error)
            if attempt:
                raise


def analyze(transcript, expert, call, report, checkpoint=None):
    checkpoint = checkpoint or (lambda key, compute: compute())
    profile = get_profile(expert)
    segments = transcript['segments']
    chunks = source_chunks(segments)
    if not chunks:
        raise ValueError('文字稿为空，无法解读')
    notes, articles, corrections, warnings = [], [], [], []
    categories = ', '.join(k for k, _, _ in profile.sections)
    for index, chunk in enumerate(chunks):
        report(f'校准文字与整理证据 {index+1}/{len(chunks)}')
        material = '\n'.join(line for _, line in chunk)
        instruction = (
            '只输出 JSON 对象，结构：{"notes":[{"category":"分类","content":"论点、依据、例子与不确定性","evidence_ids":[整数段号]}],'
            '"article":{"title":"本片段主题","paragraphs":[{"text":"连贯的文章段落","evidence_ids":[整数段号]}]},'
            '"corrections":[{"original":"原稿词句","suggestion":"校准写法或候选","reason":"上下文依据","status":"applied或uncertain","evidence_ids":[整数段号]}]}。'
            f'notes 分类：{categories}，1-40条，每条最多800字；引用当前片段的1-3个代表段号即可定位，勿穷举连续段号。'
            '文章是原视频的书面化整理，与专家解读独立：仅根据原文，保留论证、例子、条件、分歧与推测语气，合并碎句、去掉口头填充与重复，不改成要点摘要。'
            '用完整自然段表达主题和观点，再用视频里的例子解释；不能新增原稿没有的例子、事件、专家知识或结论。不要用【视频观点】等报告标签，也不要贴时间戳。'
            'original必须逐字复制当前原文中一个连续词句，不合并多个别名、不添加标点或意译。未发现明确错误可以不输出校准记录。专名只有在片段上下文有明确证据时校准并记录 applied，否则保留原词/模糊称呼并记录 uncertain，不能凭发音猜厂商。'
            '1-20段，每段最多2500字，整个文章片段建议1500-2500字，依原稿长度调整；title最多100字；校准记录最多20条、各字段最多500字，无疑点返回空数组。')
        piece_notes, article, changes = checkpoint(f'chunk-{index}', lambda: structured_call(material, instruction, lambda raw: parse_chunk(raw, chunk, profile.sections), call))
        report(f'编辑书面文章 {index+1}/{len(chunks)}')
        original_warnings = article.get('validation_warnings', [])
        article = checkpoint(f'article-edited-v2-{index}', lambda: edit_article(material, changes, chunk, call))
        article['validation_warnings'] = original_warnings
        article_text = '\n'.join(p['text'] for p in article['paragraphs'])
        # 校准建议只有确实进入成稿才显示“已采用”，避免记录与文章不一致。
        changes = [{**c, 'status': 'uncertain', 'reason': c['reason']+'；整理文章未明确采用该写法'}
                   if c['status'] == 'applied' and c['suggestion'] not in article_text else c for c in changes]
        notes.extend(piece_notes)
        articles.append(article)
        warnings.extend(article.get('validation_warnings', []))
        corrections.extend(changes)
    # 只根据各部分题目编排目录，不把长篇文章再次压成摘要。
    outline_material = json.dumps([{'index': i, 'title': a['title']} for i, a in enumerate(articles)], ensure_ascii=False)
    if len(outline_material) > SYNTHESIS_LIMIT:
        raise ValueError('视频过长，文章目录超出上下文限制，请分集处理')
    report('编排整理文章')
    outline_instruction = (
        '这是按视频时间顺序形成的文章章节。只输出 JSON {"title":"全篇文章标题","headings":["各章节标题"]}。'
        f'以原视频内容为主题，不强调专家身份；统一标题表达，必须返回{len(articles)}个heading，数量/顺序与输入完全相同，不能合并章节。title和每个heading最多100字。')
    def validate_outline(raw):
        outline = read_json(raw)
        if not isinstance(outline, dict) or not isinstance(outline.get('headings'), list) or len(outline['headings']) != len(articles):
            raise ValueError(f'模型文章目录与原文片段不一致，headings必须有{len(articles)}项')
        outline['title'] = require_text(outline.get('title'), 100, '文章标题')
        outline['headings'] = [require_text(heading, 100, '文章章节标题') for heading in outline['headings']]
        return outline
    outline_key = 'outline-v2-' + hashlib.sha256(outline_material.encode()).hexdigest()
    outline = checkpoint(outline_key, lambda: structured_call(outline_material, outline_instruction, validate_outline, call))
    title = require_text(outline.get('title'), 100, '文章标题')
    article_sections = []
    for index, (piece, heading) in enumerate(zip(articles, outline['headings'])):
        heading = require_text(heading, 100, '文章章节标题')
        paragraphs = []
        for paragraph in piece['paragraphs']:
            refs = ' '.join(f'[S{i}]' for i in representative_ids(paragraph['evidence_ids'], 3))
            # 编辑器已验证所有内嵌引用并并入 evidence_ids。阅读正文每段只显示代表定位。
            prose = re.sub(r'\[S\d+\](?:\([^)]*\))?|\[[^\]]*\]\(#segment-\d+\)', '', paragraph['text'])
            paragraphs.append(bind_sources(prose.strip()+' '+refs, segments, set(paragraph['evidence_ids'])))
        article_sections.append({'id': f'article-{index+1}', 'title': heading, 'text': '\n\n'.join(paragraphs), 'paragraphs': piece['paragraphs']})
    complete_material = '\n'.join(line for chunk in chunks for _, line in chunk)
    if profile.report_style == 'finance_brief' and len(complete_material) <= 24000:
        from .finance import full_report
        report('编排财经研究笔记')
        sections = checkpoint('finance-brief-v3', lambda: full_report(complete_material, profile, segments, call))
    else:
        section_stage = 'section-finance-v2-' if profile.report_style == 'finance_brief' else 'section-compact-v2-'
        sections = [checkpoint(section_stage+section[0], lambda section=section: synthesize_section(notes, section, segments, call, report, checkpoint)) for section in profile.sections]
    if profile.report_style == 'finance_brief':
        from .finance import format_references
        formatted_sections = []
        for section in sections:
            text, ids = format_references(section['text'], segments)
            formatted_sections.append({**section, 'text': text, 'evidence_ids': list(dict.fromkeys(section.get('evidence_ids', []) + ids))})
        sections = formatted_sections
    article = {'title': title, 'sections': article_sections,
               'text': '# '+title+'\n\n'+'\n\n'.join('## '+s['title']+'\n\n'+s['text'] for s in article_sections),
               'corrections': corrections, 'validation_warnings': warnings}
    from .finance_entities import entity_candidates
    identity_candidates = entity_candidates(''.join(s['text'] for s in segments)) if profile.report_style == 'finance_brief' else []
    return {'schema_version': CONTRACT_VERSION, 'sections': sections, 'article': article,
            'entity_candidates': identity_candidates,
            'text': '\n\n'.join('## '+s['title']+'\n\n'+s['text'] for s in sections),
            'evidence_notes': notes, 'execution_kind': 'provider', 'source_chunks': len(chunks), 'profile': profile.id}
