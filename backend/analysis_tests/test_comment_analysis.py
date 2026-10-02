import json
import pytest
from fastapi.testclient import TestClient
from analysis_app.store import Store
from analysis_app.comment_analysis import (comment_length, prepare_input, parse_items, parse_overview,
                                          analyze_selected, analyze_comments, review_overview)


def source(rpid, message, root='0', up=False):
    return {'rpid':str(rpid), 'root':root, 'parent':root, 'uname':'读者', 'message':message,
            'ctime':1, 'ctime_iso':'2026-10-01', 'like':1, 'rcount':0, 'is_up_reply':up, 'top_type':0}


def snapshot(comments=None):
    return {'id':'snapshot','title':'示例','url':'https://www.bilibili.com/video/BV1NWaZ6REvt',
            'generated_at':1,'scope':'partial','status':'completed','counts':{'total':3},'stop_reason':'限量',
            'comments': comments or [source(1,'成本会影响利润，例如涨价10%后，我的收益降低了。'),
                                     source(2,'我不赞成该结论，缺少数据。','1'),source(3,'哈哈')]}


def filters(**kwargs):
    return {'min_chars':5,'max_chars':None,'query':'','up_only':False,**kwargs}


def fake_call(material, instruction, *args):
    data = json.loads(material)
    if 'overview_to_check' in data:
        return json.dumps({'overview': data['overview_to_check'], 'checks': [
            {'index': i, 'is_disagreement': False, 'reason': '材料缺少同对象的明确相反立场'}
            for i, _ in enumerate(data['disagreements_to_check'])]}, ensure_ascii=False)
    if 'comments' in data:
        return json.dumps({'items':[{'source_id':c['source_id'],'viewpoints':[
            {'topic':'成本与收益','opinion':'成本影响收益','output':'需考虑成本变化',
             'reasoning':[],'examples':[], 'quote':c['message'][:30]}],
            'boundary':'这是作者自述，未外部核实'} for c in data['comments']]},ensure_ascii=False)
    ids = ([n['source_id'] for n in data['notes']] if 'notes' in data else
           list(dict.fromkeys(i for s in data['summaries'] for t in s['topics'] for i in t['source_ids'])))
    return json.dumps({'overview':'评论讨论成本与收益，存在不同判断。样本是筛选后的部分评论。',
         'topics':[{'topic':'成本','opinion':'关注成本变化','outputs':['考虑成本'], 'reasoning':[],
                    'examples':list(data['examples'])[:2],'source_ids':ids}],
         'disagreements':[],'limits':['样本不代表全部观众。']},ensure_ascii=False)


def test_length_filter_unicode_bounds_and_per_comment_selection():
    assert comment_length(' 中 文\n😀\t\ufeff') == 3
    assert comment_length('\u0085\u001cA') == 1
    rows=[source(1,'中😀文'),source(2,'中😀文！','1'),source(3,'其他',up=True)]
    frozen=prepare_input(snapshot(rows),filters(min_chars=3,max_chars=3))
    assert [s['rpid'] for s in frozen['sources']] == ['1']
    assert frozen['stats']['selected']==1 and frozen['sources'][0]['char_count']==3
    frozen=prepare_input(snapshot(rows),filters(min_chars=0,query='其他',up_only=True))
    assert [s['rpid'] for s in frozen['sources']] == ['3']
    with pytest.raises(ValueError,match='最大字数'):
        prepare_input(snapshot(),filters(min_chars=50,max_chars=1))
    with pytest.raises(ValueError,match='没有评论'):
        prepare_input(snapshot(),filters(min_chars=1000))
    with pytest.raises(ValueError,match='最多500'):
        prepare_input(snapshot([source(i,'支持') for i in range(501)]),filters(min_chars=0))


def test_selected_only_sent_and_missing_parent_boundary():
    frozen=prepare_input(snapshot(),filters(query='缺少'))
    seen=[]
    def call(material,instruction,*args):
        seen.append(material)
        return fake_call(material,instruction,*args)
    result=analyze_selected(frozen,call,lambda _:None)
    first=json.loads(seen[0])['comments'][0]
    assert first['source_id']=='C1' and first['context_missing'] and first['parent_context'] is None
    assert '涨价10%' not in '\n'.join(seen) and '哈哈' not in '\n'.join(seen)
    assert '读者' not in '\n'.join(seen)  # 模型不需要作者昵称/原始平台ID。
    assert result['stats']['selected']==1


@pytest.mark.parametrize('failure',['missing','unknown','wrong_quote','invented_example'])
def test_map_refuses_omission_fake_ids_and_wrong_author_quotes(failure):
    frozen=prepare_input(snapshot(),filters())
    calls=[]
    def broken(material,instruction,*args):
        calls.append(material)
        data=json.loads(fake_call(material,instruction,*args))
        if failure=='missing': data['items'].pop()
        if failure=='unknown': data['items'][0]['source_id']='C999'
        if failure=='wrong_quote': data['items'][0]['viewpoints'][0]['quote']='原文没有这句'
        if failure=='invented_example': data['items'][0]['viewpoints'][0]['examples']=[{'description':'编的案例','quote':'不属于作者的例子'}]
        return json.dumps(data,ensure_ascii=False)
    with pytest.raises(ValueError):
        analyze_selected(frozen,broken,lambda _:None)
    assert len(calls)==2


def test_summary_refuses_unparsed_ids_and_unverified_examples():
    good={'overview':'主题','topics':[{'topic':'主题','opinion':'观点','outputs':[], 'reasoning':[],
                                    'examples':[],'source_ids':['C1']}],'disagreements':[],'limits':[]}
    assert parse_overview(json.dumps(good),{'C1'}, {})['topics'][0]['source_ids']==['C1']
    with pytest.raises(ValueError): parse_overview(json.dumps(good),{'C2'}, {})
    good['topics'][0]['examples']=['C1-E999']
    with pytest.raises(ValueError): parse_overview(json.dumps(good),{'C1'}, {})


def test_long_comment_keeps_five_reasons_and_repair_error_names_source():
    frozen = prepare_input(snapshot(), filters())
    data = json.loads(fake_call(json.dumps({'comments': frozen['sources']}), ''))
    point = data['items'][0]['viewpoints'][0]
    point['reasoning'] = ['成本变化', '收入变化', '利润变化', '仓位变化', '市场变化']
    assert len(parse_items(json.dumps(data), frozen['sources'])[0]['viewpoints'][0]['reasoning']) == 5
    point['reasoning'] = '单条理由也必须是数组'
    with pytest.raises(ValueError, match='C1第1个观点.*字符串数组'):
        parse_items(json.dumps(data), frozen['sources'])
    point['reasoning'] = ['理由'] * 9
    with pytest.raises(ValueError, match='C1第1个观点.*实际9条，最多8条'):
        parse_items(json.dumps(data), frozen['sources'])


def test_quote_repair_receives_previous_output_and_precise_source():
    frozen = prepare_input(snapshot(), filters())
    calls = []
    def call(material, instruction, *args):
        calls.append(instruction)
        raw = fake_call(material, instruction)
        if len(calls) == 1:
            data = json.loads(raw)
            data['items'][0]['viewpoints'][0]['quote'] = '这句不在原评论中'
            return json.dumps(data, ensure_ascii=False)
        return raw
    result = analyze_selected(frozen, call, lambda _: None)
    assert result['stats']['selected'] == 2
    assert 'C1的第1个观点的quote' in calls[1]
    assert '这句不在原评论中' in calls[1] and '上次待修复输出' in calls[1]
    assert len(calls) == 4  # 抽取、一次定点修复、汇总、独立审校。


def test_condition_in_same_comment_cannot_be_split_into_disagreement():
    data = {'overview': '估值看似便宜，但仍需关注风险。', 'topics': [
        {'topic': '估值', 'opinion': '不能只看低估值', 'outputs': [], 'reasoning': [],
         'examples': [], 'source_ids': ['C1', 'C2']}], 'limits': [],
        'disagreements': [{'topic': '是否低估', 'sides': [
            {'opinion': '看似便宜', 'source_ids': ['C1']},
            {'opinion': '仍需关注风险', 'source_ids': ['C1', 'C2']}]}]}
    with pytest.raises(ValueError, match='双方来源不能重叠'):
        parse_overview(json.dumps(data), {'C1', 'C2'}, {})
    data['disagreements'][0]['sides'][1]['source_ids'] = ['C2']
    assert len(parse_overview(json.dumps(data), {'C1', 'C2'}, {})['disagreements']) == 1


def test_independent_review_removes_different_subjects_without_losing_topics():
    draft = {'overview': '批评甲与赞扬乙形成对立。', 'topics': [
        {'topic': '人物评价', 'opinion': '批评甲、赞扬乙', 'source_ids': ['C1', 'C2']}],
        'limits': ['都是单方自述'], 'disagreements': [{'topic': '人物评价', 'sides': [
            {'opinion': '批评甲', 'source_ids': ['C1']}, {'opinion': '赞扬乙', 'source_ids': ['C2']}]}]}
    def review_call(material, instruction, *args):
        assert len(json.loads(material)['relevant_notes']) == 2
        return json.dumps({'overview': '讨论中有对不同人物的主观评价，均未核实。',
            'checks': [{'index': 0, 'is_disagreement': False, 'reason': '评价对象不同，不能算同问题相反结论'}]})
    result = review_overview(draft, [{'source_id': 'C1'}, {'source_id': 'C2'}], review_call)
    assert result['disagreements'] == [] and result['topics'] == draft['topics']
    assert '形成对立' not in result['overview']
    assert result['disagreement_checks'][0]['reason'].startswith('评价对象不同')


def test_chunks_cover_every_comment_and_retry_reuses_checkpoint():
    frozen=prepare_input(snapshot([source(i,'持仓收益需要考虑风险。'*20) for i in range(25)]),filters())
    cache={};calls=[]
    def checkpoint(key,compute):
        if key not in cache:cache[key]=compute()
        return cache[key]
    def call(*args):calls.append(args[0]);return fake_call(*args)
    result=analyze_selected(frozen,call,lambda _:None,checkpoint)
    assert len(result['items'])==25 and len(calls)>2
    assert [i['source_id'] for i in result['items']]==[s['source_id'] for s in frozen['sources']]
    calls.clear()
    assert analyze_selected(frozen,call,lambda _:None,checkpoint)==result
    assert not calls


def test_no_opinion_does_not_force_a_summary():
    frozen=prepare_input(snapshot([source(1,'哈哈')]),filters(min_chars=0))
    def call(*args):
        return json.dumps({'items':[{'source_id':'C1','viewpoints':[],'boundary':'单纯情绪表达'}]})
    result=analyze_selected(frozen,call,lambda _:None)
    assert result['stats']['with_viewpoints']==0 and result['topics']==[]


def test_api_frozen_selection_retry_and_export(tmp_path,monkeypatch):
    import analysis_main as module
    monkeypatch.setattr(module,'store',Store(tmp_path))
    monkeypatch.setattr(module,'worker',lambda stop:stop.wait())
    monkeypatch.setattr(module,'analyze_comments',lambda frozen,p,k,r,checkpoint: analyze_selected(frozen,fake_call,r,checkpoint))
    with TestClient(module.app) as client:
        snap=module.store.put('comments',snapshot(),'snapshot')
        provider=module.store.put('provider',{'name':'测试','model':'demo','base_url':'https://example.com','secret':module.store.encrypt('hidden')})
        request={'comments_id':snap,'provider_id':provider,'min_chars':5}
        job=client.post('/api/comment-analyses',json=request).json()['id']
        frozen=module.store.get(module.store.get(job)['input_id'],'comment_analysis_input')
        assert frozen['material']['stats']['selected']==2
        # 输入在排队时冻结，后台运行或失败重试都不能跟随采集快照变化。
        module.store.put('comments',snapshot([source(99,'后来新增的评论')]),'snapshot')
        module.run_job(module.store.claim())
        completed=module.store.get(job)
        report=client.get('/api/comment-analyses/'+completed['result_id']).json()
        assert [s['rpid'] for s in report['sources']]==['1','2']
        assert 'hidden' not in json.dumps(report)
        assert 'sources' not in client.get('/api/comment-analyses').json()[0]
        assert client.get('/api/comment-analyses/'+report['id']+'/export').status_code==200
        assert client.get('/api/comment-analyses/'+report['id']+'/export?format=json').json()['filters']['min_chars']==5
        module.store.update(job,status='failed')
        retry=client.post('/api/jobs/'+job+'/retry').json()['id']
        assert module.store.get(retry)['input_id']==completed['input_id']
        module.run_job(module.store.claim())
        retried=client.get('/api/comment-analyses/'+module.store.get(retry)['result_id']).json()
        assert retried['sources']==report['sources']
        assert client.post('/api/comment-analyses',json={**request,'min_chars':100,'max_chars':3}).status_code==400


def test_model_call_auth_is_only_in_header(monkeypatch):
    import analysis_app.comment_analysis as module
    captured=[]
    class Reply:
        status_code=200
        def __init__(self,text):self.text=text
        def json(self):return {'choices':[{'message':{'content':self.text},'finish_reason':'stop'}],'usage':{'prompt_tokens':2,'completion_tokens':3}}
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,headers,json):
            captured.append((headers,json))
            instruction,material=json['messages'][1]['content'].split('\n<待分析材料>\n')
            return Reply(fake_call(material.split('\n</待分析材料>')[0],instruction))
    monkeypatch.setattr(module.httpx,'Client',Client)
    result=analyze_comments(prepare_input(snapshot(),filters()),{'model':'demo','base_url':'https://api.deepseek.com'},'private-key',lambda _:None)
    assert result['usage']=={'prompt_tokens':6,'completion_tokens':9}
    assert all(h['Authorization']=='Bearer private-key' for h,b in captured)
    assert all('private-key' not in json.dumps(b) and b['thinking']=={'type':'disabled'} for h,b in captured)
