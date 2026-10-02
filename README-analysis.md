# 视频文字与专家解读工作台

基于 BiliNote 的本地单用户网页：输入视频 URL 与可选 Cookie，优先获取字幕，无字幕可使用本地 ASR；加密保存平台 Cookie 和模型 API Key；对同一文字稿选择不同专家与模型解读。

## 启动

Python 3.12、Node.js 20+、pnpm。使用精简入口，无需安装原版 requirements.txt 的全部依赖。

```bash
uv venv --python python3.12 .venv
uv pip install --python .venv/bin/python -r backend/requirements-analysis.txt
cd BillNote_frontend
pnpm install
pnpm build:analysis
cd ../backend
../.venv/bin/uvicorn analysis_main:app --host 127.0.0.1 --port 8483 --no-access-log
```

打开 http://127.0.0.1:8483 。开发模式另运行 `pnpm dev:analysis`，访问 http://127.0.0.1:3015/analysis.html 。后端必须单 worker 运行，数据目录通过文件锁防止重复启动；当前面向 macOS/Linux。

无字幕视频还需要可选依赖（包含 imageio-ffmpeg 提供的 FFmpeg 二进制，无需系统安装；已有系统 FFmpeg 时优先使用）：

```bash
uv pip install --python .venv/bin/python -r backend/requirements-analysis-asr.txt
```

初次本地 ASR 会下载 Whisper 模型，默认 base/CPU/int8。已有字幕不依赖 FFmpeg 或 ASR 模型，也不需要 LLM Key。

## 使用

1. 设置中保存平台 Cookie（Cookie Header 或 Netscape 文件内容）。也可以只在提取表单填本次临时 Cookie。
2. 提取页面输入 HTTPS 视频链接；B站分 P 保留 `?p=N`；按需开启无字幕转写。
3. 历史任务中查看状态，完成后打开文字稿，可导出 TXT/SRT/JSON。
4. 设置中配置模型厂商、HTTPS Base URL、模型名及 API Key。支持 OpenAI-compatible `/chat/completions`，不宣称原生 Anthropic/Gemini 协议兼容。
5. 对文字稿选择专家和模型进行解读；可创建或编辑专家提示词。更换专家不重复提取视频。

## 数据与部署

默认数据目录 `backend/data/analysis/`，可通过 `ANALYSIS_DATA_DIR` 指定。SQLite 保存任务、文字稿、解读与加密凭据。任务中的临时 Cookie 加密暂存，任务结束后清除。密钥优先读取 `ANALYSIS_SECRET_KEY`（Fernet 格式）；未配置时首次生成权限 0600 的 `secret.key`。备份数据库与密钥，但将密钥和数据库分开保护；丢失密钥无法解密凭据。

此入口仅用于本地单用户部署，默认绑定 127.0.0.1；当前没有账户登录和多用户隔离，不应直接暴露到公网。耗时任务由单工作线程串行处理，重启后未完成任务重新排队，模型请求被中断时重试可能产生重复费用。支持取消排队任务和手动重试失败任务；临时 Cookie 已清除的失败任务需重新输入。当前尚无运行中任务强制取消和自动重试。

B站/YouTube 是主要目标；抖音与快手使用 yt-dlp 通用适配，平台风控和登录可能导致失败。文字指字幕/语音，暂未实现画面 OCR。专家解读不联网核查事实。未自动读取访问者浏览器 Cookie，未自动迁移原版 JSON 凭据和供应商配置。

## 检查

```bash
.venv/bin/python -m pytest backend/analysis_tests -q
cd BillNote_frontend
pnpm build:analysis
```

真实登录视频与真实模型的端到端验证需要用户自有 Cookie/API Key；不使用测试结果替代真实站点验证。

## Docker（可选）

```bash
docker compose -f docker-compose.analysis.yml up --build -d
```

同样访问 http://127.0.0.1:8483 。默认仅安装字幕提取和 LLM 依赖；需要无字幕转写时把 compose 的 `INSTALL_ASR` 改成 `"true"` 后重新构建。数据库和密钥放在 `analysis-data` 命名卷。Docker 构建文件已提供，本机尚未验证 Docker 构建。

### 专家解读与整理文章

程序员默认模板 v3 使用六个章节：内容总结、观点与论证、专业名词解释、工程实践启示、分歧与待验证问题、转写疑点与信息边界。同时输出由原稿改写的连贯文章、原文定位和文字校准记录。金融、通用与自定义专家复用共同引擎与版本化输出契约，保留各自视角。自定义提示词不覆盖，旧报告仍可阅读；实现说明见 `docs/expert-development.md`。

长稿逐片整理证据与文章，再按章节归纳。非法正文引用、空结果和未恢复的截断会明确失败；不匹配原词的校准记录剔除，并在页面提示。每个通过校验的分片和章节持久化，失败重试复用成功阶段。新的“重新生成”从头处理；长稿涉及多次计费调用。校验只能保证结构和引用存在，不能证明语义真实性，重要专名仍需回听。

网页按所选专家显示结果，多个版本可选历史解读；解读/文章各自阅读与下载。时间戳可展开原稿并定位，下载 Markdown 中引用转换为公开视频时间链接。供应商无需接触平台 Cookie。

### DeepSeek 配置与实测

Base URL 使用 `https://api.deepseek.com`；本次实际模型列表包含 `deepseek-flash` 和 `deepseek-v4-pro`，选择前者测试。DeepSeek 专用请求关闭默认思考模式，结构整理启用 JSON object；其它兼容厂商不附带专用参数。API Key 仅保存在加密数据库，不写入源码。

页面应用 design-visual-frontend skill 的工作台与长文阅读规则：精简顶部、可折叠提取栏、专家/文章切换、固定目录及宽屏校准侧栏。设计决策与五个尺寸验收见 `docs/design-decision.md`。


指定 B站访谈的真实 DeepSeek 运行已完成：六章解读、12节/100自然段整理文章（14725汉字），可在网页选择最新“deepseek-flash · 模板 v3 · 第5份”。导出示例在 `artifacts/deepseek-programmer-analysis.md` 与 `artifacts/deepseek-edited-article.md`，实测统计在 `artifacts/deepseek-validation/result-stats.json`。43项后端测试、类型检查和生产构建通过；390/768/1440/1920/2560五个尺寸与核心阅读交互验证通过。其它供应商仅协议模拟覆盖，未真实联网测试；专名与事实仍需要回听核对。

### 财经专家

选择“财经专家”会按finance-v2输出：核心主题、账户与市场表现、标的观点、政策与行业逻辑、风险与历史教训、关键结论，同时生成独立整理文章。每家公司分组列观点与依据，时间引用可定位原稿；来源链接与生成时间可见。宽屏展示公司名称核对侧栏，窄屏折叠。新链接使用同一模板，结果按专家独立保存；旧finance-v1与自定义模板保留。

短视频整篇编排，长视频分片整理后跨类别归纳。有限公司身份字典提供官方名称/代码来源，发音匹配标为疑似，不把视频财务或政策信息当已核实。实现见 `docs/finance-development.md`。

示例BV1NWaZ6REvt真实DeepSeek生成完成：288段原稿，六章解读约3280汉字、整理文章约2357汉字；文件为 `artifacts/finance-example-analysis.md`、`artifacts/finance-example-article.md`。当前53项后端测试及前端检查/构建通过，五尺寸和核心交互完成验证。数字、公司指代及推断仍需回听，段号校验不代表事实核验。

### B站视频评论

导航“视频评论”支持独立输入视频链接或BV号；已有文字稿标题旁的“视频评论”入口会预填当前链接。可选择已保存的B站Cookie、热门/最新采集顺序、主评论和总评论上限，以及是否包含楼中楼。默认100条主评论、1000条总评论，单次最多1000条主评论和5000条总评论。

采集为独立持久任务，页面显示进度，离开页面后继续；失败保留已采集记录，可在评论页或任务历史重试。主评论、楼中楼与置顶去重保存，评论支持关键词/作者搜索、点赞/时间排序、仅UP主评论筛选、线程展开、分页及JSON/JSONL/Markdown下载。范围和平台声明数量会明确显示，达到上限不标为完整。新采集创建独立快照。

复用 [bilibili-comment-skill](https://github.com/niudungh/bilibili-comment-skill) 的解析模块并参考其接口分页；适配到现有SQLite、加密凭据与工作线程，不需要额外Python依赖。来源见 `UPSTREAM.md`，实现/验收见 `docs/comments-development.md`。Cookie只发送给B站固定API，评论不自动进入专家的LLM输入。

真实示例BV1NWaZ6REvt已从页面保存307条（87条主评论、220条楼中楼）；latest限量采集也通过。当前62项后端测试、前端检查/构建及五尺寸界面验证通过。平台风控/权限、删除/隐藏评论和采集上限会影响范围；真实风控恢复、手机原生浏览器仍未实测。


### 评论观点分析

在“视频评论”中选择已保存资料，设置最少/最多字数（最多留空表示不限）。字数忽略空白，标点和表情计入；搜索内容/作者及仅UP主评论条件共同生效。页面显示准确匹配条数，主评论和每条楼中楼分别计数。

选择已配置的模型，点击“分析筛选后的 N 条评论”。输出包含整体总结、主题观点、作者结论/表达结果、理由/论据、具体举例、分歧和信息边界；同时保留每条评论的解析。没有具体举例会明确提示，引用编号可以打开生成时保存的原评论。模型分析需要使用用户已配置的API，会产生调用费用。

报告保留生成时筛选条件与评论快照，之后修改筛选不会改变旧报告。结果支持历史切换和MD/JSON下载；失败可以重试并复用已完成片段。单次最多500条、10万字符，超量需收紧筛选，不自动截断。评论分析独立于视频专家解读，两者不会混用输入。


真实DeepSeek示例：307条快照设最少50字，25条送入分析，获得36个观点、28个举例条目和17个主题；独立审校移除1处不同对象的伪分歧。最新报告可从“历史任务”直接打开，也可在评论页选择历史结果。77项后端测试及前端检查/构建通过，五尺寸与下载/引用/分页验证完成，详情见`docs/comments-development.md`与`artifacts/comment-analysis-validation.json`。模型语义和评论自述事实仍需结合原评论判断。
