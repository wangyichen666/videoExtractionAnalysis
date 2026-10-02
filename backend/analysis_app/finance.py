"""财经报告的整篇编排，输出仍使用通用章节与证据契约。"""
import json
import re


def format_references(text, segments):
    from .report_engine import normalize_source_markers, bind_sources, representative_ids
    text = normalize_source_markers(text)
    allowed = set(range(1, len(segments)+1))
    bind_sources(text, segments, allowed)  # 隐藏引用也必须先校验。
    ids = list(dict.fromkeys(int(marker or anchor) for marker, anchor in
               re.findall(r'\[S(\d+)\]|#segment-(\d+)', text)))
    def compact(match):
        group = list(dict.fromkeys(int(i) for i in re.findall(r'\[S(\d+)\]', match.group(0))))
        return ' '.join(f'[S{i}]' for i in representative_ids(group, 2)) + ' '
    text = re.sub(r'(?:\[S\d+\](?:\([^)]*\))?\s*){3,}', compact, text)
    return bind_sources(text, segments, allowed), ids


def full_report(material, profile, segments, call):
    from .report_engine import structured_call, read_json, require_text
    from .finance_entities import entity_candidates
    layout = [{'id': key, 'title': title, 'requirements': instruction}
              for key, title, instruction in profile.sections]
    limits = {'summary': 800, 'market': 2200, 'holdings': 3500,
              'policy': 1800, 'risks': 1800, 'conclusions': 1200}
    instruction = (
        '财经整篇报告：只输出 JSON {"sections":[{"id":"章节id","text":"Markdown正文"}]}。'
        '依据完整原稿一次编排六章，顺序、id与下列定义完全相同，每章只写该章内容，不重复章标题，不重复整篇概要。'
        + json.dumps(layout, ensure_ascii=False) +
        '\n核心主题只写150-250字单段概述；市场章按账户/行情/资金列5-8条；'
        '标的章每个公司用###标题，每家公司2-4条，覆盖所有明确讨论标的并区分持仓与举例；'
        '政策章3-5条解释作用路径与限制；风险章4-6条；结论章4-6条。全篇目标1800-2800汉字。'
        '每个关键视频观点引用1-2个最直接的[S段号]，不要穷举。'
        '【视频观点】用于原稿转述；【专家补充】用于专业解释；不确定处标【待核实】，不要每条重复免责声明。'
        '原稿公司名或数量存在歧义时必须具体列出疑点，不要用确定股数或股票代码填补。'
        '原稿已提供的账户状态、股息资金、经营现金流等不能说材料未给出；整体仓位不变不等于没有账户间买卖。'
        '不能由成交量直接推出内幕交易；区分贴息降低融资成本与物业收入增长之间的间接推论。'
        '账户合并是管理方式变化，不能因此认定资产集中度上升；原稿未给仓位比例时无法判断集中持仓程度。'
        '附录公司身份只核对官方名称、行业和代码，不核实视频里的财务或政策数据。'
        '只有发音候选（candidate）的主体应写“疑似公司名（代码，名称待确认）”；不能把关联关系写成已确认。'
        '如果解释估值，市盈率=市值/净利润，市净率=市值/净资产，不能把指标分子分母写反。'
        '概括优点和缺点时不能把原意互换：作者把破净当作价格便宜的依据时，不能把破净列为公司缺陷。'
        '股息支付率（分红/利润）和股息率（股息/股价）是不同口径；低股息支付率不自动等于低股息率。'
        '篇幅上限（包括标点和引用标记）：'+json.dumps(limits, ensure_ascii=False)+'。')

    def validate(raw):
        data = read_json(raw)
        sections = data.get('sections') if isinstance(data, dict) else None
        expected = [key for key, _, _ in profile.sections]
        if (not isinstance(sections, list) or any(not isinstance(s, dict) for s in sections)
                or [s.get('id') for s in sections] != expected):
            raise ValueError('财经报告章节缺失、重复或顺序错误，请完整输出定义的六章')
        result = []
        for section, (_, title, _) in zip(sections, profile.sections):
            text = require_text(section.get('text'), limits[section['id']], title)
            text, evidence_ids = format_references(text, segments)
            result.append({'id': section['id'], 'title': title, 'text': text, 'evidence_ids': evidence_ids})
        return result

    candidates = entity_candidates(''.join(s.get('text', '') for s in segments))
    context = '\n<外部公司身份候选，仅用于名称核对>\n' + json.dumps(candidates, ensure_ascii=False) if candidates else ''
    return structured_call(material + context, instruction, validate, call)
