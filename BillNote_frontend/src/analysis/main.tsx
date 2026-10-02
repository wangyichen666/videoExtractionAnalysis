import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { FileText, History, Settings, X, MessageSquare } from 'lucide-react'
import './style.css'

import type { RecordData, CommentSnapshot, CommentAnalysis } from './types'
import { ReportReader } from './components/ReportReader'
import { CommentWorkspace } from './components/CommentWorkspace'

async function api(path: string, method = 'GET', data?: unknown) {
  let response: Response
  try { response = await fetch('/api' + path, { method, headers: { 'Content-Type': 'application/json' }, body: data ? JSON.stringify(data) : undefined }) } catch { throw new Error('暂时无法连接服务，请稍后重试') }
  const body = await response.json()
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '输入格式错误，请检查填写内容')
  return body
}
function App() {
  const [compact, setCompact] = useState(() => matchMedia('(max-width: 1100px)').matches)
  const [tab, setTab] = useState('提取与解读')
  const [settings, setSettings] = useState<{ credentials: RecordData[]; providers: RecordData[]; experts: RecordData[] }>({ credentials: [], providers: [], experts: [] })
  const [jobs, setJobs] = useState<RecordData[]>([])
  const [history, setHistory] = useState<RecordData[]>([])
  const [analyses, setAnalyses] = useState<RecordData[]>([])
  const [commentRecords, setCommentRecords] = useState<CommentSnapshot[]>([])
  const [commentAnalyses, setCommentAnalyses] = useState<CommentAnalysis[]>([])
  const [commentId, setCommentId] = useState('')
  const [commentReportId, setCommentReportId] = useState('')
  const [commentUrl, setCommentUrl] = useState('')
  const [selected, setSelected] = useState<RecordData | null>(null)
  const [url, setUrl] = useState('')
  const [cookie, setCookie] = useState('')
  const [credential, setCredential] = useState('')
  const [allowAsr, setAllowAsr] = useState(false)
  const [reportDetail, setReportDetail] = useState<RecordData | null>(null)
  const [reportId, setReportId] = useState('')
  const [expert, setExpert] = useState('programmer')
  const [provider, setProvider] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [health, setHealth] = useState<{ ffmpeg: boolean; asr: boolean } | null>(null)
  const [editingExpert, setEditingExpert] = useState('')
  const [expertName, setExpertName] = useState('')
  const [expertPrompt, setExpertPrompt] = useState('')
  useEffect(() => {
    const query = matchMedia('(max-width: 1100px)')
    const change = () => setCompact(query.matches)
    query.addEventListener('change', change)
    return () => query.removeEventListener('change', change)
  }, [])
  async function refresh() {
    const [s, j, t, a, c, ca] = await Promise.all([api('/settings'), api('/jobs'), api('/transcripts'), api('/analyses?summary=true'), api('/comments'), api('/comment-analyses')])
    setSettings(s); setJobs(j); setHistory(t); setAnalyses(a); setCommentRecords(c); setCommentAnalyses(ca)
    setMessage(previous => previous === '暂时无法连接服务，请稍后重试' ? '' : previous)
    setProvider(p => p || s.providers[0]?.id || '')
  }
  useEffect(() => {
    let active = true
    const poll = async () => { if (active) { try { await refresh() } catch (e) { if (active) setMessage((e as Error).message) } } }
    void poll(); void api('/health').then(setHealth).catch(() => {})
    const timer = setInterval(poll, 3000)
    return () => { active = false; clearInterval(timer) }
  }, [])
  async function action(fn: () => Promise<unknown>, success: string) {
    setBusy(true); setMessage('')
    try { await fn(); await refresh(); setMessage(success) } catch (e) { setMessage((e as Error).message) } finally { setBusy(false) }
  }
  async function load(id: string) { await action(async () => { setSelected(await api('/transcripts/' + id)); setTab('提取与解读') }, '文字稿已加载') }
  function openComments(videoUrl = '', id = '', reportId = '') { setCommentReportId(reportId); setCommentUrl(videoUrl); setCommentId(id); setTab('视频评论'); setMessage('') }
  const currentAnalyses = analyses.filter(a => a.transcript_id === selected?.id && (a.expert_id === expert || a.expert_snapshot?.id === expert || (!a.expert_id && !a.expert_snapshot?.id && (a.profile?.startsWith(expert+'-') || a.expert === settings.experts.find(x => x.id === expert)?.name))))
  const generating = jobs.some(j => j.type === 'analysis' && j.request?.transcript_id === selected?.id && j.request?.expert_id === expert && (j.status === 'running' || j.status === 'queued'))
  const currentReport = currentAnalyses.find(a => a.id === reportId) || currentAnalyses[0]
  const expertDefinition = settings.experts.find(x => x.id === expert)
  useEffect(() => {
    if (!currentReport?.id) { setReportDetail(null); return }
    let active = true
    void api('/analyses/' + currentReport.id).then(data => { if(active) setReportDetail(data) }).catch(e => { if(active) setMessage((e as Error).message) })
    return () => { active = false }
  }, [currentReport?.id])
  return <div className="shell">
    <header className="app-header">
      <div className="brand"><span className="brand-icon"><FileText size={18} /></span><span>视频文字工作台</span></div>
      <nav aria-label="主导航">{[{ name: '提取与解读', icon: FileText }, { name: '视频评论', icon: MessageSquare }, { name: '历史任务', icon: History }, { name: '设置', icon: Settings }].map(({ name, icon: Icon }) => <button key={name} aria-current={tab === name ? 'page' : undefined} className={tab === name ? 'active' : ''} onClick={() => { setTab(name); setMessage('') }}><Icon size={16} /><span>{name}</span></button>)}</nav>
      <span className="local-status"><span />本地工作区</span>
    </header>
    <div className="page-bar"><h1>{tab === '提取与解读' ? '视频工作台' : tab}</h1><div className="workspace-meta"><span>{history.length} 份文字稿</span><span>{jobs.filter(j => j.status === 'queued' || j.status === 'running').length} 个进行中任务</span></div></div>
    {message && <div role="status" className="notice"><span>{message}</span><button aria-label="关闭提示" onClick={() => setMessage('')}><X size={16} /></button></div>}
    {tab === '提取与解读' && <div className="workspace"><aside className="panel input-panel"><details className="new-task" open={!selected || !compact}><summary>新建提取</summary><p className="panel-description">字幕优先，可选语音转写</p><form onSubmit={e => { e.preventDefault(); void action(async () => { await api('/extractions', 'POST', { url, credential_id: credential || null, cookie, allow_asr: allowAsr }); setCookie('') }, '任务已加入队列，在历史任务中查看进度') }}>
      <label>视频链接<input required type="text" placeholder="https://www.bilibili.com/video/…" value={url} onChange={e => setUrl(e.target.value)} /></label>
      <label>已保存的平台 Cookie<select value={credential} onChange={e => setCredential(e.target.value)}><option value="">不使用已保存凭据</option>{settings.credentials.map(c => <option key={c.id} value={c.id}>{c.name} · {c.platform}</option>)}</select></label>
      <details><summary>本次临时 Cookie</summary><textarea placeholder="粘贴 Cookie Header，仅用于本次提取" value={cookie} onChange={e => setCookie(e.target.value)} /></details>
      <label className="check"><input type="checkbox" checked={allowAsr} onChange={e => setAllowAsr(e.target.checked)} />无字幕时使用本地语音转写</label>
      {allowAsr && health && (!health.asr || !health.ffmpeg) && <p className="warning">语音转写尚缺少 {!health.asr ? 'faster-whisper ' : ''}{!health.ffmpeg ? 'FFmpeg' : ''}，请按启动文档安装。</p>}
      <button className="primary" disabled={busy}>开始提取</button><p className="hint">首期重点支持 B站与 YouTube；抖音、快手仍需实际验证。画面文字识别暂未启用。</p>
    </form></details><details className="library-list" open={!selected || !compact}><summary>资料库 · {history.length} 篇</summary>{history.length === 0 && <p className="hint">提取完成后会出现在这里。</p>}{history.map(t => <button className="history-item" key={t.id} onClick={() => void load(t.id)}>{t.title}<small>{t.platform} · {t.source}</small></button>)}</details></aside>
    <main className="panel result">{!selected ? <div className="empty"><div className="empty-icon">文</div><h2>文字是理解的起点</h2><p>输入视频链接，或从左侧选择已有文字稿。</p><p>提取字幕不需要配置大模型 API Key。</p></div> : <><div className="result-head"><div className="result-title"><h2>{selected.title}</h2><div className="document-meta"><span className="badge">{selected.source}</span><span>{selected.segments?.length.toLocaleString()} 段</span><span>{selected.text?.length.toLocaleString()} 字</span></div></div><div className="exports">{selected.platform === 'bilibili' && <button className="comment-entry" onClick={()=>openComments(selected.url || '',commentRecords.find(c=>c.video_id===selected.video_id)?.id || '')}><MessageSquare size={13}/>视频评论</button>}{['txt','srt','json'].map(f => <a key={f} href={`/api/transcripts/${selected.id}/export?format=${f}`}>{f.toUpperCase()}</a>)}</div></div>
      <details className="source-document"><summary>查看原文文字稿 · {selected.segments?.length.toLocaleString()} 段</summary><div className="transcript">{selected.segments?.map((s, i) => <div key={i} id={`segment-${i+1}`} tabIndex={-1}><time>{Math.floor(s.start/60)}:{String(Math.floor(s.start%60)).padStart(2,'0')}</time><p>{s.text}</p></div>)}</div></details>
      <section className="expert-box"><div className="expert-toolbar-label">生成解读与文章</div><div className="row"><select aria-label="选择专家" value={expert} onChange={e => setExpert(e.target.value)}>{settings.experts.map(x => <option value={x.id} key={x.id}>{x.name}</option>)}</select><select aria-label="选择模型" value={provider} onChange={e => setProvider(e.target.value)}><option value="">选择模型配置</option>{settings.providers.map(x => <option value={x.id} key={x.id}>{x.name} · {x.model}</option>)}</select><button disabled={!provider || busy || generating} className="primary" onClick={() => void action(() => api('/analyses', 'POST', { transcript_id: selected.id, expert_id: expert, provider_id: provider }), '开始生成解读与文章')}>{generating ? '生成中…' : '生成解读'}</button></div>
      <details className="expert-scope"><summary>解读范围 · {expertDefinition?.sections?.length || 0} 个维度{expertDefinition?.outputs?.includes('article') && ' ＋ 整理文章'}</summary><p>{expertDefinition?.sections?.map(s => s.title).join(' · ')}</p></details>
      {!provider && <p className="hint">自动解读需先配置模型。<button className="text-button" onClick={() => setTab('设置')}>前往设置</button>；已有参考报告可直接阅读。长视频将分段整理证据，再生成各章，会产生多次模型请求。</p>}
      {jobs.filter(j => j.type === 'analysis' && j.request?.transcript_id === selected.id && (j.status === 'running' || j.status === 'queued')).map(j => <p role="status" key={j.id} className={j.status === 'running' ? 'task-progress' : 'hint'}>正在处理 · {j.phase}</p>)}
      </section>
      {currentReport ? <><div className="report-selection"><span>{currentAnalyses.length} 份{expertDefinition?.name}解读</span>{currentAnalyses.length > 1 && <select aria-label="选择历史解读" value={currentReport.id} onChange={e => setReportId(e.target.value)}>{currentAnalyses.map((a, index) => <option value={a.id} key={a.id}>{a.model} · 模板 v{a.expert_version} · 第 {currentAnalyses.length-index} 份</option>)}</select>}</div>{reportDetail?.id === currentReport.id ? <ReportReader key={currentReport.id} analysis={reportDetail} /> : <p role="status" className="hint">正在加载解读…</p>}</> : <div className="report-empty"><h3>使用{expertDefinition?.name || '所选专家'}理解这份视频</h3><p>生成专业解读和整理文章，结果将按专家模式独立保存。</p></div>}
    </>}</main></div>}
    {tab === '视频评论' && <CommentWorkspace records={commentRecords} analysisRecords={commentAnalyses} providers={settings.providers} jobs={jobs} credentials={settings.credentials} busy={busy} initialUrl={commentUrl} initialReportId={commentReportId} recordId={commentId} setRecordId={setCommentId} api={api} action={action}/>}
    {tab === '历史任务' && <section className="panel"><h2>任务进度与历史</h2>{jobs.length === 0 && <p>还没有任务。</p>}{jobs.map(j => <div className="job" key={j.id}><div><strong>{j.title}</strong><p>{j.type === 'extract' ? '文字提取' : j.type === 'comments' ? '评论采集' : j.type === 'comment_analysis' ? '评论分析' : '专家解读'} · {j.phase}{j.error && <span className="warning"> · {j.error}</span>}</p></div><span className="badge">{{queued:'排队',running:'处理中',completed:'完成',failed:'失败',cancelled:'已取消'}[j.status || '']}</span>{j.status === 'failed' && <button disabled={busy} onClick={() => void action(() => api('/jobs/'+j.id+'/retry','POST'), '重试任务已排队')}>重试</button>}{j.status === 'queued' && <button disabled={busy} onClick={() => void action(() => api('/jobs/'+j.id+'/cancel','POST'), '排队任务已取消')}>取消</button>}{j.type === 'comment_analysis' && j.status === 'completed' && j.request?.comments_id && <button onClick={()=>openComments('',j.request?.comments_id || '',j.result_id || '')}>打开评论分析</button>}{j.type === 'comments' && j.result_id && commentRecords.some(c=>c.id===j.result_id) && <button onClick={()=>openComments(j.request?.url || '',j.result_id!)}>打开评论</button>}{j.type === 'extract' && j.result_id && <button onClick={() => void load(j.result_id!)}>打开文字稿</button>}</div>)}</section>}
    {tab === '设置' && <div className="settings-grid"><section className="panel"><h2>平台凭据</h2><p className="hint">Cookie 加密存入 SQLite；页面不会回显原文。</p><form onSubmit={e => {e.preventDefault(); const form = e.currentTarget; const d = Object.fromEntries(new FormData(form)); void action(async () => { await api('/credentials','POST',d); form.reset() }, '平台凭据已保存') }}><label>名称<input name="name" required placeholder="我的 B站账号" /></label><label>平台<select name="platform">{['bilibili','youtube','douyin','kuaishou'].map(p => <option key={p}>{p}</option>)}</select></label><label>格式<select name="format"><option value="header">Cookie Header</option><option value="netscape">Netscape Cookie 文件内容</option></select></label><label>Cookie<textarea name="cookie" required autoComplete="off" /></label><button disabled={busy} className="primary">保存凭据</button></form>{settings.credentials.map(c => <div className="config-row" key={c.id}><span>{c.name} · {c.platform} · 已加密</span><button onClick={() => void action(() => api('/credentials/'+c.id,'DELETE'), '已删除凭据')}>删除</button></div>)}</section>
    <section className="panel"><h2>模型厂商</h2><p className="hint">支持 OpenAI-compatible 接口；填写厂商提供的完整接口地址。连接测试会发起少量计费请求。</p><form onSubmit={e => {e.preventDefault(); const form = e.currentTarget; const d = Object.fromEntries(new FormData(form)); void action(async () => {await api('/providers','POST',d); form.reset()}, '模型配置已保存') }}><label>配置名称<input name="name" required placeholder="DeepSeek" /></label><label>Base URL<input name="base_url" type="url" required placeholder="https://api.deepseek.com" /></label><label>模型名称<input name="model" required placeholder="deepseek-flash" /></label><label>API Key<input name="api_key" type="password" required autoComplete="new-password" /></label><button className="primary" disabled={busy}>保存模型</button></form>{settings.providers.map(p => <div className="config-row" key={p.id}><span>{p.name} · {p.model}</span><button disabled={busy} onClick={() => void action(() => api('/providers/'+p.id+'/test','POST'), '模型连接成功')}>测试</button><button onClick={() => void action(() => api('/providers/'+p.id,'DELETE'), '已删除模型')}>删除</button></div>)}</section>
    <section className="panel expert-settings"><h2>专家模板</h2><p className="hint">内置专家可编辑，也可创建自己的提示词模板。已有解读保留生成时的模板版本。</p><select aria-label="编辑专家" value={editingExpert} onChange={e => { const id=e.target.value; setEditingExpert(id); const x=settings.experts.find(x=>x.id===id); setExpertName(x?.name || ''); setExpertPrompt(x?.prompt || '') }}><option value="">创建新专家</option>{settings.experts.map(x=><option key={x.id} value={x.id}>{x.name} · v{x.version}</option>)}</select><form onSubmit={e=>{e.preventDefault(); void action(()=>api('/experts'+(editingExpert?'/'+editingExpert:''),editingExpert?'PUT':'POST',{name:expertName,prompt:expertPrompt}),'专家模板已保存')}}><label>专家名称<input required value={expertName} onChange={e=>setExpertName(e.target.value)}/></label><label>专家提示词<textarea required rows={6} value={expertPrompt} onChange={e=>setExpertPrompt(e.target.value)}/></label><button className="primary" disabled={busy}>保存模板</button></form></section></div>}
    <footer>解读内容请结合原文判断 · 数据保存在本地</footer>
  </div>
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
