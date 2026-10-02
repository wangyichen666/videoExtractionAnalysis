# videoExtractionAnalysis

视频文字提取与专家解读工作台。

基于 [BiliNote](https://github.com/JefferyHcool/BiliNote) 的本地网页第一版，复用其 B站字幕模块、前端技术栈及 yt-dlp/faster-whisper 链路。

- 输入视频链接与可选 Cookie，字幕优先、无字幕可选本地 ASR。
- SQLite 加密保存 Cookie 与模型 API Key。
- 通用、金融、程序员专家，可编辑提示词并保存版本。
- 对同一文字稿选择不同模型与专家解读，不重复提取。
- TXT/SRT/JSON 导出，历史任务、重启恢复、手动重试与排队取消。
- 程序员、财经专家提供专属解读章节、整理文章、上下文校准与原文引用。
- B站评论采集与楼中楼阅读，支持字数/关键词筛选、模型观点分析和 Markdown/JSON 导出。

请按 [启动与使用说明](README-analysis.md) 运行，新入口是 `backend/analysis_main.py`。

原版完整应用仍保留，见 [上游 README](README.upstream.md) 和 [来源记录](UPSTREAM.md)。

当前为本地单用户版本，仅绑定回环地址；主要验证目标是 B站/YouTube，抖音/快手适配仍需实测。模型接口采用 OpenAI-compatible 协议；未实现画面 OCR、工具型 skill 或多用户账户。

最近验收（2026-10-01）：77 项后端测试、前端类型检查、生产构建通过，五种屏幕尺寸验证完成。B站字幕提取、程序员/财经专家与评论分析已通过真实 DeepSeek 调用验证。评论示例共307条，按至少50字筛选25条，提炼36个观点和28个举例条目。开发记录见 [评论功能文档](docs/comments-development.md) 与 [专家功能文档](docs/expert-development.md)。

Cookie、API Key、SQLite 数据库、运行密钥、验收截图和视频/模型稿件均保存在本机，不随代码提交。文档中提到的 `artifacts/` 为本地验收目录。

保留上游 MIT 许可证，见 LICENSE。
