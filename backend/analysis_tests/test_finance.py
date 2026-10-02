import json
import pytest
from analysis_app.finance import full_report
from analysis_app.expert_profiles import PROFILES
from analysis_app.report_engine import synthesize_section


def response(overrides=None):
    sections = [{'id': key, 'text': '【视频观点】账户整体仓位不变。[S1]'}
                for key, _, _ in PROFILES['finance-v2'].sections]
    return json.dumps({'sections': (overrides or (lambda s: s))(sections)})


@pytest.mark.parametrize('change', [lambda s: s[:-1], lambda s: s+s[:1], lambda s: s[::-1]])
def test_finance_report_rejects_missing_duplicate_or_reordered_chapters(change):
    calls = []
    def call(*args):
        calls.append(args)
        return response(change)
    with pytest.raises(ValueError, match='章节'):
        full_report('[S1] 整体仓位不变', PROFILES['finance-v2'], [{'start': 0, 'text': '原稿'}], call)
    assert len(calls) == 2


def test_finance_report_uses_complete_source_and_rejects_invented_evidence():
    material = '[S1] 大账户基本不亏\n[S2] 股息25000元尚未加仓'
    def call(text, instruction, tokens):
        assert text == material
        return response(lambda s: [{**x, 'text': '股息尚未加仓[S99]'} for x in s])
    with pytest.raises(ValueError, match='未提供'):
        full_report(material, PROFILES['finance-v2'], [{'start': 0}, {'start': 2}], call)


def test_long_finance_chapter_considers_facts_outside_its_note_category():
    notes = [{'category': 'summary', 'content': '账户基本不亏，资金借用中', 'evidence_ids': [1]},
             {'category': 'holdings', 'content': '经营现金流28亿多', 'evidence_ids': [2]}]
    def call(material, instruction, tokens):
        assert '账户基本不亏' in material and '经营现金流28亿多' in material
        return '【视频观点】财务口径需核实。[S2]'
    result = synthesize_section(notes, PROFILES['finance-v2'].sections[4],
        [{'start': 0}, {'start': 60}], call, lambda _: None, lambda key, compute: compute())
    assert '#segment-2' in result['text']


def test_company_identity_candidates_never_confirm_asr_or_match_market_word():
    from analysis_app.finance_entities import entity_candidates
    assert entity_candidates('今天行情不好') == []
    candidates = entity_candidates('韩信、宝利维、海基')
    assert {c['code'] for c in candidates} == {'00696', '06049', '06078'}
    assert all(c['status'] == 'candidate' and c['source_url'].startswith('https://') for c in candidates)
    assert entity_candidates('保利物业')[0]['status'] == 'explicit_name'


def test_compact_finance_citations_preserve_full_evidence_and_validate_hidden_ids():
    segments = [{'start': i, 'text': '原文'} for i in range(5)]
    def make_reply(reference):
        return response(lambda sections: [{**s, 'text': '【视频观点】观点'+reference} for s in sections])
    result = full_report('[S1]原文', PROFILES['finance-v2'], segments,
                         lambda *args: make_reply('[S1][S2][S3][S4][S5]'))
    assert result[0]['evidence_ids'] == [1, 2, 3, 4, 5]
    assert result[0]['text'].count('#segment-') == 2
    with pytest.raises(ValueError, match='未提供'):
        full_report('[S1]原文', PROFILES['finance-v2'], segments,
                    lambda *args: make_reply('[S1][S99][S5]'))


def test_fullwidth_sources_are_clickable_and_invalid_sources_still_rejected():
    from analysis_app.finance import format_references
    text, ids = format_references('观点【S1】【S2】［S3］', [{'start': 0}, {'start': 1}, {'start': 2}])
    assert ids == [1, 2, 3] and text.count('#segment-') == 2
    assert '【S' not in text and '［S' not in text
    with pytest.raises(ValueError, match='未提供'):
        format_references('观点【S1】【S99】【S3】', [{'start': 0}, {'start': 1}, {'start': 2}])
