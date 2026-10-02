"""适配 bbc-skill 的主评论/楼中楼分页，复用其扁平化字段。

任务、原子检查点与采集上限属于本项目；来源见 vendor/bbc/NOTICE.md。
"""
import json
import re
import time
from urllib.parse import urlparse

import httpx

from .pipeline import platform_for, resolve_url
from .vendor.bbc.flatten import flatten_reply

API = 'https://api.bilibili.com'


def normalize_target(target):
    target = target.strip()
    if re.fullmatch(r'BV[0-9A-Za-z]{10}', target):
        return f'https://www.bilibili.com/video/{target}'
    if '://' not in target:
        target = 'https://' + target
    parsed = urlparse(target)
    if (platform_for(target) != 'bilibili' or parsed.scheme != 'https'
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError('评论采集目前只支持 B站 HTTPS 视频链接或 BV 号')
    if parsed.hostname == 'b23.tv':
        return target
    match = re.search(r'(?:/video/|[?&]bvid=)(BV[0-9A-Za-z]{10})(?=[/?&#]|$)', target)
    if not match:
        raise ValueError('没有找到有效 BV 号，请使用 B站视频链接')
    return f'https://www.bilibili.com/video/{match[1]}'


def cookie_header(cookie, format='header'):
    if not cookie:
        return ''
    if format == 'netscape':
        pairs = []
        for line in cookie.splitlines():
            if not line or (line.startswith('#') and not line.startswith('#HttpOnly_')):
                continue
            fields = line.split('\t')
            domain = fields[0].removeprefix('#HttpOnly_').lstrip('.')
            if len(fields) != 7 or not (domain == 'bilibili.com' or domain.endswith('.bilibili.com')):
                raise ValueError('Cookie 文件格式或平台域名不匹配')
            pairs.append(f'{fields[5]}={fields[6]}')
        cookie = '; '.join(pairs)
    if any(ord(c) < 32 or ord(c) > 126 for c in cookie):
        raise ValueError('Cookie 含非法字符，请使用 Cookie Header 或 Netscape 文件内容')
    # 兼容用户保存的单个 SESSDATA 值。
    return cookie if '=' in cookie else 'SESSDATA=' + cookie


class CommentClient:
    def __init__(self, cookie, url):
        self.client = httpx.Client(timeout=20, follow_redirects=False, headers={
            'User-Agent': 'Mozilla/5.0', 'Referer': url, 'Cookie': cookie,
            'Accept': 'application/json, text/plain, */*'})
        self.last = 0

    def close(self):
        self.client.close()

    def get(self, path, params=None):
        # 固定API域名，不接受响应重定向地址，不将凭据发送到第三方。
        for attempt in range(3):
            elapsed = time.monotonic() - self.last
            if elapsed < 1:
                time.sleep(1-elapsed)
            self.last = time.monotonic()
            try:
                response = self.client.get(API + path, params=params)
            except httpx.HTTPError:
                if attempt < 2:
                    time.sleep(2**(attempt+1))
                    continue
                raise ValueError('评论接口网络连接失败，已采集内容保留，可稍后重试') from None
            if response.status_code in (412, 429) or response.status_code >= 500:
                if attempt < 2:
                    time.sleep(2**(attempt+1))
                    continue
                raise ValueError(f'评论接口暂不可访问（HTTP {response.status_code}），请稍后重试')
            if response.status_code != 200:
                raise ValueError(f'评论接口返回 HTTP {response.status_code}，请检查 Cookie 或视频权限')
            try:
                body = response.json()
            except (ValueError, TypeError):
                raise ValueError('评论接口未返回有效数据，请稍后重试') from None
            if not isinstance(body, dict):
                raise ValueError('评论接口响应格式异常')
            code = body.get('code')
            if code == 0:
                return body.get('data') or {}
            if code in (-101, -111):
                raise ValueError('B站登录已失效，请在设置中更新 Cookie')
            if code in (-404, 62002, 62004):
                raise ValueError('视频或评论不可访问，可能已删除、关闭评论或无权限')
            if code in (-352, -412, -509) and attempt < 2:
                time.sleep(2**(attempt+1))
                continue
            raise ValueError(f'评论接口返回错误码 {code}，请检查访问权限或稍后重试')


def clean_reply(reply, bvid, owner_mid, top_type=0):
    row = flatten_reply(reply, bvid=bvid, owner_mid=owner_mid, top_type=top_type)
    # 字符串ID防止JavaScript整数精度损失，不保留UID/IP/性别等额外用户信息。
    return {**{k: row[k] for k in ('uname', 'ctime', 'ctime_iso', 'message', 'like', 'rcount', 'is_up_reply', 'top_type')},
            'rpid': str(row['rpid']), 'root': str(row['root']), 'parent': str(row['parent'])}


def summarize(state, payload, status='collecting', reason=''):
    rows = list(state['rows'].values())
    roots = [r for r in rows if r['root'] == '0']
    nested = len(rows)-len(roots)
    declared = state.get('declared_total')
    complete = (state['main_done'] and (not payload['include_replies'] or
                all(r['rpid'] in state['subs_done'] for r in roots if r['rcount'] > 0)))
    # 关闭楼中楼时，主评论遍历完也不能宣称整个评论区完整。
    scope = 'finished' if complete and payload['include_replies'] and not reason else 'partial'
    return {'title': state.get('title') or payload['url'], 'url': state.get('url') or payload['url'],
            'video_id': state.get('bvid'), 'platform': 'bilibili', 'generated_at': time.time(),
            'started_at': state['started_at'], 'status': status, 'scope': scope,
            'stop_reason': reason, 'request_options': {k: payload[k] for k in ('order', 'max_top', 'max_total', 'include_replies')},
            'counts': {'total': len(rows), 'top_level': len(roots), 'nested': nested,
                       'pinned': sum(bool(r['top_type']) for r in roots),
                       'up_replies': sum(r['is_up_reply'] for r in rows), 'declared_total': declared},
            'main_exhausted': state['main_done'], 'comments': rows}


def collect_comments(payload, cookie, report, store, client_factory=CommentClient):
    state_id = 'comment-state-' + payload['namespace']
    try:
        state = store.get(state_id, 'comment_checkpoint')['value']
    except KeyError:
        state = {'rows': {}, 'next': 0, 'main_pages': 0, 'main_done': False, 'subs_done': [],
                 'sub_pages': {}, 'cursors': [], 'started_at': time.time()}
    client = None
    reason = ''

    def save(status='collecting', stop_reason=''):
        store.put('comment_checkpoint', {'value': state}, state_id)
        value = summarize(state, payload, status, stop_reason)
        store.put('comments', value, payload['snapshot_id'])
        return value

    def add(raw, pinned=0, root=None):
        row = clean_reply(raw, state['bvid'], state['owner_mid'], pinned)
        if root and row['root'] == '0':
            row.update(root=root, parent=root)
        if row['rpid'] in ('0', ''):
            return False
        previous = state['rows'].get(row['rpid'])
        if previous:
            row['top_type'] = max(row['top_type'], previous['top_type'])
        elif len(state['rows']) >= payload['max_total']:
            return False
        state['rows'][row['rpid']] = row
        return True

    try:
        url = normalize_target(payload['url'])
        if urlparse(url).hostname == 'b23.tv':
            url = normalize_target(resolve_url(url))
        bvid = re.search(r'BV[0-9A-Za-z]{10}', url)[0]
        client = client_factory(cookie_header(cookie, payload.get('cookie_format', 'header')), url)
        if not state.get('aid'):
            report('获取视频信息')
            view = client.get('/x/web-interface/wbi/view', {'bvid': bvid})
            if not view.get('aid'):
                raise ValueError('未取得视频编号，无法读取评论')
            state.update(bvid=bvid, url=url, aid=int(view['aid']), title=view.get('title') or bvid,
                         owner_mid=int((view.get('owner') or {}).get('mid') or 0))
            save()
        while not state['main_done']:
            roots = [r for r in state['rows'].values() if r['root'] == '0']
            if len(roots) >= payload['max_top'] or len(state['rows']) >= payload['max_total']:
                reason = '达到主评论采集上限' if len(roots) >= payload['max_top'] else '达到总评论采集上限'
                break
            report(f"读取主评论 · 第 {state['main_pages']+1} 页 · 已保存 {len(state['rows'])} 条")
            data = client.get('/x/v2/reply/main', {'type': 1, 'oid': state['aid'],
                              'mode': 3 if payload['order'] == 'hot' else 2, 'next': state['next'], 'ps': 20})
            cursor = data.get('cursor')
            if not isinstance(cursor, dict) or 'is_end' not in cursor:
                raise ValueError('评论接口分页信息缺失，已保存内容保留')
            state['declared_total'] = cursor.get('all_count')
            replies = data.get('replies') or []
            pinned = list(data.get('top_replies') or [])
            top = (data.get('upper') or {}).get('top')
            if isinstance(top, dict):
                pinned.append(top)
            candidates = [(r, 1) for r in pinned] + [(r, 0) for r in replies]
            skipped = False
            for raw, pin in candidates:
                rid = str(raw.get('rpid') or '')
                root_count = sum(r['root'] == '0' for r in state['rows'].values())
                if rid not in state['rows'] and root_count >= payload['max_top']:
                    skipped = True
                    continue
                if not add(raw, pin):
                    skipped = True
            next_cursor = cursor.get('next')
            state['main_pages'] += 1
            if skipped:
                reason = '达到主评论采集上限' if root_count >= payload['max_top'] else '达到总评论采集上限'
                save()
                break  # 不推进游标，不虚报已遍历完整页。
            state['main_done'] = bool(cursor['is_end'])
            if not state['main_done']:
                if not replies or next_cursor is None or next_cursor == state['next'] or next_cursor in state['cursors']:
                    save()
                    raise ValueError('评论接口分页未前进，已保存内容保留，可稍后重试')
                state['cursors'].append(state['next'])
                state['next'] = next_cursor
            save()
        if payload['include_replies']:
            roots = [r for r in state['rows'].values() if r['root'] == '0' and r['rcount'] > 0]
            for root in roots:
                rid = root['rpid']
                if rid in state['subs_done']:
                    continue
                if len(state['rows']) >= payload['max_total']:
                    reason = '达到总评论采集上限'
                    break
                pn = state['sub_pages'].get(rid, 1)
                while True:
                    report(f"读取楼中楼 · 第 {pn} 页 · 已保存 {len(state['rows'])} 条")
                    data = client.get('/x/v2/reply/reply', {'type': 1, 'oid': state['aid'], 'root': rid, 'ps': 20, 'pn': pn})
                    replies = data.get('replies') or []
                    before = len(state['rows'])
                    for raw in replies:
                        if not add(raw, root=rid):
                            reason = '达到总评论采集上限'
                    if reason == '达到总评论采集上限':
                        save()
                        break
                    page = data.get('page') or {}
                    count, size = page.get('count'), page.get('size')
                    ended = not replies or (isinstance(count, int) and isinstance(size, int) and size > 0 and pn*size >= count)
                    if ended:
                        state['subs_done'].append(rid)
                    else:
                        if len(state['rows']) == before:
                            save()
                            raise ValueError('楼中楼分页未前进，已保存内容保留，可稍后重试')
                        pn += 1
                        state['sub_pages'][rid] = pn
                    save()
                    if ended:
                        break
                if reason == '达到总评论采集上限':
                    break
        elif not reason:
            reason = '本次仅采集主评论'
        return save('completed', reason)
    except Exception:
        if state['rows']:
            save('interrupted', '采集中断，已保存内容可查看；重试将继续采集')
        raise
    finally:
        if client:
            client.close()
