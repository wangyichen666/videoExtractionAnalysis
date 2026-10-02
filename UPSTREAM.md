# 上游来源

基于 JefferyHcool/BiliNote（MIT）二次开发，保留原 LICENSE 和完整上游应用。

- 仓库：https://github.com/JefferyHcool/BiliNote
- 引入日期：2026-10-01
- 基线提交：90940fde4d224d0f69ad99674f4af0a1ea52d3c4
- 新入口：backend/analysis_main.py、BillNote_frontend/analysis.html
- 复用：BiliNote B站字幕模块与相关工具；React/Vite/Markdown 依赖；yt-dlp 平台提取与 faster-whisper 转写。
- 原版入口 backend/main.py 保留；app/__init__.py 改为延迟加载路由，以免独立入口加载无关依赖。

- B站字幕模块增加显式 Cookie 参数、严格访问错误模式、CDN 域校验与 Cookie 隔离；原版调用保持默认模式。
- 新界面通过 analysis-markdown 别名使用 React 19 兼容版本，保留原版 react-markdown 依赖。

## 评论采集参考

- 仓库：https://github.com/niudungh/bilibili-comment-skill
- 核对日期：2026-10-01；提交034978ae596ce8d28689149262e75a0acddfc36e。
- README与SKILL声明MIT，作者Agents365-ai，仓库未附独立LICENSE文件。解析模块flatten.py原样保留于backend/analysis_app/vendor/bbc，许可与来源见同目录NOTICE.md。
- 参考主评论游标/置顶合并/楼中楼分页协议；请求、双上限、SQLite检查点、恢复与页面为本项目适配实现。没有引入CLI全量依赖、自动浏览器凭据读取、用户批量扫描或原始API档案。
