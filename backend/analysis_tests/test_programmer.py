import json
import re
import pytest
from analysis_app.expert_profiles import (PROFILE, PROMPT, LEGACY_PROMPT, V2_PROMPT,
                                         SECTIONS, seed_experts, PROFILES)
from analysis_app.report_engine import (source_chunks, parse_chunk, analyze, bind_sources)
from analysis_app.store import Store


def chunk_reply(ids, sections=SECTIONS, corrections=None):
    return json.dumps({'notes': [{'category': key, 'content': title, 'evidence_ids': [ids[0]]} for key, title, _ in sections],
        'article': {'title': '从需求到实现', 'paragraphs': [{'text': '讨论者以编译器为例，说明工具可以参与构建自身；这一类比用于讨论改进的层次，没有直接证明智能提升。', 'evidence_ids': [ids[0]]}]},
        'corrections': corrections or []})


def fake_call_for(sections=SECTIONS):
    def call(text, instruction, max_tokens):
        if '财经整篇报告：' in instruction:
            source_id = int(re.search(r'\[S(\d+)\]', text).group(1))
            return json.dumps({'sections': [{'id': key, 'text': f'【视频观点】{title}。[S{source_id}]'} for key, title, _ in sections]})
        if 'notes 分类' in instruction:
            ids = [int(i) for i in re.findall(r'\[S(\d+)\]', text)]
            return chunk_reply(ids, sections)
        if 'headings' in instruction:
            parts = json.loads(text)
            return json.dumps({'title': 'AI 编程的边界', 'headings': [p['title'] for p in parts]})
        if '文章编辑：' in instruction:
            return json.dumps({'title': 'AI 编程的边界', 'paragraphs': [{'text': '编译器自举为讨论提供了类比，但不能直接证明模型智能提升。', 'evidence_ids': [int(re.search(r'\[S(\d+)\]', text).group(1))]}]})
        i = re.search(r'\[S(\d+)\]', text).group(1)
        return f'【视频观点】原文中的论点。[S{i}]\n\n【专家补充】这是专业解释。'
    return call


def test_default_migration_preserves_custom_prompts(tmp_path):
    store = Store(tmp_path)
    defaults = {'programmer': ('程序员专家', LEGACY_PROMPT)}
    for prompt in (LEGACY_PROMPT, V2_PROMPT):
        store.put('expert', {'name': '我的专家', 'prompt': prompt, 'version': 2}, 'programmer')
        seed_experts(store, defaults)
        assert store.get('programmer')['version'] == 3
        assert store.get('programmer')['profile'] == PROFILE
        assert store.get('programmer')['prompt'] == PROMPT
        assert '行动与学习清单' not in store.get('programmer')['prompt']
    seed_experts(store, defaults)
    assert store.get('programmer')['version'] == 3
    store.put('expert', {'name': '定制', 'prompt': '自定义提示词', 'version': 5}, 'programmer')
    seed_experts(store, defaults)
    assert store.get('programmer')['prompt'] == '自定义提示词'
    assert store.get('programmer')['version'] == 5
    assert store.get('programmer')['outputs'] == ['analysis', 'article']


def test_finance_migration_preserves_customization_and_historical_reports(tmp_path):
    from analysis_app.expert_profiles import FINANCE_LEGACY_PROMPT, FINANCE_PROMPT, FINANCE_V2_SECTIONS
    store = Store(tmp_path)
    defaults = {'finance': ('金融专家', FINANCE_LEGACY_PROMPT)}
    store.put('expert', {'name': '金融专家', 'prompt': FINANCE_LEGACY_PROMPT, 'version': 1, 'profile': 'finance-v1'}, 'finance')
    store.put('analysis', {'profile': 'finance-v1', 'expert_version': 1, 'text': '历史分析'}, 'old-finance')
    seed_experts(store, defaults)
    expert = store.get('finance')
    assert expert['name'] == '财经专家'
    assert expert['profile'] == 'finance-v2' and expert['version'] == 2
    assert expert['prompt'] == FINANCE_PROMPT
    assert [s['id'] for s in expert['sections']] == [s[0] for s in FINANCE_V2_SECTIONS]
    assert store.get('old-finance')['profile'] == 'finance-v1'
    seed_experts(store, defaults)
    assert store.get('finance')['version'] == 2
    store.put('expert', {'name': '我的宏观专家', 'prompt': '我的宏观视角', 'version': 7}, 'finance')
    seed_experts(store, defaults)
    assert store.get('finance')['prompt'] == '我的宏观视角'
    assert store.get('finance')['name'] == '我的宏观专家'
    assert store.get('finance')['version'] == 7


def test_chunking_covers_every_character_and_segment():
    segments = [{'start': 0, 'text': '甲'*19000}, {'start': 1, 'text': '乙'*9000}]
    chunks = source_chunks(segments)
    lines = [line for chunk in chunks for _, line in chunk]
    assert sum(line.count('甲') for line in lines) == 19000
    assert sum(line.count('乙') for line in lines) == 9000
    assert max(sum(len(line)+1 for _, line in chunk) for chunk in chunks) <= 6000
    assert {i for chunk in chunks for i, _ in chunk} == {1, 2}


@pytest.mark.parametrize('ids', [[99], [True], [], ['1']])
def test_evidence_rejects_invalid_source_ids(ids):
    data = json.loads(chunk_reply([1]))
    data['article']['paragraphs'][0]['evidence_ids'] = ids
    with pytest.raises(ValueError):
        parse_chunk(json.dumps(data), [(1, '[S1] [0s] 原文')], SECTIONS)


def test_correction_requires_real_original_and_status():
    correction = {'original': '不存在', 'suggestion': '替换', 'reason': '上下文', 'evidence_ids': [1], 'status': 'applied'}
    rejected = parse_chunk(chunk_reply([1], corrections=[correction]), [(1, '[S1] [0s] 原文')], SECTIONS)
    assert not rejected[2]
    assert rejected[1]['validation_warnings'][0]['original'] == '不存在'
    correction['original'] = '原文'
    result = parse_chunk(chunk_reply([1], corrections=[correction]), [(1, '[S1] [0s] 原文')], SECTIONS)
    assert result[2][0]['original'] == '原文'


@pytest.mark.parametrize('profile_id', list(PROFILES))
def test_each_expert_has_own_structure_and_independent_article(profile_id):
    profile = PROFILES[profile_id]
    calls = []
    call = fake_call_for(profile.sections)
    def tracked(*args):
        calls.append(args)
        return call(*args)
    result = analyze({'segments': [{'start': 65, 'text': '编译器可以用自己来编译自己。'}]}, {'profile': profile_id}, tracked, lambda _: None)
    assert [s['id'] for s in result['sections']] == [k for k, _, _ in profile.sections]
    assert all(s['id'] != 'actions' for s in result['sections'])
    assert '[01:05](#segment-1)' in result['text']
    assert '[01:05](#segment-1)' in result['article']['text']
    assert '【专家补充】' not in result['article']['text']
    assert result['schema_version'] == 2
    assert len(calls) == (4 if profile.report_style == 'finance_brief' else 9)


def test_synthesis_cannot_invent_a_source():
    call = fake_call_for()
    def invented(text, instruction, max_tokens):
        if 'notes 分类' in instruction or 'headings' in instruction or '文章编辑：' in instruction:
            return call(text, instruction, max_tokens)
        return '虚构引用[S2]'
    with pytest.raises(ValueError, match='未提供'):
        analyze({'segments': [{'start': 0, 'text': '原文'}, {'start': 2, 'text': '另段'}]}, {'profile': PROFILE}, invented, lambda _: None)


def test_long_report_reduces_per_chapter_and_preserves_every_article_piece():
    transcript = {'segments': [{'start': i, 'text': f'原文{i}'+ '长'*400} for i in range(36)]}
    mapped, inputs = set(), []
    base = fake_call_for()
    def call(text, instruction, max_tokens):
        inputs.append(text)
        if 'notes 分类' in instruction:
            ids = [int(i) for i in re.findall(r'\[S(\d+)\]', text)]
            mapped.update(ids)
            data = json.loads(chunk_reply(ids))
            data['notes'].extend({'category': 'summary', 'content': '论据'*350, 'evidence_ids': [ids[0]]} for _ in range(20))
            return json.dumps(data)
        return base(text, instruction, max_tokens)
    result = analyze(transcript, {'profile': PROFILE}, call, lambda _: None)
    assert mapped == set(range(1, 37))
    assert max(map(len, inputs)) <= 32200
    assert len(result['sections']) == 6
    assert len(result['article']['sections']) == result['source_chunks']
    assert len(inputs) > result['source_chunks'] + 7


def test_article_outline_cannot_drop_a_chunk():
    base = fake_call_for()
    def call(text, instruction, max_tokens):
        if 'headings' in instruction:
            return '{"title":"文章","headings":[]}'
        return base(text, instruction, max_tokens)
    with pytest.raises(ValueError, match='目录'):
        analyze({'segments': [{'start': 0, 'text': '原文'}]}, {'profile': PROFILE}, call, lambda _: None)


def test_long_intermediate_reports_still_converge():
    from analysis_app.report_engine import synthesize_section
    calls = []
    notes = [{'category': 'summary', 'content': '论据'*350, 'evidence_ids': [1]} for _ in range(120)]
    def call(material, instruction, tokens):
        calls.append(len(material))
        assert len(calls) < 10, '归纳层数应随组数减少而收敛'
        assert len(material) <= 32000
        return '归纳'*6900 + '[S1]' if '只整理' in instruction else '完整结论[S1]'
    section = synthesize_section(notes, SECTIONS[0], [{'start': 0, 'text': '原文'}],
                                 call, lambda _: None, lambda key, compute: compute())
    assert section['text'] == '完整结论[00:00](#segment-1)'
    assert len(calls) == 6  # 三组→两组→最终一组，不循环单独改写同一批。


def test_article_edit_repairs_oral_style_and_validates_inline_sources():
    from analysis_app.report_engine import edit_article
    instructions = []
    def call(material, instruction, tokens):
        instructions.append(instruction)
        text = '主持人问，嘉宾说，主持人总结，嘉宾解释。' if len(instructions) == 1 else '编译器自举为递归改进提供类比。[S2]'
        return json.dumps({'title': '自举的边界', 'paragraphs': [{'text': text, 'evidence_ids': [1]}]})
    result = edit_article('原稿', [], [(1, '原文'), (2, '类比')], call)
    assert len(instructions) == 2
    assert '仍在复述对话' in instructions[1]
    assert result['paragraphs'][0]['evidence_ids'] == [1, 2]
    with pytest.raises(ValueError, match='不属于'):
        edit_article('原稿', [], [(1, '原文')], lambda *args: json.dumps(
            {'title': '标题', 'paragraphs': [{'text': '虚构引用[S2]', 'evidence_ids': [1]}]}))


def test_summary_retries_excessive_length_without_truncating_prose():
    from analysis_app.report_engine import synthesize_section
    requests = []
    def call(material, instruction, tokens):
        requests.append(instruction)
        return '长'*3100 + '[S1]' if len(requests) == 1 else '浓缩后的完整观点[S1]'
    result = synthesize_section([{'category': 'summary', 'content': '观点', 'evidence_ids': [1]}],
        SECTIONS[0], [{'start': 0, 'text': '原文'}], call, lambda _: None, lambda key, compute: compute())
    assert len(requests) == 2
    assert '严格遵守字符上限' in requests[1]
    assert result['text'] == '浓缩后的完整观点[00:00](#segment-1)'


def test_structured_output_repair_is_bounded():
    base = fake_call_for()
    attempts = []
    def repaired(text, instruction, max_tokens):
        if 'notes 分类' in instruction:
            attempts.append(instruction)
            if len(attempts) == 1:
                return '模型返回了普通文本'
        return base(text, instruction, max_tokens)
    result = analyze({'segments': [{'start': 0, 'text': '原文'}]}, {'profile': PROFILE}, repaired, lambda _: None)
    assert result['article']
    assert len(attempts) == 2
    assert '上次输出未符合约定' in attempts[-1]
    failed = []
    def invalid(*args):
        failed.append(args)
        return '持续错误'
    with pytest.raises(ValueError, match='JSON'):
        analyze({'segments': [{'start': 0, 'text': '原文'}]}, {'profile': PROFILE}, invalid, lambda _: None)
    assert len(failed) == 2


def test_direct_anchor_cannot_bypass_evidence_validation():
    with pytest.raises(ValueError, match='未提供'):
        bind_sources('错误引用[00:00](#segment-2)', [{'start': 0, 'text': '原文'}, {'start': 1, 'text': '另一段'}], {1})


def test_many_real_evidence_ids_are_valid_and_metadata_preserved():
    ids = list(range(1, 32))
    data = json.loads(chunk_reply(ids))
    data['article']['paragraphs'][0]['evidence_ids'] = ids
    entries = [(i, f'[S{i}] [0s] 原文') for i in ids]
    _, article, _ = parse_chunk(json.dumps(data), entries, SECTIONS)
    assert article['paragraphs'][0]['evidence_ids'] == ids


def test_missing_final_container_can_be_completed_without_changing_values():
    from analysis_app.report_engine import read_json
    assert read_json('{"outer":{"value":"正文"}') == {'outer': {'value': '正文'}}
    with pytest.raises(ValueError):
        read_json('{"outer":{"value":"未完成正文')


def test_verified_checkpoints_resume_without_repeating_completed_calls():
    cache = {}
    def checkpoint(key, compute):
        if key not in cache:
            cache[key] = compute()
        return cache[key]
    base = fake_call_for()
    calls = []
    def call(*args):
        calls.append(args)
        return base(*args)
    transcript = {'segments': [{'start': 0, 'text': '原文'}]}
    analyze(transcript, {'profile': PROFILE}, call, lambda _: None, checkpoint)
    initial = len(calls)
    result = analyze(transcript, {'profile': PROFILE}, call, lambda _: None, checkpoint)
    assert len(calls) == initial  # 目录/文章/原文分片/已通过章节均复用；目录输入变化则单独失效。
    assert len(result['sections']) == 6
