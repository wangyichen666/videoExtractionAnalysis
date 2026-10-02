# 调研发现

## 用户需求
网页输入视频 URL 与 Cookie；SQLite 保存凭据和任务；输出文字；可选择金融、程序员等专家；网页配置多模型厂商 API Key。

## 前序会话
已读取会话 01a0f566-b3f8-7ae0-8aa2-3e5527f8ddfe。候选包括 bili-transcript、video-summary-tool、BiliBiliDecoder、bilibili-subtitle-fetch。此前结论仅来自项目说明，需重新核验。

## 核验结果
- 当前目录为空，尚未初始化 Git。
- BiliNote 主分支 master，核验提交 90940fde4d224d0f69ad99674f4af0a1ea52d3c4，MIT；GitHub API 显示最近推送 2026-09-01，未归档。
- CookieConfigManager 使用 config/downloader.json，按平台保存明文 Cookie；需改为 SQLite 加密存储。
- provider 路由已有供应商新增、修改、查询与连接测试接口，查询调用 safe 方法；数据库加密情况仍需核对。
- requirements 已含 FastAPI、SQLAlchemy、yt-dlp、faster-whisper 等；依赖范围较大。
- urllib 遇到本机证书链错误，改用 curl 成功，未关闭证书验证。
- note.py 流程虽已字幕优先，但仍先初始化 GPT，构造器初始化 ASR，需独立提取入口与延迟初始化。
- 下载器持有初始化时 Cookie，需检查共享实例和更新生效；临时 Netscape 文件需控制权限与清理。
- providers 表 api_key 为 String；是否已加密需继续检查写入服务，不能仅由字段类型判定。
- 当前任务执行器为进程内线程池，首期计划补 SQLite 持久任务与重启恢复。
- BiliSum、video-summary-tool、bili-transcript 为 MIT；yt-dlp 源码主要为 Unlicense；faster-whisper 为 MIT；LiteLLM API license=Other，需目录级核验。


## 开发验证
- 用户提供视频 BV1xQKp6bE4U，B站 view API 无 Cookie 返回 HTTP 412 / text/html；不是“视频没有字幕”的证明。
- 精简入口复用 BilibiliSubtitleFetcher，增加显式 Cookie 注入、可选严格鉴权检查及 CDN Cookie 隔离；原完整入口默认行为保留。
- 已安装 Python 3.12 精简依赖、faster-whisper 与 imageio-ffmpeg；健康检查均就绪，未下载/验证 Whisper 模型推理。
- 13 项测试、前端类型检查、生产构建通过；真实厂商测试需要用户自己的 Key。
- 补充实际验收：SESSDATA 有效时 nav 返回 HTTP 200/code 0/isLogin=true；原 view 接口仍 412。wbi/view 可正常取到元信息，因此实现仅在原接口 412 时回退备用接口。
- 已成功获取用户指定视频 2213 段 AI 字幕。直接字幕路径保留元信息，不再要求 yt-dlp 元信息请求成功。

程序员专家升级：现有提示词只有一句，长文本层层合并导致术语/分歧压缩丢失。当前稿 2213 段、约 76 分钟；需分段抽取带段号证据，分别生成七章。字幕中模型与人名误识别严重，无说话人标记，不能可靠逐句归人。现有 providers 为空，必须将会话参考分析与网页模型生成区分。

成文与专业解读必须分离：文章仅保留原视频论证/例子/推测语气，专业补充只在解读中。每片原稿保留成文片段，目录编排不能再把文章压成摘要。校准记录校验原词和段号，但语义准确性仍依赖模型和人工复核。多专家共用输出契约，身份通过expert_id及快照识别，避免不同模式结果混杂；历史旧结构不覆盖。
