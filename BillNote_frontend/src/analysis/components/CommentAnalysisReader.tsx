import { useEffect, useRef, useState } from 'react'
import { Download, X, ExternalLink } from 'lucide-react'
import type { CommentAnalysis, CommentSource } from '../types'

const readingBoundary = (text: string) => text
  .replace(/parent_source_id为空且context_missing为true/g, '缺少被回复的原评论，语境不完整')
  .replace(/parent_source_id为空/g, '缺少被回复的原评论')
  .replace(/context_missing为(?:true|真)/g, '回复语境不完整')
  .replace(/context_missing为false且所指原视频片段不在材料中/g, '本次分析未提供所指的原视频片段')
  .replace(/context_missing为false/g, '父评论语境不缺失')
  .replace(/parent缺失/g, '父评论缺失')

function Lines({ values, empty }: {values: string[]; empty: string}) {
  return values.length ? <ul>{values.map((value,index)=><li key={index}>{value}</li>)}</ul> : <p className="comment-unprovided">{empty}</p>
}

export function CommentAnalysisReader({ data }: {data: CommentAnalysis}) {
  const [mode, setMode] = useState<'overview'|'items'>('overview')
  const [source, setSource] = useState<CommentSource|null>(null)
  const [showEmpty, setShowEmpty] = useState(false)
  const [page, setPage] = useState(1)
  const dialog = useRef<HTMLDialogElement>(null)
  const reportHeading = useRef<HTMLHeadingElement>(null)
  const changePage = (next: number) => {
    setPage(next)
    reportHeading.current?.focus({preventScroll:true})
    reportHeading.current?.scrollIntoView({block:'start'})
  }
  const sourceById = new Map(data.sources.map(s=>[s.source_id,s]))
  useEffect(()=>{if(source) dialog.current?.showModal(); else dialog.current?.close()},[source])
  useEffect(()=>setPage(1),[showEmpty,data.id])
  const cite = (ids: string[]) => <span className="comment-citations">{ids.map(id=><button key={id} onClick={()=>setSource(sourceById.get(id)||null)} title="查看生成时的原评论">{id}</button>)}</span>
  const examples = (ids: string[]) => ids.length ? <ul>{ids.map(id=>{const e=data.example_bank[id]; return <li key={id}>{e.description} {cite([e.source_id])}<blockquote>{e.quote}</blockquote></li>})}</ul> : <p className="comment-unprovided">未给出具体举例</p>
  const items = data.items.filter(i=>showEmpty||i.viewpoints.length>0)
  return <section className="comment-analysis-reader" aria-label="评论分析报告">
    <div className="comment-analysis-heading"><div><h3 ref={reportHeading} tabIndex={-1}>评论观点分析</h3><p>{data.model} · 生成于 {new Date(data.generated_at*1000).toLocaleString('zh-CN')}</p></div><div className="exports"><a href={`/api/comment-analyses/${data.id}/export?format=md`}><Download size={12}/>分析 MD</a><a href={`/api/comment-analyses/${data.id}/export?format=json`}>JSON</a></div></div>
    <p className="comment-analysis-scope">本报告分析 {data.stats.selected} / {data.stats.total} 条 · 最少 {data.filters.min_chars} 字，最多 {data.filters.max_chars??'不限'}字 · {data.stats.with_viewpoints} 条含观点 · {data.stats.examples} 个举例条目<br/>搜索：{data.filters.query||'不限'}{data.filters.up_only&&' · 仅 UP 主评论'} · 基于生成时保存的评论；采集范围{data.source_snapshot.scope==='finished'?'为接口当时可见内容':'仅为部分评论'}</p>
    <div className="comment-report-modes" role="tablist" aria-label="评论分析阅读方式"><button role="tab" aria-selected={mode==='overview'} className={mode==='overview'?'active':''} onClick={()=>setMode('overview')}>观点总览</button><button role="tab" aria-selected={mode==='items'} className={mode==='items'?'active':''} onClick={()=>setMode('items')}>逐条解析</button></div>
    <div className="comment-analysis-prose">
      {mode==='overview' ? <><h4>整体总结</h4><p>{data.overview}</p>{data.topics.map((topic,index)=><article className="comment-topic" key={index}><h4>{index+1}. {topic.topic}</h4><dl><dt>观点</dt><dd>{topic.opinion}</dd><dt>结论 / 表达结果</dt><dd><Lines values={topic.outputs} empty="未明确给出结论"/></dd><dt>理由 / 论据</dt><dd><Lines values={topic.reasoning} empty="未提供具体理由"/></dd><dt>举例</dt><dd>{examples(topic.examples)}</dd></dl><div className="comment-topic-sources">观点来源 · {topic.source_ids.length} 条评论 {cite(topic.source_ids)}</div></article>)}<h4>观点分歧</h4>{data.disagreements.length ? data.disagreements.map((d,index)=><article key={index} className="comment-disagreement"><h5>{d.topic}</h5>{d.sides.map((side,i)=><p key={i}>{side.opinion} {cite(side.source_ids)}</p>)}</article>) : <p className="comment-unprovided">未提炼出有明确来源的对立观点</p>}<h4>信息边界</h4><Lines values={data.limits.map(readingBoundary)} empty="请结合原评论核对"/></> : <>
        <label className="check"><input type="checkbox" checked={showEmpty} onChange={e=>setShowEmpty(e.target.checked)}/>同时显示未提炼出观点的评论</label><p className="hint">{items.length} 条解析 · 编号对应本报告保存的评论</p>{items.slice((page-1)*10,page*10).map(item=>{const original=sourceById.get(item.source_id)!;return <article key={item.source_id} className="comment-topic"><h4>{item.source_id} · {original.uname} {cite([item.source_id])}</h4>{item.viewpoints.map((p,index)=><div className="comment-point" key={index}><h5>{p.topic}</h5><dl><dt>观点</dt><dd>{p.opinion}</dd><dt>结论 / 表达结果</dt><dd>{p.output}</dd><dt>理由 / 论据</dt><dd><Lines values={p.reasoning} empty="未提供具体理由"/></dd><dt>举例</dt><dd>{p.examples.length ? <ul>{p.examples.map((e,i)=><li key={i}>{e.description}<blockquote>{e.quote}</blockquote></li>)}</ul> : <p className="comment-unprovided">未给出具体举例</p>}</dd><dt>原话依据</dt><dd><blockquote>{p.quote}</blockquote></dd></dl></div>)}{!item.viewpoints.length&&<p className="comment-unprovided">未提炼出明确观点</p>}<p className="comment-item-boundary">信息边界：{readingBoundary(item.boundary)}</p></article>})}{items.length>10&&<div className="comment-pagination"><button disabled={page===1} onClick={()=>changePage(page-1)}>上一组解析</button><span>{page} / {Math.ceil(items.length/10)}</span><button disabled={page*10>=items.length} onClick={()=>changePage(page+1)}>下一组解析</button></div>}
      </>}
    </div>
    <dialog ref={dialog} className="comment-source-dialog" onClose={()=>setSource(null)} aria-label="报告引用的原评论">{source&&<><div className="comment-analysis-heading"><h3>{source.source_id} · {source.uname}</h3><button autoFocus aria-label="关闭原评论" onClick={()=>setSource(null)}><X size={18}/></button></div><p className="hint">生成时保存的原评论 · {source.char_count} 字 · {source.root==='0'?'主评论':'楼中楼回复'}</p><p className="comment-message">{source.message}</p><a href={`${data.source_snapshot.url}#reply${source.rpid}`} target="_blank" rel="noreferrer">打开 B站原评论 <ExternalLink size={12}/></a></>}</dialog>
  </section>
}
