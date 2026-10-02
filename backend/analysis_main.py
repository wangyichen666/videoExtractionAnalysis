"""独立网页入口：单用户本地部署，复用 BiliNote 与 yt-dlp。"""
import asyncio
import json
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from analysis_app.expert_profiles import seed_experts, profile_metadata, PROFILES
from analysis_app.store import Store
from analysis_app.pipeline import extract, interpret, platform_for, provider_options
from analysis_app.comments import collect_comments, normalize_target
from analysis_app.comment_analysis import prepare_input, analyze_comments

ROOT = Path(__file__).resolve().parent
store = Store(Path(os.getenv('ANALYSIS_DATA_DIR', ROOT / 'data' / 'analysis')))
DEFAULT_EXPERTS = {
    'general': ('通用解读', '你是一位严谨的知识整理专家，梳理主题、论证、核心知识和疑问。'),
    'finance': ('金融专家', '你是一位金融研究分析师，分析数据口径、经济逻辑、隐含假设、估值依据和风险。不得将视频观点当作已核实事实，不提供个性化交易指令。'),
    'programmer': ('程序员专家', '你是一位资深软件工程师，解释技术原理、实现步骤、架构取舍、潜在问题及适用条件。材料未给出代码时不要声称已审查实际代码。'),
}


def safe_record(record):
    return {k: v for k, v in record.items() if k not in ('secret', 'payload')}


def get(record_id, kind):
    try:
        return store.get(record_id, kind)
    except KeyError:
        raise HTTPException(404, '记录不存在')


def run_job(job):
    def report(phase):
        store.update(job['id'], phase=phase)
    try:
        payload = job['payload']
        if job['type'] == 'extract':
            cookie = store.decrypt(payload.get('secret', ''))
            result = extract(payload, cookie, report)
            result_id = store.put('transcript', result)
        elif job['type'] == 'comments':
            collect_comments(payload, store.decrypt(payload.get('secret', '')), report, store)
            result_id = payload['snapshot_id']
        elif job['type'] == 'comment_analysis':
            frozen = store.get(payload['input_id'], 'comment_analysis_input')
            provider = frozen['provider_snapshot']
            namespace = job['checkpoint_namespace']
            import hashlib
            def checkpoint(key, compute):
                cache_id = 'comment-analysis-cache-' + hashlib.sha256((namespace+key).encode()).hexdigest()
                try:
                    return store.get(cache_id, 'comment_analysis_checkpoint')['value']
                except KeyError:
                    value = compute()
                    store.put('comment_analysis_checkpoint', {'value': value}, cache_id)
                    return value
            result = analyze_comments(frozen['material'], provider, store.decrypt(provider['secret']), report, checkpoint)
            result.update(comments_id=frozen['material']['source_snapshot']['id'], model=provider['model'],
                          provider=provider['name'], generated_at=time.time())
            result_id = store.put('comment_analysis', result)
        else:
            transcript = store.get(payload['transcript_id'], 'transcript')
            provider = payload['provider_snapshot']
            import hashlib
            namespace = job.get('checkpoint_namespace', job['id'])
            # 缓存只在一次任务及其重试内复用，模型/提示词/原稿改变时自动失效。
            signature = json.dumps([namespace, transcript, payload['expert_snapshot'], provider['id'], provider['model'], provider['base_url'], 'engine-20261001.2'], sort_keys=True, ensure_ascii=False)
            prefix = hashlib.sha256(signature.encode()).hexdigest()
            def checkpoint(key, compute):
                record_id = 'checkpoint-' + hashlib.sha256((prefix + key).encode()).hexdigest()
                try:
                    return store.get(record_id, 'analysis_checkpoint')['value']
                except KeyError:
                    value = compute()
                    store.put('analysis_checkpoint', {'value': value, 'stage': key}, record_id)
                    return value
            result = interpret(transcript, payload['expert_snapshot'], provider,
                               store.decrypt(provider['secret']), report, checkpoint=checkpoint)
            result.update({'transcript_id': transcript['id'], 'expert_id': payload['expert_snapshot']['id'], 'expert': payload['expert_snapshot']['name'],
                           'expert_version': payload['expert_snapshot']['version'], 'expert_snapshot': payload['expert_snapshot'], 'model': provider['model'],
                           'provider': provider['name'], 'source_url': transcript.get('url', ''), 'generated_at': time.time()})
            result_id = store.put('analysis', result)
        store.update(job['id'], status='completed', phase='完成', result_id=result_id, payload={})
    except Exception as error:
        # 外部 SDK 错误可能含签名 URL 或凭据，仅保存已知业务错误。
        message = str(error) if isinstance(error, ValueError) else '处理失败，请检查平台访问、依赖或模型连接后重试'
        store.update(job['id'], status='failed', phase='失败', failed_phase=store.get(job['id']).get('phase'), error=message[:300], payload={})


def worker(stop):
    while not stop.is_set():
        job = store.claim()
        if job:
            run_job(job)
        else:
            stop.wait(0.5)


@asynccontextmanager
async def lifespan(app):
    # 同一 SQLite 只允许一个工作进程，防止启动恢复把正在执行的任务重新排队。
    import fcntl
    lock_file = (store.directory / 'worker.lock').open('a')
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        raise RuntimeError('此数据目录已有工作进程，请使用单 worker 启动')
    seed_experts(store, DEFAULT_EXPERTS)
    # 单工作进程；上次中断的任务重新排队，结果仍按独立记录保存。
    for job in store.list('job'):
        if job['status'] == 'running':
            store.update(job['id'], status='queued', phase='中断后重新排队')
    stop = threading.Event()
    thread = threading.Thread(target=worker, args=(stop,), daemon=True)
    thread.start()
    yield
    stop.set()
    await asyncio.to_thread(thread.join, 5)
    fcntl.flock(lock_file, fcntl.LOCK_UN)
    lock_file.close()


app = FastAPI(title='视频文字与专家解读', lifespan=lifespan)


class CredentialInput(BaseModel):
    platform: Literal['bilibili', 'youtube', 'douyin', 'kuaishou']
    name: str = Field(min_length=1, max_length=80)
    cookie: str = Field(min_length=1, max_length=100000)
    format: Literal['header', 'netscape'] = 'header'


class ProviderInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    base_url: str
    model: str = Field(min_length=1, max_length=150)
    api_key: str = Field(min_length=1, max_length=1000)


class ExpertInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=12000)


class ExtractionInput(BaseModel):
    url: str = Field(max_length=2000)
    credential_id: str | None = None
    cookie: str = Field(default='', max_length=100000)
    cookie_format: Literal['header', 'netscape'] = 'header'
    allow_asr: bool = False
    language: str = 'zh'
    asr_model: Literal['tiny', 'base', 'small', 'medium', 'large-v3'] = 'base'


class AnalysisInput(BaseModel):
    transcript_id: str
    expert_id: str
    provider_id: str


class CommentsInput(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    credential_id: str | None = None
    cookie: str = Field(default='', max_length=100000)
    cookie_format: Literal['header', 'netscape'] = 'header'
    order: Literal['hot', 'latest'] = 'hot'
    max_top: int = Field(default=100, ge=1, le=1000)
    max_total: int = Field(default=1000, ge=1, le=5000)
    include_replies: bool = True


class CommentAnalysisInput(BaseModel):
    comments_id: str
    provider_id: str
    min_chars: int = Field(default=20, ge=0, le=20000)
    max_chars: int | None = Field(default=None, ge=0, le=20000)
    query: str = Field(default='', max_length=200)
    up_only: bool = False


@app.get('/api/health')
def health():
    import importlib.util
    import shutil
    return {'status': 'ok', 'ffmpeg': bool(__import__('analysis_app.runtime', fromlist=['ffmpeg_binary']).ffmpeg_binary()), 'asr': importlib.util.find_spec('faster_whisper') is not None}


@app.get('/api/settings')
def settings():
    return {'credentials': [safe_record(r) for r in store.list('credential')],
            'providers': [safe_record(r) for r in store.list('provider')], 'experts': store.list('expert')}


@app.post('/api/credentials')
def save_credential(data: CredentialInput):
    record = data.model_dump(exclude={'cookie'})
    record['secret'] = store.encrypt(data.cookie)
    return {'id': store.put('credential', record)}


@app.delete('/api/credentials/{record_id}')
def delete_credential(record_id: str):
    get(record_id, 'credential')
    store.delete(record_id, 'credential')
    return {'ok': True}


@app.post('/api/providers')
def save_provider(data: ProviderInput):
    from urllib.parse import urlparse
    parsed = urlparse(data.base_url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(400, '模型 Base URL 必须使用 HTTPS 且不能含账号或查询参数')
    record = data.model_dump(exclude={'api_key'})
    record['secret'] = store.encrypt(data.api_key)
    return {'id': store.put('provider', record)}


@app.delete('/api/providers/{record_id}')
def delete_provider(record_id: str):
    get(record_id, 'provider')
    store.delete(record_id, 'provider')
    return {'ok': True}


@app.post('/api/providers/{record_id}/test')
def test_provider(record_id: str):
    provider = get(record_id, 'provider')
    try:
        with httpx.Client(timeout=20) as client:
            response = client.post(provider['base_url'].rstrip('/') + '/chat/completions',
                headers={'Authorization': 'Bearer ' + store.decrypt(provider['secret'])},
                json={'model': provider['model'], 'messages': [{'role': 'user', 'content': '请回复：连接成功'}], 'max_tokens': 20, **provider_options(provider)})
        if response.status_code >= 400:
            raise HTTPException(400, f'连接失败：HTTP {response.status_code}')
        content = response.json()['choices'][0]['message']['content']
        if not isinstance(content, str) or not content.strip():
            raise HTTPException(400, '模型连接已响应但未返回正文，请检查模型设置')
        return {'ok': True}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, '连接失败，请检查地址、网络和模型配置')


@app.post('/api/experts')
def save_expert(data: ExpertInput):
    return {'id': store.put('expert', {**data.model_dump(), 'version': 1, **profile_metadata(PROFILES['custom-v1'])})}


@app.put('/api/experts/{record_id}')
def update_expert(record_id: str, data: ExpertInput):
    old = get(record_id, 'expert')
    store.put('expert', {**{k: v for k, v in old.items() if k != 'id'}, **data.model_dump(), 'version': old['version'] + 1}, record_id)
    return {'id': record_id}


@app.post('/api/extractions')
def start_extraction(data: ExtractionInput):
    if '://' not in data.url:
        data.url = 'https://' + data.url
    try:
        platform = platform_for(data.url)
    except ValueError as error:
        raise HTTPException(400, str(error))
    from urllib.parse import urlparse
    parsed = urlparse(data.url)
    if parsed.scheme != 'https' or parsed.username or parsed.password:
        raise HTTPException(400, '请输入 HTTPS 视频链接')
    if platform == 'bilibili':
        from app.utils.url_parser import normalize_video_url
        data.url = normalize_video_url(data.url)
    payload = data.model_dump(exclude={'cookie'})
    cookie = data.cookie
    if data.credential_id and not cookie:
        credential = get(data.credential_id, 'credential')
        if credential['platform'] != platform:
            raise HTTPException(400, '凭据平台与视频链接不匹配')
        cookie = store.decrypt(credential['secret'])
        payload['cookie_format'] = credential['format']
    payload['secret'] = store.encrypt(cookie) if cookie else ''
    return {'id': store.put('job', {'type': 'extract', 'status': 'queued', 'phase': '排队', 'title': data.url, 'payload': payload, 'request': data.model_dump(exclude={'cookie'}), 'temporary_cookie': bool(data.cookie)})}


@app.post('/api/analyses')
def start_analysis(data: AnalysisInput):
    return enqueue_analysis(data)


@app.post('/api/comment-jobs')
def start_comments(data: CommentsInput):
    return enqueue_comments(data)


def enqueue_comments(data, namespace=None, snapshot_id=None):
    import uuid
    try:
        data.url = normalize_target(data.url)
    except ValueError as error:
        raise HTTPException(400, str(error))
    if data.max_total < data.max_top:
        raise HTTPException(400, '总评论上限不能小于主评论上限')
    payload = data.model_dump(exclude={'cookie'})
    cookie = data.cookie
    if data.credential_id and not cookie:
        credential = get(data.credential_id, 'credential')
        if credential['platform'] != 'bilibili':
            raise HTTPException(400, '请选择 B站平台 Cookie')
        cookie = store.decrypt(credential['secret'])
        payload['cookie_format'] = credential['format']
    namespace = namespace or str(uuid.uuid4())
    snapshot_id = snapshot_id or str(uuid.uuid4())
    payload.update(secret=store.encrypt(cookie) if cookie else '', namespace=namespace, snapshot_id=snapshot_id)
    job_id = store.put('job', {'type': 'comments', 'status': 'queued', 'phase': '排队',
            'title': data.url + ' · 视频评论', 'payload': payload, 'request': data.model_dump(exclude={'cookie'}),
            'temporary_cookie': bool(data.cookie), 'checkpoint_namespace': namespace, 'result_id': snapshot_id})
    return {'id': job_id, 'result_id': snapshot_id}


@app.post('/api/comment-analyses')
def start_comment_analysis(data: CommentAnalysisInput):
    return enqueue_comment_analysis(data)


def enqueue_comment_analysis(data, namespace=None, input_id=None):
    import uuid
    namespace = namespace or str(uuid.uuid4())
    if not input_id:
        snapshot = get(data.comments_id, 'comments')
        if snapshot['status'] == 'collecting':
            raise HTTPException(400, '请等待评论采集结束后再进行模型分析')
        provider = get(data.provider_id, 'provider')
        filters = data.model_dump(exclude={'comments_id', 'provider_id'})
        try:
            material = prepare_input(snapshot, filters)
        except ValueError as error:
            raise HTTPException(400, str(error))
        input_id = store.put('comment_analysis_input', {'material': material, 'provider_snapshot': provider})
    frozen = get(input_id, 'comment_analysis_input')
    return {'id': store.put('job', {'type': 'comment_analysis', 'status': 'queued', 'phase': '排队',
        'title': frozen['material']['source_snapshot']['title']+' · 评论观点分析',
        'payload': {'input_id': input_id}, 'request': data.model_dump(),
        'checkpoint_namespace': namespace, 'input_id': input_id})}


def enqueue_analysis(data, checkpoint_namespace=None):
    import uuid
    checkpoint_namespace = checkpoint_namespace or str(uuid.uuid4())
    transcript = get(data.transcript_id, 'transcript')
    provider = get(data.provider_id, 'provider')
    expert = get(data.expert_id, 'expert')
    payload = {'transcript_id': data.transcript_id, 'provider_snapshot': provider, 'expert_snapshot': expert}
    return {'id': store.put('job', {'type': 'analysis', 'status': 'queued', 'phase': '排队',
                                 'title': transcript['title'] + ' · ' + expert['name'], 'payload': payload, 'request': data.model_dump(), 'checkpoint_namespace': checkpoint_namespace})}


@app.post('/api/jobs/{record_id}/retry')
def retry_job(record_id: str):
    job = get(record_id, 'job')
    if job['status'] != 'failed':
        raise HTTPException(400, '只能重试失败任务')
    if not job.get('request'):
        raise HTTPException(400, '旧版任务不包含重试参数，请重新提交视频链接')
    if job.get('temporary_cookie'):
        raise HTTPException(400, '本次临时 Cookie 已清除，请重新输入后提交')
    if job['type'] == 'extract':
        return start_extraction(ExtractionInput(**job['request']))
    if job['type'] == 'comments':
        return enqueue_comments(CommentsInput(**job['request']), job.get('checkpoint_namespace'), job.get('result_id'))
    if job['type'] == 'comment_analysis':
        return enqueue_comment_analysis(CommentAnalysisInput(**job['request']), job.get('checkpoint_namespace'), job.get('input_id'))
    return enqueue_analysis(AnalysisInput(**job['request']), job.get('checkpoint_namespace'))


@app.post('/api/jobs/{record_id}/cancel')
def cancel_job(record_id: str):
    job = get(record_id, 'job')
    if job['status'] != 'queued':
        raise HTTPException(400, '当前仅支持取消排队任务')
    # 与工作线程领取任务在同一写锁下判断，避免覆盖已经运行的任务。
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        raw = db.execute("SELECT data FROM records WHERE id=? AND kind='job'", (record_id,)).fetchone()
        current = json.loads(raw[0])
        if current['status'] != 'queued':
            raise HTTPException(400, '任务已经开始处理')
        current.update(status='cancelled', phase='已取消', payload={})
        db.execute('UPDATE records SET data=? WHERE id=?', (json.dumps(current), record_id))
    return {'ok': True}


@app.get('/api/jobs')
def jobs():
    return [safe_record(r) for r in store.list('job')]


@app.get('/api/transcripts')
def transcripts():
    return [{k: v for k, v in r.items() if k not in ('text', 'segments')} for r in store.list('transcript')]


@app.get('/api/transcripts/{record_id}')
def transcript(record_id: str):
    return get(record_id, 'transcript')


@app.get('/api/analyses')
def analyses(summary: bool = False):
    records = store.list('analysis')
    if not summary:
        return records  # 保留第一版接口兼容。
    result = []
    for record in records:
        item = {k: v for k, v in record.items() if k not in ('text', 'sections', 'article', 'evidence_notes', 'expert_snapshot')}
        item['expert_snapshot'] = {k: v for k, v in record.get('expert_snapshot', {}).items() if k in ('id', 'profile')}
        item['has_article'] = bool(record.get('article'))
        result.append(item)
    return result


@app.get('/api/analyses/{record_id}')
def analysis_detail(record_id: str):
    return get(record_id, 'analysis')


@app.get('/api/comments')
def comments_list():
    return [{k: v for k, v in r.items() if k != 'comments'} for r in store.list('comments')]


@app.get('/api/comments/{record_id}')
def comments_detail(record_id: str):
    return get(record_id, 'comments')


@app.get('/api/comments/{record_id}/export')
def export_comments(record_id: str, format: Literal['json', 'jsonl', 'md'] = 'json'):
    data = get(record_id, 'comments')
    if format == 'json':
        content = json.dumps(data, ensure_ascii=False, indent=2)
    elif format == 'jsonl':
        content = '\n'.join(json.dumps(r, ensure_ascii=False) for r in data['comments']) + '\n'
    else:
        import re
        def escaped(text):
            # 用户评论始终当文本输出，不让HTML或Markdown改变文档结构。
            return re.sub(r'([\\`*_{}\[\]()#+.!<>|~-])', r'\\\1', str(text)).replace('\n', '  \n')
        content = f"# {escaped(data['title'])} · 评论\n\n视频：{data['url']}\n\n"
        from datetime import datetime
        content += f"采集时间：{datetime.fromtimestamp(data['generated_at']).astimezone().isoformat(timespec='seconds')}\n\n"
        content += f"已采集 {data['counts']['total']} 条；主评论 {data['counts']['top_level']} 条，楼中楼 {data['counts']['nested']} 条。\n\n"
        content += f"范围：{data['stop_reason'] or '已遍历接口当前可见评论，不保证包含被删除或隐藏内容'}\n\n"
        roots = [r for r in data['comments'] if r['root'] == '0']
        for root in roots:
            content += f"## {escaped(root['uname'] or '匿名用户')} · {root['ctime_iso']}\n\n点赞 {root['like']} · 回复 {root['rcount']}\n\n{escaped(root['message'])}\n\n"
            for reply in data['comments']:
                if reply['root'] == root['rpid']:
                    content += f"- {escaped(reply['uname'] or '匿名用户')} · {reply['ctime_iso']} · 点赞 {reply['like']}：{escaped(reply['message'])}\n\n"
    return Response(content, media_type='application/json' if format == 'json' else 'text/plain; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{data.get("video_id") or "video"}-comments.{format}"'})


@app.get('/api/comment-analyses')
def comment_analyses():
    return [{k:v for k,v in r.items() if k not in ('sources', 'items', 'example_bank', 'topics', 'disagreements', 'disagreement_checks', 'overview', 'limits')}
            for r in store.list('comment_analysis')]


@app.get('/api/comment-analyses/{record_id}')
def comment_analysis_detail(record_id: str):
    return get(record_id, 'comment_analysis')


@app.get('/api/comment-analyses/{record_id}/export')
def export_comment_analysis(record_id: str, format: Literal['md', 'json'] = 'md'):
    data = get(record_id, 'comment_analysis')
    if format == 'json':
        content = json.dumps(data, ensure_ascii=False, indent=2)
    else:
        from analysis_app.comment_analysis import export_markdown
        content = export_markdown(data)
    return Response(content, media_type='application/json' if format == 'json' else 'text/markdown; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="comment-viewpoints.{format}"'})


@app.get('/api/analyses/{record_id}/export')
def export_analysis(record_id: str, output: Literal['analysis', 'article'] = 'analysis'):
    data = get(record_id, 'analysis')
    transcript = get(data['transcript_id'], 'transcript')
    origin = '本次会话参考分析，未调用网页模型' if data.get('execution_kind') == 'conversation_reference' else '网页模型生成'
    if output == 'article' and not data.get('article'):
        raise HTTPException(404, '此历史报告尚未生成整理文章，请重新解读')
    if output == 'article':
        body = data['article']['text']
        corrections = data['article'].get('corrections', [])
        if corrections:
            body += '\n\n## 文字校准记录\n\n' + '\n'.join(
                f"- {'已校准' if c['status'] == 'applied' else '待确认'}：{c['original']} → {c['suggestion']}。{c['reason']}"
                for c in corrections)
    elif data.get('sections'):
        body = '\n\n'.join('## '+s['title']+'\n\n'+s['text'] for s in data['sections'] if s['id'] != 'actions')
    else:
        body = data['text']
    if data.get('entity_candidates'):
        body += '\n\n## 公司名称与代码核对\n\n官方来源只用于核对身份；疑似名称仍需回听，不代表财务或政策数据已核实。\n\n'
        body += '\n'.join(f"- {'疑似 ' if c['status'] == 'candidate' else ''}{c['name']}（{c['code']}，{c['market']}）：原稿写法 {'、'.join(c['matched_terms'])}。[公司官方页面]({c['source_url']})" for c in data['entity_candidates'])
    document_title = data['article']['title'] if output == 'article' else transcript['title']
    if output == 'article' and body.startswith('# '+document_title+'\n'):
        body = body.split('\n', 1)[1].lstrip()
    content = f"# {document_title}\n\n{data['expert']} · {data['model']} · 模板 v{data['expert_version']}\n\n来源：{origin}\n\n" + body
    if data.get('generated_at'):
        from datetime import datetime
        metadata = f"视频链接：{transcript.get('url', '')}\n\n生成时间：{datetime.fromtimestamp(data['generated_at']).astimezone().isoformat(timespec='seconds')}\n\n"
        content = content.replace('来源：'+origin+'\n\n', '来源：'+origin+'\n\n'+metadata, 1)
    import re
    def source_link(match):
        i = int(match.group(1)) - 1
        if 0 <= i < len(transcript['segments']):
            url = transcript.get('url', '')
            return '(' + url + ('&' if '?' in url else '?') + 't=' + str(int(transcript['segments'][i]['start'])) + ')'
        return ''
    content = re.sub(r'\(#segment-(\d+)\)', source_link, content)
    return Response(content, media_type='text/markdown; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="expert-{output}.md"'})


@app.get('/api/transcripts/{record_id}/export')
def export(record_id: str, format: Literal['txt', 'srt', 'json'] = 'txt'):
    data = get(record_id, 'transcript')
    def timestamp(seconds):
        ms = round(seconds * 1000)
        return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
    content = data['text']
    if format == 'srt':
        content = '\n\n'.join(f"{i+1}\n{timestamp(s['start'])} --> {timestamp(s['end'])}\n{s['text']}" for i, s in enumerate(data['segments']))
    elif format == 'json':
        content = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(content, media_type='application/json' if format == 'json' else 'text/plain',
                    headers={'Content-Disposition': f'attachment; filename="transcript.{format}"'})


DIST = ROOT.parent / 'BillNote_frontend' / 'dist'
if DIST.exists():
    app.mount('/assets', StaticFiles(directory=DIST / 'assets'), name='assets')
    @app.get('/')
    def index():
        return FileResponse(DIST / 'analysis.html')
