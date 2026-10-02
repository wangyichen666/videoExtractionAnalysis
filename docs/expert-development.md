# 专家模式与输出契约

## 各层职责

- `backend/analysis_app/expert_profiles.py`：专家预设、视角、章节、输出能力、默认模板迁移。程序员v3与财经v2各有六章，通用/自定义共享对应结构。
- `backend/analysis_app/report_engine.py`：分片、结构校验、有限修复、证据聚合、文章校准与目录编排。与视频标题、平台、专家名称无硬编码关系。
- `backend/analysis_app/pipeline.py`：供应商 HTTP 协议、超时、输出截断检查、token 统计。专家和原稿进入请求，平台 Cookie 不进入请求。
- `backend/analysis_main.py`：任务快照、结果入库、元信息列表、详情和两类导出。
- `BillNote_frontend/src/analysis/components/ReportReader.tsx`：按结果数据渲染解读/文章、章节/目录、原文定位和校准记录。页面不自行生成分析内容。
- `scripts/save_reference_article.py`：当前视频的会话参考材料导入，独立于生产生成路径；未调用网页模型，旧参考记录保留。

## 结果契约 v2

```text
schema_version: 2
expert_id / expert_version / expert_snapshot: 生成时专家身份与模板
profile: 生成使用的章节配置
sections: [{id, title, text}]  专家解读
text: 专家解读 Markdown（兼容旧字段）
article: {title, text, sections: [{id,title,text}], corrections: [...]}
corrections: [{original,suggestion,reason,status: applied|uncertain,evidence_ids:[整数]}]
evidence_notes: [{category,content,evidence_ids}]
execution_kind: provider | conversation_reference
usage: {prompt_tokens,completion_tokens}
```

程序员章节：summary、viewpoints、glossary、engineering、questions、uncertainty。没有行动清单。旧金融v1用 finance 替换 engineering；财经v2使用 summary/market/holdings/policy/risks/conclusions，通用/自定义用 implications。UI 根据接口的章节和 outputs 显示能力，不通过专家中文名判断功能。

## 成文流程与可靠性边界

1. 所有原始字幕按 6000 字符分片，超长单段继续拆分并保留同一原文段号。
2. 每片同时整理证据、书面段落及校准记录。文章只允许来自视频的观点、论证和实例，不混入专家知识。每段有真实片段范围内的证据段号。
3. 校准原词必须逐字出现在引用片段；有上下文依据的修改记录 applied，未能确认的专名记录 uncertain。不匹配的校准记录排除，并在文章显示 validation_warnings，避免把意译或错位记录当作校准依据。原字幕不被覆盖。
4. 分片之后有独立文章编辑阶段：用原始材料和校准建议（不再次注入口语初稿），改成直接围绕主题展开的书面段落，保留论证和视频例子；每片正文最多3200字符、每段最多600字符。标为 applied 的校准建议若没有进入最终文章，则降为 uncertain。连续出现对话转述框架时要求重写。总结、一般章节、术语章节分别有3000/6000/8000字符上限（原始模型文本，渲染时间链接会增加字符），超限或非法引用至多修复一次。
5. 目录只统一各片标题，不重新压缩整篇文章，保留全部片段的正文。专家章节分别基于证据整理，超过输入上限时分组归纳。
6. JSON 或段号异常至多重生成一次，仍失败则标记任务失败。仅允许补齐可明确解析的顶层最后一个右括号，不补截断正文。输出长度受限时扩大预算重试一次，上限16000 tokens，仍截断则失败。空结果、目录遗漏、无效正文引用不会标成成功。所有章节完整生成后才入库。
7. 每个通过校验的分片、证据归纳和章节写入 SQLite 检查点。失败任务重试继承 namespace，复用已完成阶段；重新生成创建新 namespace，原稿、专家快照或模型配置变化使缓存失效。usage 仅统计本次执行新发出的请求（含修复与长度重试），不包含缓存的历史请求。
8. 一段正文可以对应大量有效原文段号，底层保留完整 evidence_ids，页面与汇总提示词只选少量代表定位，避免错误地因证据多而拒绝结果。

这能固定结构、保留处理覆盖范围并识别部分错误，不能从程序层面证明每个语义判断正确。校准需要回听；模型可能遗漏观点或错误理解，因此重要结论仍应复核。供应商兼容性、内容质量和成本须用配置的模型验证。DeepSeek 官方域名专用参数关闭默认 thinking，JSON阶段启用 json_object；其它 OpenAI-compatible 厂商不附带这些参数。真实运行证据见 artifacts 下的 DeepSeek 报告，不能把会话参考稿作为供应商实测。

## 增加专家与向后兼容

创建自定义专家时默认使用 custom-v1，保留用户提示词；如需要新的固定章节，在 PROFILES 注册独立 profile，API 模板持久化其 metadata。不要按视频标题或某个 BV 号分支生成内容。

内置旧程序员默认提示词迁移到 v3；被用户修改的提示词不覆盖。模板版本与结果 schema_version 分开。已有结果、提示词快照及 API Key 配置不覆盖。历史无 article 的报告仍能阅读/下载解读，文章入口显示“历史结果暂无文章”；旧行动章节在阅读/导出时隐藏，原记录保留。

`GET /api/analyses?summary=true` 用于轻量轮询，正文通过 `GET /api/analyses/{id}` 按需加载。无 query 的列表保留旧接口。导出使用 `GET /api/analyses/{id}/export?output=analysis|article`。

## 验证

运行 `.venv/bin/python -m pytest backend/analysis_tests -q`，前端 `pnpm --dir BillNote_frontend check:analysis` 与 `build:analysis`。覆盖四类专家、版本迁移、自定义保留、完整分片、文章不丢片段、有限格式修复、非法引用/校准原词拒绝、模型协议和双导出、旧结果兼容。


财经v2：短视频直接依据全部原稿整篇编排，长视频各财经章交叉读取全体证据笔记；输出与共享阅读/编辑契约一致。有限身份候选、来源核对、篇幅和数字规则见 docs/finance-development.md。文章目录现在也经过有限格式/数量修复与检查点缓存，按章节标题输入hash失效。
