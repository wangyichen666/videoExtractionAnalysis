import json
import pytest
from fastapi.testclient import TestClient
from analysis_app.comments import collect_comments, normalize_target, cookie_header, CommentClient
from analysis_app.store import Store


def row(rpid, *, root=0, count=0, text='讨论', author=1):
    return {'rpid': rpid, 'root': root, 'parent': root, 'rcount': count, 'like': 2, 'ctime': 1750000000,
            'member': {'mid': author, 'uname': '作者', 'sex': '男', 'ip_location': '上海'}, 'content': {'message': text}}


def payload(**kwargs):
    return {'url': 'https://www.bilibili.com/video/BV1NWaZ6REvt', 'namespace': 'test', 'snapshot_id': 'snapshot',
            'max_top': 100, 'max_total': 1000, 'order': 'hot', 'include_replies': True, **kwargs}


class FakeClient:
    def __init__(self, *args):
        self.closed = False
        self.calls = []

    def get(self, path, params):
        self.calls.append((path, params))
        if 'view' in path:
            return {'aid': 123, 'title': '示例', 'owner': {'mid': 1}}
        if path.endswith('/main'):
            if params['next'] == 0:
                return {'replies': [row(11, count=2), row(12)], 'upper': {'top': row(11, count=2)},
                        'cursor': {'is_end': False, 'next': 2, 'all_count': 5}}
            return {'replies': [row(13)], 'cursor': {'is_end': True, 'next': 2, 'all_count': 5}}
        return {'replies': [row(21, root=11), row(22, root=11)], 'page': {'count': 2, 'size': 10}}

    def close(self):
        self.closed = True


def test_comments_pins_dedup_threads_and_minimal_fields(tmp_path):
    client = FakeClient()
    result = collect_comments(payload(), 'SESSDATA=secret', lambda _: None, Store(tmp_path), lambda *args: client)
    assert result['counts'] == {'total': 5, 'top_level': 3, 'nested': 2, 'pinned': 1, 'up_replies': 5, 'declared_total': 5}
    assert result['scope'] == 'finished' and result['status'] == 'completed'
    assert result['comments'][0]['top_type'] == 1
    assert all(isinstance(c['rpid'], str) for c in result['comments'])
    assert not {'mid', 'ip_location', 'sex'} & result['comments'][0].keys()
    assert 'secret' not in json.dumps(result) and client.closed


def test_comments_exact_limits_do_not_claim_full(tmp_path):
    result = collect_comments(payload(max_top=1, max_total=2), '', lambda _: None, Store(tmp_path), FakeClient)
    assert result['counts']['top_level'] == 1
    assert result['counts']['total'] == 2
    assert result['scope'] == 'partial' and result['stop_reason'] == '达到总评论采集上限'


def test_comments_recover_after_nested_failure_without_skipping(tmp_path):
    store = Store(tmp_path)
    class Broken(FakeClient):
        def get(self, path, params):
            if path.endswith('/reply'):
                raise ValueError('网络中断')
            return super().get(path, params)
    with pytest.raises(ValueError, match='网络中断'):
        collect_comments(payload(), '', lambda _: None, store, Broken)
    assert store.get('snapshot', 'comments')['counts']['total'] == 3
    assert store.get('snapshot', 'comments')['status'] == 'interrupted'
    client = FakeClient()
    result = collect_comments(payload(), '', lambda _: None, store, lambda *args: client)
    assert result['counts']['total'] == 5
    assert [c[0] for c in client.calls] == ['/x/v2/reply/reply']


def test_comments_recover_main_cursor_and_keep_pinned_state(tmp_path):
    store = Store(tmp_path)
    class Broken(FakeClient):
        def get(self, path, params):
            if path.endswith('/main') and params['next'] == 2:
                raise ValueError('分页中断')
            return super().get(path, params)
    with pytest.raises(ValueError):
        collect_comments(payload(), '', lambda _: None, store, Broken)
    assert store.get('snapshot', 'comments')['counts']['top_level'] == 2
    client = FakeClient()
    result = collect_comments(payload(), '', lambda _: None, store, lambda *args: client)
    assert client.calls[0][1]['next'] == 2
    assert result['counts']['total'] == 5 and result['counts']['pinned'] == 1


def test_comments_sub_page_size_and_duplicate_cursor(tmp_path):
    class Paged(FakeClient):
        def get(self, path, params):
            if path.endswith('/reply'):
                pn = params['pn']
                return {'replies': [row(20+pn, root=11)], 'page': {'count': 2, 'size': 1}}
            return super().get(path, params)
    result = collect_comments(payload(), '', lambda _: None, Store(tmp_path/'paged'), Paged)
    assert result['counts']['nested'] == 2 and result['scope'] == 'finished'
    class Stuck(FakeClient):
        def get(self, path, params):
            result = super().get(path, params)
            if path.endswith('/main'):
                result['cursor'].update(is_end=False, next=params['next'])
            return result
    with pytest.raises(ValueError, match='未前进'):
        collect_comments(payload(), '', lambda _: None, Store(tmp_path/'stuck'), Stuck)


def test_comments_urls_and_cookie_boundaries():
    assert normalize_target('BV1NWaZ6REvt').endswith('BV1NWaZ6REvt')
    assert normalize_target('bilibili.com/video/BV1NWaZ6REvt/?spm_id=x') == normalize_target('BV1NWaZ6REvt')
    for url in ['https://evil.example/video/BV1NWaZ6REvt', 'https://bilibili.com.evil.example/video/BV1NWaZ6REvt',
                'https://user:secret@bilibili.com/video/BV1NWaZ6REvt', 'https://bilibili.com/video/BV123']:
        with pytest.raises(ValueError):
            normalize_target(url)
    assert cookie_header('single-session') == 'SESSDATA=single-session'
    assert cookie_header('.bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tx', 'netscape') == 'SESSDATA=x'
    with pytest.raises(ValueError):
        cookie_header('.youtube.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tx', 'netscape')
    with pytest.raises(ValueError):
        cookie_header('SESSDATA=x\nAuthorization:bad')
    with pytest.raises(ValueError):
        cookie_header('SESSDATA=中文')


def test_comment_api_jobs_retry_export_and_secret_isolation(tmp_path, monkeypatch):
    import analysis_main as module
    monkeypatch.setattr(module, 'store', Store(tmp_path))
    monkeypatch.setattr(module, 'worker', lambda stop: stop.wait())
    monkeypatch.setattr(module, 'collect_comments', lambda p,c,r,s: collect_comments(p,c,r,s,FakeClient))
    with TestClient(module.app) as client:
        credential = client.post('/api/credentials', json={'platform':'bilibili','name':'测试','cookie':'SESSDATA=never-expose'}).json()['id']
        job = client.post('/api/comment-jobs', json={'url':'BV1NWaZ6REvt','credential_id':credential}).json()
        assert 'never-expose' not in client.get('/api/jobs').text
        module.run_job(module.store.claim())
        saved = client.get('/api/comments/'+job['result_id']).json()
        assert saved['counts']['total'] == 5
        assert 'comments' not in client.get('/api/comments').json()[0]
        assert module.store.get(job['id'])['payload'] == {}
        for fmt in ('json','jsonl','md'):
            exported = client.get(f'/api/comments/{job["result_id"]}/export?format={fmt}')
            assert exported.status_code == 200 and 'never-expose' not in exported.text
        assert client.post('/api/comment-jobs',json={'url':'BV1NWaZ6REvt','max_top':100,'max_total':20}).status_code == 400
        other = client.post('/api/credentials',json={'platform':'youtube','name':'错平台','cookie':'x'}).json()['id']
        assert client.post('/api/comment-jobs',json={'url':'BV1NWaZ6REvt','credential_id':other}).status_code == 400
        # 失败重试沿用同一快照/断点，而不是重新爬完所有页。
        module.store.update(job['id'],status='failed')
        retried = client.post('/api/jobs/'+job['id']+'/retry').json()
        assert retried['result_id'] == job['result_id']
        module.run_job(module.store.claim())
        assert client.get('/api/comments/'+job['result_id']).json()['counts']['total'] == 5


def test_comment_network_error_redacted_and_throttle(monkeypatch):
    import analysis_app.comments as module
    import httpx
    requests = []
    clock = {'now': 100.0}
    monkeypatch.setattr(module.time,'monotonic',lambda:clock['now'])
    def sleep(seconds): clock['now'] += seconds
    monkeypatch.setattr(module.time,'sleep',sleep)
    class Http:
        def get(self,url,params):
            requests.append(clock['now'])
            return httpx.Response(200,json={'code':0,'data':{'ok':True}})
        def close(self): pass
    client = CommentClient('', 'https://www.bilibili.com/')
    client.client.close(); client.client = Http()
    assert client.get('/one') == {'ok':True}
    client.get('/two')
    assert requests[1]-requests[0] >= 1
    def fail(*args,**kwargs):
        raise httpx.ConnectError('SESSDATA=secret-url')
    client.client.get = fail
    with pytest.raises(ValueError) as error:
        client.get('/fail')
    assert 'secret-url' not in str(error.value)


def test_comment_http_redirect_is_not_followed(monkeypatch):
    import httpx
    seen = []
    def respond(request):
        seen.append(request.url.host)
        return httpx.Response(302, headers={'Location': 'https://untrusted.example/receive-cookie'})
    client = CommentClient('SESSDATA=secret', 'https://www.bilibili.com/')
    client.client.close()
    client.client = httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=False)
    with pytest.raises(ValueError, match='HTTP 302'):
        client.get('/redirect')
    assert seen == ['api.bilibili.com']
    client.close()
