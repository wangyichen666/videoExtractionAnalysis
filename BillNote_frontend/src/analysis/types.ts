export type ReportSection = { id: string; title: string; text: string }
export type Correction = { original: string; suggestion: string; reason: string; status: 'applied' | 'uncertain'; evidence_ids: number[] }
export type ArticleData = { title: string; text: string; sections: ReportSection[]; corrections: Correction[]; validation_warnings?: {original: string; reason: string; evidence_ids: number[]}[] }
export type RecordData = {
  sections?: ReportSection[]; article?: ArticleData; execution_kind?: string; profile?: string; schema_version?: number;
  url?: string; video_id?: string; outputs?: string[]; id: string; name?: string; title?: string; platform?: string; format?: string; model?: string;
  generated_at?: number; source_url?: string;
  entity_candidates?: {name: string; code: string; market: string; status: string; matched_terms: string[]; source_url: string}[];
  prompt?: string; version?: number; expert_version?: number; status?: string; phase?: string; error?: string;
  type?: string; result_id?: string; text?: string; source?: string; expert?: string; expert_id?: string;
  expert_snapshot?: { id?: string; profile?: string }; transcript_id?: string; request?: { transcript_id?: string; expert_id?: string; comments_id?: string; url?: string };
  segments?: { start: number; end: number; text: string }[];
}

export type VideoComment = {rpid: string; root: string; parent: string; uname: string; ctime: number; ctime_iso: string; message: string; like: number; rcount: number; is_up_reply: boolean; top_type: number}
export type CommentSnapshot = {id: string; title: string; url: string; video_id?: string; generated_at: number; status: string; scope: string; stop_reason: string; main_exhausted: boolean;
  counts: {total: number; top_level: number; nested: number; pinned: number; up_replies: number; declared_total?: number};
  request_options: {order: 'hot'|'latest'; max_top: number; max_total: number; include_replies: boolean}; comments?: VideoComment[]}

export type CommentFilters = {min_chars: number; max_chars: number|null; query: string; up_only: boolean}
export type CommentSource = VideoComment & {source_id: string; char_count: number}
export type CommentPoint = {topic: string; opinion: string; output: string; reasoning: string[]; examples: {description: string; quote: string}[]; quote: string}
export type CommentAnalysis = {id: string; comments_id: string; model: string; provider: string; generated_at: number; filters: CommentFilters;
  source_snapshot: {id: string; title: string; url: string; generated_at: number; scope: string};
  stats: {selected: number; total: number; characters: number; top_level: number; nested: number; with_viewpoints: number; viewpoints: number; examples: number};
  overview: string; topics: {topic: string; opinion: string; outputs: string[]; reasoning: string[]; examples: string[]; source_ids: string[]}[];
  disagreements: {topic: string; sides: {opinion: string; source_ids: string[]}[]}[]; limits: string[];
  sources: CommentSource[]; items: {source_id: string; viewpoints: CommentPoint[]; boundary: string}[];
  example_bank: Record<string,{source_id: string; description: string; quote: string}>}
