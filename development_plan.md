# 视频文字提取与专家解读：开发计划

调研日期：2026-10-01。基于指定前序会话和 GitHub README、许可证、部分核心源码。当前目录原为空，未初始化 Git。本轮仅输出计划；尚未部署或用真实视频、Cookie、API Key 实测。

## 1. 结论与复用策略

推荐以 [JefferyHcool/BiliNote](https://github.com/JefferyHcool/BiliNote) 为候选底座，通过 fork 二次开发。先验证现有链路，再增加文字提取独立入口、SQLite 凭据管理、专家配置与多次解读。保留已有 React/Vite 前端、FastAPI 后端、SQLAlchemy/SQLite、平台适配器、转写接口、模型厂商设置和部署文件，不重新实现下载器或 ASR。

本次源码核验基线：master，提交 `90940fde4d224d0f69ad99674f4af0a1ea52d3c4`。正式开发固定通过验收的提交和依赖版本，保留 MIT 版权声明，并记录上游合并策略。

此推荐是基于需求匹配和源码抽查的工程判断；实际底座选择需要通过阶段 0 的可运行性验证。

## 2. 开源项目比较

| 项目 | 已核验能力及许可证 | 本项目用途与取舍 |
| --- | --- | --- |
| [BiliNote](https://github.com/JefferyHcool/BiliNote) | MIT；网页前后端、多平台适配、字幕优先、ASR、模型配置与历史 | 首选底座；平台可用性需逐项实测，Cookie 与工作流需要改造 |
| [BiliSum](https://github.com/lycohana/BiliSum) | MIT；FastAPI/SQLite、React、Docker 网页访问；桌面端与 CLI；多种模型协议 | 备选底座，参考多 P、重跑与模型适配；产品包含较多知识库/桌面功能，首期不必引入 |
| [video-summary-tool](https://github.com/Entropy-R/video-summary-tool) | MIT；Docker CLI、字幕优先、faster-whisper、只转写模式、可选画面阅读 | 参考提取/总结拆分与多模态流程；缺少目标网页和设置管理，不作为主要底座 |
| [bili-transcript](https://github.com/uraraneko/bili-transcript) | MIT；B 站 CLI、字幕/转写、TXT/SRT/JSON、显式浏览器 Cookie 选项 | 参考字幕归一化与导出，作为对照验证工具；功能范围不足以覆盖网页 |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | 源码主要采用 Unlicense；发布包及部分组件需单独核对 | 沿用上游依赖，负责站点提取与音频下载；支持列表不等于所有视频均可成功 |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT；基于 CTranslate2 的 Whisper 转写 | 沿用本地 ASR 接口；按硬件选择 CPU/GPU，另核对模型权重许可 |
| [LiteLLM](https://github.com/BerriAI/litellm) | 多厂商 SDK/网关；许可证需按具体目录核对，仓库 API 标为 Other | 仅作为后续原生协议适配备选，首期不部署完整网关 |

上述项目在 GitHub API 检查时均未归档。未用 star 数或最近提交直接推断稳定性。

## 3. 源码核验发现与改造位置

固定提交下的 [文字流程](https://github.com/JefferyHcool/BiliNote/blob/90940fde4d224d0f69ad99674f4af0a1ea52d3c4/backend/app/services/note.py) 已按缓存→平台字幕→音频转写执行，但 `generate()` 提前创建 GPT 实例，初始化时也创建转写器，最终继续生成笔记。因此新增“只提取文字”不能只隐藏网页总结按钮：需要拆分服务、延迟初始化 ASR，使有字幕时不依赖模型下载或 LLM Key。

[Cookie 管理](https://github.com/JefferyHcool/BiliNote/blob/90940fde4d224d0f69ad99674f4af0a1ea52d3c4/backend/app/services/cookie_manager.py) 当前按平台保存在 `config/downloader.json`。新增 SQLite 凭据仓库，保持兼容接口，提供一次性迁移。

[B 站下载器](https://github.com/JefferyHcool/BiliNote/blob/90940fde4d224d0f69ad99674f4af0a1ea52d3c4/backend/app/downloaders/bilibili_downloader.py) 已有 player API 字幕与 yt-dlp 回退，并把 Cookie 转成临时 Netscape 文件；检查解析、生命周期、清理与凭据更新后生效方式，避免共享下载器持有旧凭据。

[供应商路由](https://github.com/JefferyHcool/BiliNote/blob/90940fde4d224d0f69ad99674f4af0a1ea52d3c4/backend/app/routers/provider.py) 已有配置与连接测试；[表模型](https://github.com/JefferyHcool/BiliNote/blob/90940fde4d224d0f69ad99674f4af0a1ea52d3c4/backend/app/db/models/providers.py) 的 API Key 是字符串字段。表模型本身不能证明写入值是否加密，实施前继续检查 DAO/service 和已有数据，再迁移到统一加密凭据存储。

[任务执行器](https://github.com/JefferyHcool/BiliNote/blob/90940fde4d224d0f69ad99674f4af0a1ea52d3c4/backend/app/services/task_serial_executor.py) 使用进程内线程池，不提供持久化队列保证。需要为提取与解读任务增加持久化状态、启动恢复和资源限流。

## 4. 第一版范围与网页流程

默认先做本地或私有部署、单用户版本，优先验收 B 站、YouTube，随后验收抖音与快手。后两者虽然已有适配代码，实际风控、短链和登录行为必须单独验证。多用户公开服务另增加账户与数据隔离。

“视频中的文字”首期定义为已有字幕或语音转写全文，保留时间戳。画面里的 PPT、代码和图表文字属于后续 OCR/视觉阶段，不能由语音转写保证覆盖。

网页复用并调整为：
1. 提取页：输入 URL，自动识别平台；选择已保存凭据或本次临时 Cookie；选择分 P、语言及是否允许 ASR 回退；不配置 LLM Key 也能提取已有字幕。
2. 结果页：视频信息、文字稿、来源、时间戳、复制与 TXT/SRT/JSON 导出；提供“专家解读”操作，选择专家及供应商/模型。
3. 历史页：查询提取和解读结果；对已有文字稿切换专家或模型，只重做解读。
4. 设置页：平台凭据管理、模型厂商/API Key/Base URL/模型名、ASR 引擎设置、专家模板编辑。

普通网页无法直接读取其他站点或用户浏览器资料中的 Cookie。首期支持手动粘贴 Cookie Header、导入 Netscape 文件；两种格式明确区分。服务器上的 cookies-from-browser 读取的是服务器环境，不能代替读取访问者浏览器。以后可复用 BiliNote 浏览器扩展做用户主动同步，或按平台增加扫码登录。

## 5. 服务架构与任务流程

React/Vite 网页 → FastAPI → SQLite 数据与凭据仓库 → 提取工作进程 / 专家解读服务。

提取工作进程复用平台适配器、yt-dlp、FFmpeg 与 ASR。模型请求由后端读取密钥后发起，专家模块只接收文字与元信息。

提取状态：排队→解析链接→获取字幕→（必要时下载音频→转写）→完成/失败/取消。解读为独立任务。任务启动时保存 transcript_id、expert_version、provider/model 和参数快照。

首期采用 SQLite 持久化任务表与一个受控工作进程；耗时处理不在 HTTP 请求内执行。使用原子领取、心跳与重启恢复，重试只针对可恢复错误，LLM 重试需避免重复计费。网页先复用轮询，必要时增加 SSE。ASR 并发默认 1，模型调用另设限流。规模增长后再考虑 Redis/Celery 与 PostgreSQL。

字幕统一为 `{start, end, text}` 段落，保存原始全文及来源（人工字幕/平台自动字幕/ASR），清洗稿单独版本保存。鉴权失败、限流、无字幕分别处理；鉴权失败不应一律当作“无字幕”继续下载。

缓存身份至少包含平台、视频 ID、分 P/cid、语言、字幕来源/版本或 ASR 引擎配置；私有视频缓存必须归属用户/授权范围。解读缓存包含文字稿哈希、专家版本、供应商/模型及生成参数。

## 6. SQLite 数据设计

尽量扩展上游表，避免重复建一套供应商/模型系统；使用可回滚迁移。

| 表或实体 | 关键字段 |
| --- | --- |
| platform_credentials | 平台、名称、格式、密文、状态、更新时间、最近验证时间 |
| providers / models（复用） | 协议类型、Base URL、模型名、密钥引用、超时及启用状态 |
| videos | 平台、video_id、part_id、规范 URL、标题、作者、时长 |
| extraction_jobs | 状态、阶段、video_id、凭据引用、引擎配置、进度与脱敏错误 |
| transcripts | 视频/分 P、语言、来源、全文、段落 JSON、内容哈希与版本 |
| experts / expert_versions | 名称、说明、提示词、输出结构、版本及内容哈希 |
| analysis_jobs / analyses | transcript_id、专家版本、模型配置快照、状态、结果、用量 |

SQLite 开启 WAL、busy_timeout、外键与短事务。音视频和缓存存文件目录，数据库保存引用；支持临时文件清理与持久数据备份。

Cookie 与 API Key 使用成熟加密库存密文，主密钥来自运行环境或部署 secret，不与数据库一起保存；网页只返回掩码/是否配置。日志、错误、导出不含凭据，临时 Cookie 文件限制权限并在 finally 中删除。Cookie 没有统一可靠有效期，按真实验证与平台响应维护状态。

URL 识别使用平台白名单，短链重定向逐跳校验并阻止内网/本地地址；Cookie 按平台域发送。自定义模型 Base URL 作为管理配置处理，不与用户视频地址共用规则。Markdown 渲染清洗，部署到公网前加入身份认证。

## 7. 专家功能与多厂商模型

第一版专家是可版本化提示词模板，不引入完整 Agent 框架。可用 Markdown + YAML 元信息管理金融、程序员、通用解读，并同步到数据库编辑与保存版本。

模板字段：id、名称、适用场景、system_prompt、输出结构、版本。金融专家侧重观点依据、数据口径、假设与风险；程序员专家侧重原理、实现步骤、技术取舍、代码问题与适用条件。输出包含核心观点、原文依据/时间戳、专家推断、待核实事项。

现有 SKILL.md 可抽取说明和提示词作为模板参考；其中脚本、工具权限、联网流程不会因传给普通 LLM 自动执行。带工具的 skill 留到第二阶段设计明确的运行器与权限。

长视频按时间和 token 预算分块，保留关键引文、数字与时间戳，再汇总解读，不能仅依赖泛化摘要。视频内容作为不可信材料，不允许其指令覆盖专家提示词。模型输出引用的时间戳要能回到真实段落。首期解读不做联网事实核查，应区分原视频陈述与模型推断。

先复用上游 OpenAI-compatible 适配接口，供应商、模型、专家相互独立。厂商名不等于协议兼容，原生 Anthropic/Gemini 等另写协议适配器或评估 LiteLLM SDK；通过适配测试后再标记支持。ASR 凭据与文本 LLM 配置分别管理。

## 8. 分阶段实施与验收

以下为单开发者粗略估算，平台风控、依赖安装和运行硬件可能显著影响时间。

| 阶段 | 工作 | 验收 | 估算 |
| --- | --- | --- | --- |
| 0 底座验证 | 固定 BiliNote 提交、运行现有服务、核对依赖和数据路径；失败时与 BiliSum 对照 | B 站与 YouTube 各一个字幕视频、一个无字幕视频；可观察失败；记录基线 | 1–2 天 |
| 1 独立提取 | 拆分提取与笔记、延迟 ASR 初始化、归一化和导出、持久化任务 | 无 LLM Key 可完成字幕提取；无字幕按配置转写；重启后可恢复/重试 | 2–3 天 |
| 2 凭据与模型 | Cookie SQLite 迁移、加密、临时输入、掩码、厂商设置联通测试 | 更新凭据对新任务生效；无跨域 Cookie；两个实际供应商调用通过 | 1–2 天 |
| 3 专家解读 | 内置三类专家、版本化、独立解读任务、长文分块与时间戳 | 同一文字稿切换两位专家和模型无需重新下载/转写；保留各版本 | 2–3 天 |
| 4 产品与部署 | 网页整合、取消/失败重试、清理与备份、Docker 和回归 | 在目标环境完成端到端测试及重启/备份恢复；日志与响应脱敏 | 1–2 天 |
| 后续 | 抖音/快手专项适配、扫码/插件同步、OCR、真正的工具 skill、多用户 | 每项单独设计与验收 | 单独评估 |

预计第一版 7–12 个开发日，不作为交付承诺。阶段 0 是底座决策门槛。

回归重点：有/无字幕、无/有效/失效 Cookie、短链与分 P、时间戳、下载拒绝、ASR 超时、模型 401/429/超时、长视频、任务重启、凭据脱敏、缓存隔离。真实视频与真实厂商接入验证不可由 mock 替代。

第一版完成标准：输入受支持 URL 和可选 Cookie 得到完整文字与来源；Cookie 可加密保存和复用；不调用 LLM 也能提取；两个专家能对同一文字独立解读；至少两个实际模型厂商调用通过；重启后保留历史、设置和可恢复任务。

## 9. 下一步

按上述默认范围先开展阶段 0，复用上游网页和接口，验证后再二次开发。B 站/YouTube 是首期验收范围，SQLite 和单用户私有部署是默认假设。当前没有执行克隆、依赖安装或应用开发。
