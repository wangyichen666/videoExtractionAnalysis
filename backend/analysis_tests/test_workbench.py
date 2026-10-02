import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from analysis_app.store import Store
from analysis_app.pipeline import cookie_file, parse_subtitle, platform_for, public_url, interpret


def test_credentials_encryption_and_persistence(tmp_path):
    store = Store(tmp_path)
    value = 'SESSDATA=secret-value'
    record_id = store.put('credential', {'secret': store.encrypt(value)})
    assert value.encode() not in store.path.read_bytes()
    reopened = Store(tmp_path)
    assert reopened.decrypt(reopened.get(record_id)['secret']) == value
    assert (tmp_path / 'secret.key').stat().st_mode & 0o777 == 0o600


def test_atomic_task_claim(tmp_path):
    store = Store(tmp_path)
    for _ in range(20):
        store.put('job', {'status': 'queued'})
    with ThreadPoolExecutor(4) as pool:
        claimed = list(pool.map(lambda _: store.claim(), range(30)))
    ids = [r['id'] for r in claimed if r]
    assert len(ids) == len(set(ids)) == 20


def test_cookie_domain_and_cleanup(tmp_path):
    path = cookie_file('SESSDATA=a;token=b', 'bilibili', tmp_path, 'header')
    assert '.bilibili.com' in Path(path).read_text()
    assert Path(path).stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        cookie_file('# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tx\ty', 'bilibili', tmp_path, 'netscape')


def test_subtitle_formats_and_url_boundary():
    assert parse_subtitle('1\n00:00:01,100 --> 00:00:02,200\n你好\n', 'srt') == [{'start': 1.1, 'end': 2.2, 'text': '你好'}]
    data = {'events': [{'tStartMs': 1200, 'dDurationMs': 2000, 'segs': [{'utf8': '测试'}]}]}
    assert parse_subtitle(json.dumps(data), 'json3')[0]['end'] == 3.2
    assert platform_for('https://www.bilibili.com/video/BV123') == 'bilibili'
    with pytest.raises(ValueError):
        platform_for('https://bilibili.com.evil.example/x')
    with pytest.raises(ValueError):
        public_url('https://127.0.0.1/video')


@pytest.fixture
def application(tmp_path, monkeypatch):
    monkeypatch.setenv('ANALYSIS_DATA_DIR', str(tmp_path))
    import analysis_main
    monkeypatch.setattr(analysis_main, 'store', Store(tmp_path))
    # 暂停后台工作线程，测试显式运行任务以避免轮询时序依赖。
    monkeypatch.setattr(analysis_main, 'worker', lambda stop: stop.wait())
    with TestClient(analysis_main.app) as client:
        yield client, analysis_main


def test_api_extraction_analysis_and_no_secret_leak(application, monkeypatch):
    client, module = application
    secret = 'SESSION=never-return-this'
    credential = client.post('/api/credentials', json={'name': '测试', 'platform': 'bilibili', 'cookie': secret}).json()['id']
    config = client.get('/api/settings').json()
    assert secret not in json.dumps(config)
    assert 'secret' not in config['credentials'][0]
    wrong = client.post('/api/extractions', json={'url': 'https://youtube.com/watch?v=abc', 'credential_id': credential})
    assert wrong.status_code == 400
    calls = []
    def fake_extract(payload, cookie, report):
        calls.append(cookie)
        return {'title': '测试视频', 'url': payload['url'], 'source': '平台字幕', 'segments': [{'start': 1.1, 'end': 2.2, 'text': '原文'}], 'text': '原文'}
    monkeypatch.setattr(module, 'extract', fake_extract)
    job_id = client.post('/api/extractions', json={'url': 'https://www.bilibili.com/video/BV123', 'credential_id': credential}).json()['id']
    assert secret not in json.dumps(client.get('/api/jobs').json())
    module.run_job(module.store.claim())
    job = module.store.get(job_id)
    assert job['status'] == 'completed' and job['payload'] == {}
    assert calls == [secret]
    transcript_id = job['result_id']
    assert '00:00:01,100 --> 00:00:02,200' in client.get(f'/api/transcripts/{transcript_id}/export?format=srt').text
    provider_id = client.post('/api/providers', json={'name': '测试模型', 'base_url': 'https://example.com/v1', 'model': 'model', 'api_key': 'hidden-key'}).json()['id']
    def fake_interpret(transcript, expert, provider, key, report, **kwargs):
        assert key == 'hidden-key'
        return {'text': expert['name'], 'usage': {}}
    monkeypatch.setattr(module, 'interpret', fake_interpret)
    for expert_id in ['finance', 'programmer']:
        client.post('/api/analyses', json={'transcript_id': transcript_id, 'expert_id': expert_id, 'provider_id': provider_id})
        module.run_job(module.store.claim())
    assert len(calls) == 1
    assert len(client.get('/api/analyses').json()) == 2
    assert 'hidden-key' not in client.get('/api/settings').text


def test_failed_job_drops_temporary_credentials(application, monkeypatch):
    client, module = application
    def fail(*args):
        raise RuntimeError('external URL with private credential')
    monkeypatch.setattr(module, 'extract', fail)
    client.post('/api/extractions', json={'url': 'https://www.bilibili.com/video/BV123', 'cookie': 'temporary-secret'})
    module.run_job(module.store.claim())
    job = client.get('/api/jobs').json()[0]
    assert job['status'] == 'failed'
    assert 'private credential' not in job['error']
    assert module.store.get(job['id'])['payload'] == {}


def test_template_version_snapshot(application):
    client, module = application
    provider = module.store.put('provider', {'name': '模型', 'model': 'x', 'base_url': 'https://example.com/v1', 'secret': module.store.encrypt('key')})
    transcript = module.store.put('transcript', {'title': '标题'})
    old_version = module.store.get('finance')['version']
    task = client.post('/api/analyses', json={'provider_id': provider, 'transcript_id': transcript, 'expert_id': 'finance'}).json()['id']
    client.put('/api/experts/finance', json={'name': '金融专家新版', 'prompt': '新的提示词'})
    assert module.store.get(task)['payload']['expert_snapshot']['version'] == old_version
    assert module.store.get('finance')['version'] == old_version + 1


def test_long_transcript_uses_bounded_requests(monkeypatch):
    calls = []
    class Reply:
        status_code = 200
        def json(self):
            return {'choices': [{'message': {'content': '分析依据 [1.0s]'}}], 'usage': {'prompt_tokens': 2, 'completion_tokens': 1}}
    class FakeClient:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, url, headers, json):
            calls.append(json)
            return Reply()
    import analysis_app.pipeline as pipeline
    monkeypatch.setattr(pipeline.httpx, 'Client', FakeClient)
    result = interpret({'segments': [{'start': 1, 'text': '文' * 20000}]}, {'prompt': '专家'}, {'base_url': 'https://example.com/v1', 'model': 'x'}, 'key', lambda _: None)
    assert len(calls) > 1
    assert max(len(c['messages'][1]['content']) for c in calls) < 17000
    assert result['usage']['prompt_tokens'] == len(calls)*2


def test_retry_cancel_and_restart_recovery(application):
    client, module = application
    job_id = client.post('/api/extractions', json={'url': 'bilibili.com/video/BV123/?spm_id_from=tracking&p=2'}).json()['id']
    assert module.store.get(job_id)['request']['url'] == 'https://www.bilibili.com/video/BV123?p=2'
    assert client.post('/api/jobs/'+job_id+'/cancel').status_code == 200
    assert module.store.claim() is None
    failed = module.store.put('job', {'type': 'extract', 'status': 'failed', 'phase': '失败', 'payload': {}, 'request': {'url': 'https://www.bilibili.com/video/BV123'}})
    assert client.post('/api/jobs/'+failed+'/retry').status_code == 200
    temporary = module.store.put('job', {'type': 'extract', 'status': 'failed', 'temporary_cookie': True})
    assert client.post('/api/jobs/'+temporary+'/retry').status_code == 400


def test_bilibili_http_412_is_not_treated_as_missing_subtitle(monkeypatch):
    from app.downloaders.bilibili_subtitle import BilibiliSubtitleFetcher
    import app.downloaders.bilibili_subtitle as adapter
    class Denied:
        status_code = 412
    monkeypatch.setattr(adapter.requests, 'get', lambda *args, **kwargs: Denied())
    with pytest.raises(ValueError, match='HTTP 412'):
        BilibiliSubtitleFetcher(cookie='', strict_access=True).fetch_subtitles('https://www.bilibili.com/video/BV123')


def test_restart_requeues_incomplete_work(tmp_path, monkeypatch):
    import analysis_main
    store = Store(tmp_path)
    monkeypatch.setattr(analysis_main, 'store', store)
    monkeypatch.setattr(analysis_main, 'worker', lambda stop: stop.wait())
    task = store.put('job', {'status': 'running', 'payload': {}, 'phase': '处理'})
    with TestClient(analysis_main.app):
        assert store.get(task)['status'] == 'queued'


def test_real_pipeline_subtitle_path_needs_neither_asr_nor_llm(monkeypatch):
    import analysis_app.pipeline as pipeline
    from app.downloaders.bilibili_subtitle import BilibiliSubtitleFetcher
    from app.models.transcriber_model import TranscriptResult, TranscriptSegment
    monkeypatch.setattr(pipeline, 'resolve_url', lambda url: url)
    monkeypatch.setattr(BilibiliSubtitleFetcher, 'fetch_subtitles', lambda self, url:
        TranscriptResult('zh', '文字', [TranscriptSegment(0, 2, '文字')], {'ai_type': 1}))
    class MetadataUnavailable:
        def __init__(self, options):
            assert 'cookiefile' not in options
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, *args, **kwargs):
            raise RuntimeError('元信息被风控')
    monkeypatch.setattr(pipeline.yt_dlp, 'YoutubeDL', MetadataUnavailable)
    result = pipeline.extract({'url': 'https://www.bilibili.com/video/BV123', 'allow_asr': False}, '', lambda _: None)
    assert result['text'] == '文字'
    assert result['source'] == '平台自动字幕'


def test_model_failure_message_does_not_expose_provider_body(monkeypatch):
    import analysis_app.pipeline as pipeline
    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, *args, **kwargs):
            class Response:
                status_code = 401
                text = 'private key information'
            return Response()
    monkeypatch.setattr(pipeline.httpx, 'Client', Client)
    with pytest.raises(ValueError, match='HTTP 401') as error:
        pipeline.interpret({'segments': [{'start': 0, 'text': '内容'}]}, {'prompt': '专家'}, {'base_url': 'https://example.com/v1', 'model': 'x'}, 'secret', lambda _: None)
    assert 'private' not in str(error.value)


def test_model_length_retry_expands_budget_and_counts_both_requests(monkeypatch):
    import analysis_app.pipeline as pipeline
    budgets = []
    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, endpoint, headers, json):
            budgets.append(json['max_tokens'])
            assert headers['Authorization'] == 'Bearer test-key'
            assert 'test-key' not in str(json)
            data = {'choices': [{'finish_reason': 'length' if len(budgets) == 1 else 'stop',
                                 'message': {'content': '完整报告'}}],
                    'usage': {'prompt_tokens': 10, 'completion_tokens': 20}}
            class Response:
                status_code = 200
                def json(self):
                    return data
            return Response()
    monkeypatch.setattr(pipeline.httpx, 'Client', Client)
    result = interpret({'segments': [{'start': 0, 'text': '内容'}]}, {'prompt': '专家'},
                       {'base_url': 'https://example.com/v1', 'model': 'x'}, 'test-key', lambda _: None)
    assert budgets == [1800, 3600]
    assert result['text'] == '完整报告'
    assert result['usage'] == {'prompt_tokens': 20, 'completion_tokens': 40}


def test_bilibili_metadata_falls_back_after_412(monkeypatch):
    from app.downloaders.bilibili_subtitle import BilibiliSubtitleFetcher
    import app.downloaders.bilibili_subtitle as adapter
    requested = []
    class Reply:
        def __init__(self, status):
            self.status_code = status
        def json(self):
            return {'code': 0, 'data': {'title': '示例标题', 'pages': [{'cid': 123}]}}
    def request(url, **kwargs):
        requested.append(url)
        return Reply(200 if '/wbi/view' in url else 412)
    monkeypatch.setattr(adapter.requests, 'get', request)
    fetcher = BilibiliSubtitleFetcher(cookie='', strict_access=True)
    assert fetcher._get_cid('BV123') == 123
    assert len(requested) == 2
    assert fetcher._metadata['title'] == '示例标题'


def test_programmer_edit_keeps_profile_and_export_has_origin(application):
    client, module = application
    client.put('/api/experts/programmer', json={'name': '程序员专家', 'prompt': '自定义程序员偏好'})
    expert = module.store.get('programmer')
    assert expert['profile'] == 'programmer-v3'
    assert expert['version'] == 4
    tid = module.store.put('transcript', {'title': '访谈', 'url': 'https://www.bilibili.com/video/BV123', 'segments': [{'start': 65, 'text': '原文'}]})
    rid = module.store.put('analysis', {'transcript_id': tid, 'expert': '程序员专家', 'expert_version': 2,
        'model': '会话分析', 'execution_kind': 'conversation_reference', 'text': '观点[01:05](#segment-1)'})
    response = client.get(f'/api/analyses/{rid}/export')
    assert response.status_code == 200
    assert '未调用网页模型' in response.text
    assert 'https://www.bilibili.com/video/BV123?t=65' in response.text
    assert client.get('/api/analyses/missing/export').status_code == 404


@pytest.mark.parametrize('base_url', ['https://example.com/v1', 'https://api.deepseek.com'])
def test_programmer_protocol_and_usage(monkeypatch, base_url):
    from analysis_app.expert_profiles import PROFILE, PROMPT, SECTIONS
    import analysis_app.pipeline as pipeline
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, headers, json):
            assert headers['Authorization'] == 'Bearer key'
            calls.append(json)
            if base_url.endswith('deepseek.com'):
                assert json['thinking'] == {'type': 'disabled'}
                if '只输出 JSON' in json['messages'][1]['content']:
                    assert json['response_format'] == {'type': 'json_object'}
            else:
                assert 'thinking' not in json and 'response_format' not in json
            instruction = json['messages'][1]['content']
            if 'notes 分类' in instruction:
                content = __import__('json').dumps({'notes': [{'category': k, 'content': title, 'evidence_ids': [1]} for k, title, _ in SECTIONS], 'article': {'title': '主题', 'paragraphs': [{'text': '连贯表达视频的观点并保留例子。', 'evidence_ids': [1]}]}, 'corrections': []})
            elif 'headings' in instruction:
                content = '{"title":"文章","headings":["主题"]}'
            elif '文章编辑：' in instruction:
                content = '{"title":"主题","paragraphs":[{"text":"连贯表达观点和例子。","evidence_ids":[1]}]}'
            else:
                content = '专业解释[S1]'
            class Response:
                status_code = 200
                def json(self):
                    return {'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
            return Response()
    monkeypatch.setattr(pipeline.httpx, 'Client', Client)
    result = interpret({'segments': [{'start': 0, 'text': 'AI 编程访谈'}]}, {'profile': PROFILE, 'prompt': PROMPT}, {'base_url': base_url, 'model': 'x'}, 'key', lambda _: None)
    assert len(result['sections']) == 6
    assert result['usage'] == {'prompt_tokens': 90, 'completion_tokens': 45}
    assert len(calls) == 9


def test_article_export_summary_and_legacy_compatibility(application):
    client, module = application
    tid = module.store.put('transcript', {'title': '另一个视频', 'url': 'https://www.bilibili.com/video/BV456', 'segments': [{'start': 3, 'text': '原文'}]})
    record = {'transcript_id': tid, 'expert': '金融专家', 'expert_version': 1, 'model': 'x', 'expert_id': 'finance',
        'sections': [{'id': 'summary', 'title': '内容总结', 'text': '摘要'}, {'id': 'actions', 'title': '行动与学习清单', 'text': '旧内容'}],
        'text': '旧全文', 'evidence_notes': [{'content': '大笔记'}], 'expert_snapshot': {'id': 'finance', 'prompt': '长提示词'},
        'article': {'title': '文章标题', 'text': '# 文章标题\n\n段落 [00:03](#segment-1)', 'corrections': []}}
    rid = module.store.put('analysis', record)
    summary = client.get('/api/analyses?summary=true').json()[0]
    assert 'article' not in summary and 'evidence_notes' not in summary and 'text' not in summary
    assert summary['expert_snapshot'] == {'id': 'finance'} and summary['has_article']
    assert client.get('/api/analyses/'+rid).json()['article']['title'] == '文章标题'
    export = client.get(f'/api/analyses/{rid}/export?output=article')
    assert export.status_code == 200 and export.text.count('# 文章标题') == 1
    assert '?t=3' in export.text
    assert '行动与学习清单' not in client.get(f'/api/analyses/{rid}/export').text
    old = module.store.put('analysis', {**record, 'article': None})
    assert client.get(f'/api/analyses/{old}/export?output=article').status_code == 404
    assert client.get(f'/api/analyses/{old}/export').status_code == 200
    assert client.get(f'/api/analyses/{rid}/export?output=bad').status_code == 422


def test_new_custom_expert_uses_shared_contract(application):
    client, module = application
    rid = client.post('/api/experts', json={'name': '历史专家', 'prompt': '解释历史语境，谨慎处理史实'}).json()['id']
    custom = module.store.get(rid)
    assert custom['profile'] == 'custom-v1'
    assert custom['outputs'] == ['analysis', 'article']
    assert custom['prompt'] == '解释历史语境，谨慎处理史实'


def test_checkpoint_namespace_is_reused_only_for_retry(application):
    client, module = application
    pid = module.store.put('provider', {'name': 'x', 'model': 'm', 'base_url': 'https://example.com/v1', 'secret': module.store.encrypt('key')})
    tid = module.store.put('transcript', {'title': '视频'})
    request = {'transcript_id': tid, 'expert_id': 'programmer', 'provider_id': pid}
    first = client.post('/api/analyses', json=request).json()['id']
    namespace = module.store.get(first)['checkpoint_namespace']
    module.store.update(first, status='failed', payload={})
    retry = client.post('/api/jobs/'+first+'/retry').json()['id']
    assert module.store.get(retry)['checkpoint_namespace'] == namespace
    fresh = client.post('/api/analyses', json=request).json()['id']
    assert module.store.get(fresh)['checkpoint_namespace'] != namespace
