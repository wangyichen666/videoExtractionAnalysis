import { useState } from 'react'
import { BookOpen, FileText, Download, List, ScanText } from 'lucide-react'
import ReactMarkdown from 'analysis-markdown'
import remarkGfm from 'analysis-gfm'
import type { RecordData, Correction } from '../types'

function jump(id: string, source = false) {
  const target = document.getElementById(id)
  if (source) { const detail = target?.closest('details'); if (detail) detail.open = true }
  const behavior = matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'
  target?.scrollIntoView({ behavior, block: source ? 'center' : 'start' })
  target?.focus({ preventScroll: true })
}

function Corrections({ items }: { items: Correction[] }) {
  return <div className="correction-items">{!items.length && <p className="hint">本篇未记录明确的词句校准。</p>}{items.map((c, i) => <div className="correction-item" key={i}><span className={`badge ${c.status === 'uncertain' ? 'uncertain' : ''}`}>{c.status === 'applied' ? '已校准' : '待确认'}</span><strong>{c.original}</strong><p className="correction-suggestion">{c.suggestion}</p><p>{c.reason}</p><div>{c.evidence_ids.map(id => <button className="text-button" key={id} onClick={() => jump(`segment-${id}`, true)}>核对原文 · 第 {id} 段</button>)}</div></div>)}</div>
}

function CompanyIdentities({ items }: { items: NonNullable<RecordData['entity_candidates']> }) {
  return <ul className="company-identities">{items.map(c => <li key={c.code}><strong>{c.status === 'candidate' ? '疑似 ' : ''}{c.name}（{c.code}，{c.market}）</strong><span>原稿写法：{c.matched_terms.join('、')}</span><a href={c.source_url} target="_blank" rel="noreferrer">核对公司官方页面</a></li>)}</ul>
}

export function ReportReader({ analysis }: { analysis: RecordData }) {
  const [view, setView] = useState<'analysis' | 'article'>('analysis')
  const [chapter, setChapter] = useState('all')
  const sections = (analysis.sections || []).filter(s => s.id !== 'actions')
  const reportText = analysis.sections?.length ? sections.map(s => `## ${s.title}\n\n${s.text}`).join('\n\n') : analysis.text || ''
  const article = analysis.article
  const isArticle = view === 'article'
  const text = isArticle ? article?.text || '' : chapter === 'all' ? reportText : sections.find(s => s.id === chapter)?.text || ''
  const isFinance = analysis.profile?.startsWith('finance-')
  return <article className={`analysis report-reader ${isFinance ? 'finance-report' : ''}`}>
    <div className="reader-toolbar"><div className="reader-modes" role="tablist" aria-label="阅读方式"><button role="tab" aria-selected={!isArticle} onClick={() => setView('analysis')}><ScanText size={16}/>专家解读</button><button role="tab" aria-selected={isArticle} disabled={!article} title={!article ? '历史结果暂无整理文章' : undefined} onClick={() => setView('article')}><BookOpen size={16}/>整理文章</button></div><a className="download-action" href={`/api/analyses/${analysis.id}/export?output=${view}`}><Download size={15}/>下载{isArticle ? '文章' : '解读'}</a></div>
    <div className="report-head"><span>{analysis.execution_kind === 'conversation_reference' ? '会话参考' : '模型生成'}</span><span>{analysis.model} · 模板 v{analysis.expert_version}</span><span>{isArticle ? '书面整理 · 保留原视频观点' : '结合原文理解与判断'}</span></div>
    {isFinance && <div className="report-source">{analysis.source_url && <a href={analysis.source_url} target="_blank" rel="noreferrer">查看原视频</a>}{analysis.generated_at && <span>生成于 {new Date(analysis.generated_at * 1000).toLocaleString('zh-CN', {hour12: false})}</span>}<span>以视频录制时的市场与观点为准</span></div>}
    {!isArticle && sections.length > 0 && <nav className="report-tabs" aria-label="解读章节"><button className={chapter === 'all' ? 'active' : ''} onClick={() => setChapter('all')}>全部</button>{sections.map(s => <button key={s.id} className={chapter === s.id ? 'active' : ''} onClick={() => setChapter(s.id)}>{s.title}</button>)}</nav>}
    {isArticle && !!article?.validation_warnings?.length && <p className="quality-warning">{article.validation_warnings.length} 条校准建议未能与原稿逐字对齐，已排除。涉及专名时请回看原文确认。</p>}
    <div className={isArticle ? 'article-layout' : `analysis-layout ${isFinance && analysis.entity_candidates?.length ? 'finance-analysis-layout' : ''}`}>
      {isArticle && article && <aside className="article-nav"><details className="article-directory" open><summary><List size={15}/>文章目录 <span>{article.sections.length}</span></summary><div>{article.sections.map((s, i) => <button key={s.id} onClick={() => jump(`${analysis.id}-${s.id}`)}><span>{String(i+1).padStart(2,'0')}</span>{s.title}</button>)}</div></details></aside>}
      <div className={`markdown ${isArticle ? 'article-prose' : isFinance ? 'finance-prose' : ''}`}><ReactMarkdown remarkPlugins={[remarkGfm]} components={{ h2: ({ children }) => <h2 tabIndex={-1} id={isArticle ? `${analysis.id}-${article?.sections.find(s => s.title === String(children))?.id}` : undefined}>{children}</h2>, a: ({ href, children }) => href?.startsWith('#segment-') ? <a className="source-citation" href={href} onClick={e => {e.preventDefault(); jump(href.slice(1), true)}}>{children}</a> : <a href={href} target="_blank" rel="noreferrer">{children}</a> }}>{text}</ReactMarkdown></div>
      {!isArticle && isFinance && !!analysis.entity_candidates?.length && <aside className="finance-evidence"><h3>公司名称核对</h3><p className="hint">官方页面只核对身份。疑似名称仍需回听，视频财务数据未核实。</p><CompanyIdentities items={analysis.entity_candidates}/></aside>}
      {isArticle && <aside className="article-evidence"><h3><FileText size={15}/>文字校准 <span>{article?.corrections.length || 0}</span></h3><p className="hint">对照原稿核实名称与语义，原始字幕始终保留。</p><Corrections items={article?.corrections || []}/></aside>}
    </div>
    {isArticle && <details className="correction-log"><summary>文字校准记录 · {article?.corrections.length || 0} 处</summary><p className="hint">“已校准”仍应结合上下文或回听确认。</p><Corrections items={article?.corrections || []}/></details>}
    {isFinance && !!analysis.entity_candidates?.length && <details className="finance-identities"><summary>公司名称与代码核对 · {analysis.entity_candidates.length} 项</summary><p className="hint">官方页面只用于核对公司身份。疑似名称仍需回听，不代表视频财务数据已核实。</p><CompanyIdentities items={analysis.entity_candidates}/></details>}
  </article>
}
