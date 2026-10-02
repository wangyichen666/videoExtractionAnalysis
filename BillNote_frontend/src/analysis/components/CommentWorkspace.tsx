import { useEffect, useMemo, useState } from 'react'
import { MessageSquare, Download, Search, ChevronDown, ExternalLink, ThumbsUp } from 'lucide-react'
import type { CommentSnapshot, RecordData, VideoComment, CommentAnalysis } from '../types'

import { CommentAnalysisReader } from './CommentAnalysisReader'

const commentLength = (text: string) => Array.from(text.replace(/[\s\u0085\u001c-\u001f]/gu,'')).length

type Props = {
  records: CommentSnapshot[]; analysisRecords: CommentAnalysis[]; providers: RecordData[]; jobs: RecordData[]; credentials: RecordData[]; busy: boolean;
  initialUrl: string; initialReportId: string; recordId: string; setRecordId: (id: string) => void;
  api: (path: string, method?: string, data?: unknown) => Promise<any>;
  action: (fn: () => Promise<unknown>, success: string) => Promise<void>;
}
const date = (time: number) => time ? new Date(time*1000).toLocaleString('zh-CN') : '时间未知'

function CommentBody({ row, url, child = false, context = false }: {row: VideoComment; url: string; child?: boolean; context?: boolean}) {
  return <div className={child ? 'comment-row child-comment' : 'comment-row'} id={`comment-${row.rpid}`}>
    <div className="comment-author"><strong>{row.uname || '匿名用户'}</strong>{row.is_up_reply && <span className="badge">UP 主</span>}{row.top_type > 0 && <span className="badge">置顶</span>}<time>{date(row.ctime)}</time></div>
    {context&&<p className="comment-context-only">仅作线程上下文 · 未纳入筛选与模型分析</p>}<p className="comment-message">{row.message}</p>
    <div className="comment-meta"><span><ThumbsUp size={13} />{row.like.toLocaleString()}</span><span>{commentLength(row.message)} 字</span>{!child && row.rcount > 0 && <span>{row.rcount} 条平台回复</span>}<a href={`${url}#reply${row.rpid}`} target="_blank" rel="noreferrer">原评论 <ExternalLink size={12}/></a></div>
  </div>
}

export function CommentWorkspace({ records, analysisRecords, providers, jobs, credentials, busy, initialUrl, initialReportId, recordId, setRecordId, api, action }: Props) {
  const [url, setUrl] = useState(initialUrl)
  const [credential, setCredential] = useState(() => credentials.find(c => c.platform === 'bilibili')?.id || '')
  const [cookie, setCookie] = useState('')
  const [order, setOrder] = useState('hot')
  const [maxTop, setMaxTop] = useState(100)
  const [maxTotal, setMaxTotal] = useState(1000)
  const [includeReplies, setIncludeReplies] = useState(true)
  const [detail, setDetail] = useState<CommentSnapshot | null>(null)
  const [loadError, setLoadError] = useState('')
  const [query, setQuery] = useState('')
  const [minChars, setMinChars] = useState(20)
  const [maxChars, setMaxChars] = useState('')
  const [analysisProvider, setAnalysisProvider] = useState(providers[0]?.id || '')
  const [analysisId, setAnalysisId] = useState(initialReportId)
  const [analysisDetail, setAnalysisDetail] = useState<CommentAnalysis|null>(null)
  const [readingMode, setReadingMode] = useState<'comments'|'analysis'>(initialReportId?'analysis':'comments')
  const [sort, setSort] = useState('likes')
  const [upOnly, setUpOnly] = useState(false)
  const [page, setPage] = useState(1)
  const initialBvid = initialUrl.match(/BV[0-9A-Za-z]{10}/)?.[0]
  const activeId = recordId || (initialUrl ? records.find(r =>
    (initialBvid && r.video_id === initialBvid) || r.url === initialUrl)?.id : records[0]?.id)
  const summary = records.find(r => r.id === activeId)
  const activeJobs = jobs.filter(j => j.type === 'comments' && j.result_id === activeId)
  const running = activeJobs.find(j => j.status === 'running' || j.status === 'queued')
  const failed = !running && activeJobs[0]?.status === 'failed' ? activeJobs[0] : undefined
  const [compact, setCompact] = useState(() => matchMedia('(max-width:1100px)').matches)
  useEffect(() => {const media=matchMedia('(max-width:1100px)'); const handler=()=>setCompact(media.matches); media.addEventListener('change',handler); return()=>media.removeEventListener('change',handler)}, [])
  useEffect(() => { if(initialUrl) setUrl(initialUrl) }, [initialUrl])
  useEffect(() => {
    setDetail(null); setLoadError(''); setQuery(''); setPage(1)
  }, [activeId])
  useEffect(() => {
    if(!summary?.id) return
    let live = true
    void api('/comments/'+summary.id).then(d=>{if(live) {setDetail(d); setLoadError('')}}).catch(e=>{if(live) setLoadError((e as Error).message)})
    return()=>{live=false}
  }, [summary?.id, summary?.generated_at])
  useEffect(()=>setPage(1),[query,sort,upOnly,minChars,maxChars])
  useEffect(()=>{setAnalysisProvider(p=>providers.some(v=>v.id===p)?p:providers[0]?.id||'')},[providers])
  const currentAnalyses=analysisRecords.filter(r=>r.comments_id===activeId)
  const currentAnalysis=currentAnalyses.find(r=>r.id===analysisId)||currentAnalyses[0]
  const analysisJob=jobs.find(j=>j.type==='comment_analysis'&&j.request?.comments_id===activeId&&(j.status==='queued'||j.status==='running'))
  const latestAnalysisJob=jobs.find(j=>j.type==='comment_analysis'&&j.request?.comments_id===activeId)
  useEffect(()=>{if(!currentAnalysis?.id){setAnalysisDetail(null);return} let live=true;void api('/comment-analyses/'+currentAnalysis.id).then(d=>{if(live)setAnalysisDetail(d)}).catch(e=>{if(live)setLoadError((e as Error).message)});return()=>{live=false}},[currentAnalysis?.id])
  const filterValid=minChars>=0&&minChars<=20000&&(maxChars===''||(Number(maxChars)>=minChars&&Number(maxChars)<=20000))
  const matchingComments=useMemo(()=> (detail?.comments||[]).filter(c=>filterValid&&commentLength(c.message)>=minChars&&(maxChars===''||commentLength(c.message)<=Number(maxChars))&&(!upOnly||c.is_up_reply)&&(!query.trim()||(c.message+' '+c.uname).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))),[detail,filterValid,minChars,maxChars,query,upOnly])
  const matchingIds=new Set(matchingComments.map(c=>c.rpid))
  const filters={min_chars:minChars,max_chars:maxChars===''?null:Number(maxChars),query:query.trim(),up_only:upOnly}
  const filterChanged=analysisDetail&&(analysisDetail.filters.min_chars!==filters.min_chars||analysisDetail.filters.max_chars!==filters.max_chars||analysisDetail.filters.query!==filters.query||analysisDetail.filters.up_only!==filters.up_only)
  const overLimit=matchingComments.length>500||matchingComments.reduce((n,c)=>n+Array.from(c.message).length,0)>100000||matchingComments.some(c=>Array.from(c.message).length>12000)

  const threads = useMemo(() => {
    const all = detail?.comments || []
    const children = new Map<string,VideoComment[]>()
    all.filter(c=>c.root!=='0').forEach(c=>children.set(c.root,[...(children.get(c.root)||[]),c]))
    const matching=new Set(matchingComments.map(c=>c.rpid)); const matches=(c: VideoComment)=>matching.has(c.rpid)
    const filtered = all.filter(c=>c.root==='0').map(root=>({root,replies:(children.get(root.rpid)||[]).filter(matches).sort((a,b)=>a.ctime-b.ctime)}))
      .filter(t=>matches(t.root)||t.replies.some(matches))
    return filtered.sort((a,b)=>sort==='latest' ? b.root.ctime-a.root.ctime : sort==='oldest' ? a.root.ctime-b.root.ctime : b.root.like-a.root.like)
  }, [detail,matchingComments,sort])
  const shown = threads.slice((page-1)*20,page*20)
  const choose = (id: string) => { setRecordId(id); setPage(1) }
  const range = detail && <><p>{detail.stop_reason || (detail.scope==='finished' ? '已遍历接口当前可见的评论' : '本次采集尚未完成')}</p><p>平台报告 {detail.counts.declared_total?.toLocaleString() ?? '未知'} 条；已保存 {detail.counts.total.toLocaleString()} 条。数量会受删除、隐藏及采集期间变化影响。</p><p>采集顺序：{detail.request_options.order==='hot'?'热门':'最新'}<br/>主评论上限 {detail.request_options.max_top} · 总上限 {detail.request_options.max_total}<br/>{detail.request_options.include_replies ? '包含楼中楼' : '仅主评论'}</p><time>更新于 {date(detail.generated_at)}</time><p><a href={detail.url} target="_blank" rel="noreferrer">查看原视频 <ExternalLink size={12}/></a></p></>
  return <div className="workspace comments-workspace"><aside className="panel input-panel">
    <details className="new-task" open={!activeId || !compact}><summary>采集视频评论</summary><form onSubmit={e=>{e.preventDefault(); void action(async()=>{const result=await api('/comment-jobs','POST',{url,credential_id:credential||null,cookie,order,max_top:maxTop,max_total:maxTotal,include_replies:includeReplies}); setRecordId(result.result_id); setCookie('')},'评论任务已加入队列')}}>
      <label>视频链接或 BV 号<input required value={url} onChange={e=>setUrl(e.target.value)} placeholder="https://www.bilibili.com/video/…" /></label>
      <label>评论采集 Cookie<select value={credential} onChange={e=>setCredential(e.target.value)}><option value="">不使用已保存凭据</option>{credentials.filter(c=>c.platform==='bilibili').map(c=><option value={c.id} key={c.id}>{c.name}</option>)}</select></label>
      <details><summary>本次临时 Cookie</summary><textarea aria-label="评论临时 Cookie" value={cookie} onChange={e=>setCookie(e.target.value)} placeholder="仅用于本次评论采集" autoComplete="off"/></details>
      <label>采集顺序<select value={order} onChange={e=>setOrder(e.target.value)}><option value="hot">热门评论优先</option><option value="latest">最新评论优先</option></select></label>
      <div className="comment-limits"><label>主评论上限<input type="number" required min={1} max={1000} value={maxTop} onChange={e=>setMaxTop(Number(e.target.value))}/></label><label>总评论上限<input type="number" required min={maxTop} max={5000} value={maxTotal} onChange={e=>setMaxTotal(Number(e.target.value))}/></label></div>
      <label className="check"><input type="checkbox" checked={includeReplies} onChange={e=>setIncludeReplies(e.target.checked)}/>包含楼中楼回复</label>
      <button className="primary" disabled={busy||!!running}> {running?'采集中…':'开始采集评论'}</button>
      <p className="hint">支持 B站评论。读取受平台权限、评论可见性及采集上限影响。</p>
    </form></details>
    <details className="library-list" open={!compact}><summary>评论资料库 · {records.length} 份</summary>{records.length===0&&<p className="hint">采集完成后可随时查看。</p>}{records.map(r=><button className={'history-item '+(activeId===r.id?'selected-comment-record':'')} key={r.id} onClick={()=>choose(r.id)}>{r.title}<small>{r.counts.total} 条 · {r.status==='collecting'?'采集中':r.status==='interrupted'?'采集中断':r.scope==='finished'?'已遍历可见评论':'部分评论'}</small></button>)}</details>
  </aside><main className="panel result comments-result">
    <div className="result-head"><div className="result-title"><h2>{detail?.title || '视频评论'}</h2><p className="panel-description">查看观众讨论，按线程阅读和筛选</p>{detail&&<div className="document-meta"><span>{detail.counts.top_level} 条主评论</span><span>{detail.counts.nested} 条楼中楼</span><span className="badge">{detail.status==='collecting'?'采集中':detail.status==='interrupted'?'采集中断':detail.scope==='finished'?'已遍历可见评论':'部分评论'}</span></div>}</div>{detail&&<div className="exports">{['json','jsonl','md'].map(f=><a key={f} href={`/api/comments/${detail.id}/export?format=${f}`}><Download size={12}/>{f.toUpperCase()}</a>)}</div>}</div>
    {running&&<div className="task-progress" role="status">{running.phase} · 可离开页面，任务会继续</div>}
    {failed&&<div className="comment-error" role="alert"><p>{failed.error}</p><button disabled={busy} onClick={()=>void action(()=>api('/jobs/'+failed.id+'/retry','POST'),'已安排继续采集')}>重试采集</button></div>}
    {loadError&&<p role="alert" className="warning">{loadError}</p>}
    {!detail ? <div className="empty"><MessageSquare size={30}/><h3>{running?'正在读取评论':'阅读视频之外的讨论'}</h3><p>输入链接采集，或选择一份已保存的评论。</p></div> : <>
      <div className="comment-filters"><label className="comment-search"><Search size={16}/><input aria-label="搜索评论" placeholder="搜索评论内容或作者" maxLength={200} value={query} onChange={e=>setQuery(e.target.value)}/></label><label>阅读排序<select aria-label="评论阅读排序" value={sort} onChange={e=>setSort(e.target.value)}><option value="likes">点赞最多</option><option value="latest">时间从新到旧</option><option value="oldest">时间从旧到新</option></select></label><label className="check"><input type="checkbox" checked={upOnly} onChange={e=>setUpOnly(e.target.checked)}/>仅 UP 主评论</label></div>
      <div className="comment-length-filters"><label>最少字数<input type="number" min={0} max={20000} value={minChars} onChange={e=>setMinChars(Number(e.target.value))}/></label><label>最多字数<input type="number" min={minChars} max={20000} value={maxChars} placeholder="不限" onChange={e=>setMaxChars(e.target.value)}/></label><p>{matchingComments.length} / {detail.counts.total} 条通过筛选 · 按每条评论字数，不含空白，标点与表情计入</p></div>
      {!filterValid&&<p className="warning" role="alert">最大字数不能小于最小字数，范围为0—20000。</p>}
      <section className="comment-analysis-controls" aria-label="评论模型分析"><form onSubmit={e=>{e.preventDefault();void action(async()=>{await api('/comment-analyses','POST',{comments_id:detail.id,provider_id:analysisProvider,...filters});setAnalysisId('');setReadingMode('analysis')},'开始分析筛选后的评论')}}><label>评论分析模型<select value={analysisProvider} onChange={e=>setAnalysisProvider(e.target.value)}><option value="">选择模型配置</option>{providers.map(p=><option key={p.id} value={p.id}>{p.name} · {p.model}</option>)}</select></label><button className="primary" disabled={busy||!!analysisJob||!analysisProvider||!filterValid||!matchingComments.length||overLimit||detail.status==='collecting'}>{analysisJob?'分析中…':`分析筛选后的 ${matchingComments.length} 条评论`}</button></form><p className="hint">提炼观点、结论、理由与举例；只发送通过筛选的评论，会产生模型调用费用。</p>{overLimit&&<p className="warning">单次最多500条、10万字符；单条不超过12000字符，请收紧筛选条件。</p>}{!analysisProvider&&<p className="hint">请先在设置中添加模型配置。</p>}{analysisJob&&<p className="task-progress" role="status">{analysisJob.phase}</p>}{!analysisJob&&latestAnalysisJob?.status==='failed'&&<div className="comment-error" role="alert"><p>{latestAnalysisJob.error}</p><button disabled={busy} onClick={()=>void action(()=>api('/jobs/'+latestAnalysisJob.id+'/retry','POST'),'已安排重试评论分析')}>重试评论分析</button><small>重试保留原筛选和生成时的评论快照。</small></div>}</section>
      <div className="comment-view-controls"><div className="comment-report-modes" role="tablist" aria-label="评论页面阅读方式"><button role="tab" aria-selected={readingMode==='comments'} className={readingMode==='comments'?'active':''} onClick={()=>setReadingMode('comments')}>评论列表</button><button role="tab" aria-selected={readingMode==='analysis'} className={readingMode==='analysis'?'active':''} onClick={()=>setReadingMode('analysis')}>模型分析</button></div>{currentAnalyses.length>0&&<label>历史评论分析<select aria-label="选择历史评论分析" value={currentAnalysis?.id||''} onChange={e=>{setAnalysisId(e.target.value);setReadingMode('analysis')}}>{currentAnalyses.map(a=><option value={a.id} key={a.id}>{a.model} · {a.stats.selected} 条 · {date(a.generated_at)}</option>)}</select></label>}</div>
      {readingMode==='analysis'?<>{filterChanged&&<p className="warning">当前筛选与本报告不同；报告保留生成时的条件，重新分析后才会更新。</p>}{currentAnalysis?analysisDetail?.id===currentAnalysis.id?<CommentAnalysisReader key={currentAnalysis.id} data={analysisDetail}/>:<p role="status">正在加载评论分析…</p>:<div className="report-empty">{analysisJob?'正在提炼评论观点，完成后会显示在这里。':'选择字数范围和模型，生成评论观点分析。'}</div>}</>:<div className="comment-reading-grid"><section className="comment-thread-list" aria-label="评论线程"><p className="comment-match-count">{threads.length} 个匹配线程 · {matchingComments.length} 条评论纳入筛选与分析</p>{threads.length===0&&<p className="report-empty">{detail.counts.total===0?'尚未采集到可见评论。':'没有匹配评论，请调整筛选条件。'}</p>}{shown.map(({root,replies})=><article className="comment-thread" key={root.rpid}><CommentBody row={root} url={detail.url} context={!matchingIds.has(root.rpid)}/>{replies.length>0&&<details className="comment-replies" open={!!query.trim()||upOnly||!matchingIds.has(root.rpid)}><summary><ChevronDown size={14}/>{replies.length} 条已采集回复</summary>{replies.map(r=><CommentBody row={r} url={detail.url} child key={r.rpid}/>)}</details>}</article>)}{threads.length>20&&<div className="comment-pagination"><button disabled={page===1} onClick={()=>setPage(p=>p-1)}>上一页</button><span>第 {page} / {Math.ceil(threads.length/20)} 页</span><button disabled={page*20>=threads.length} onClick={()=>setPage(p=>p+1)}>下一页</button></div>}</section><aside className="comment-range"><h3>采集范围</h3>{range}</aside></div>}
      <details className="comment-range-compact"><summary>采集范围与来源</summary>{range}</details>
    </>}
  </main></div>
}
