# PaperLearning Daily Digest

PaperLearning Vault 的独立发现与推送层。它把低价值的每日筛选从主研究会话移到 GitHub Actions，让主会话集中在原文精读、证据账本和跨论文综合。邮件包含论文关注/探索、小红书实践趋势、B站深度视频、知乎经验知识和 X 前沿动态五类内容区域。

## 核心设计

每日候选直接从 arXiv 官方 Atom API 读取 `cs.CL,cs.LG,cs.CV,cs.AI` 指定 UTC 日期的新投稿，随后经过两级筛选。北京时间日报日与 arXiv UTC 投稿日分开记录，默认查询日为日报日前 1 天：

周五、周六没有 arXiv 新公告，因此周末日报复用最近一个官方投稿窗口，并在 JSON/HTML 中明确保存实际 `arxiv_query_date`；小红书、B站、知乎和 X 部分仍按当天抓取。

1. **确定性预筛**：关注方向使用“概念簇”而不是单一关键词；探索方向使用当日语料稀有度、跨分类、来源排序和实证/发布信号，并执行标题多样性约束。
2. **一次批量 LLM 重排**：只处理最多 36 篇预筛候选，分别选择关注方向与探索方向。没有 API Key 时自动使用确定性结果。

预览 HTML 在同一页面保留 arXiv 关注/探索、小红书实践、B站深度内容、知乎经验知识和 X 前沿动态，支持本地搜索和通道筛选；JavaScript 被邮件客户端移除时，所有内容仍可直接阅读。其中判断明确标记为“发现阶段摘要”，不会冒充原文精读、完整视频观看或对个人经验的普遍化结论。

### B站内容漏斗

B站通道采用“硬过滤 → 百分制评分 → 多样性重排”的选择逻辑。候选仅保留近期的深度访谈、产品实测、技术演讲、会议录播和论文解读；招生导流、纯搬运、过短泛资讯以及超过配置时间窗口的内容会先被排除。评分由主题相关性 30%、信息密度 25%、可信度 15%、实践价值 15%、新鲜度 10% 和互动质量 5% 构成，默认只推送 65 分以上内容。播放、点赞、收藏和弹幕是弱信号，不会单独决定入选。

为控制请求频率，30 条搜索候选预筛后只为前 12 条补充详情指标。最终每天最多 5 条，同一 UP 主最多 1 条、同一内容类型最多 2 条；不足门槛时宁可少推送。所有总结仍只依据标题、简介和公开元数据，不代表已经完整观看视频。

### 知乎内容漏斗

知乎通道面向三类核心内容：大厂面试经验、科研方向讨论和知识机制解读，同时允许少量高质量成长复盘。候选经过“Cookie 搜索 → 硬过滤 → 百分制评分 → LLM 重排 → 多样性约束”：课程咨询导流、过短文本、过时经验和纯情绪输出会被降低或排除；默认只推送 65 分以上、最多 5 条内容。

评分由主题相关性 30%、第一手经验或论据质量 25%、内容深度 20%、可信度 10%、新鲜度 10% 和互动质量 5% 构成。赞同与评论仅是弱信号；同一作者最多 1 条、同一问题最多 1 个回答、同一内容类型最多 2 条。总结会明确保留“个人经验不等于普遍事实”的边界。

### X 前沿信息漏斗

X 通道同时覆盖“定点信源”和“主题发现”：前者低频检索 OpenAI、Anthropic、Google DeepMind 等 AI 公司/研究机构官方账号及可信研究者，后者检索模型发布、AI Agent、论文、Benchmark、数据集和开源项目。官方账号只获得更高可信度权重，不会自动入选；每条内容仍必须提供明确的信息增量。

候选依次经过 Cookie 搜索、原创性/时效/垃圾内容硬过滤、百分制评分、LLM 中文摘要与多样性重排。评分考虑来源可信度 25%、主题相关性 25%、信息增量 20%、新鲜度 15%、互动质量 10% 和原创性 5%。默认只看最近 7 天、每天最多 6 条，同一作者最多 2 条、同一内容类型最多 2 条。点赞、转发、回复和浏览量只作为弱信号；总结会区分官方声明、研究者个人观点与论文结论。

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
PYTHONPATH=src python -m paper_digest.main --dry-run --date 2026-07-17

# 不重新请求 arXiv/Qwen/各内容平台，校验并重渲染已归档日报
PYTHONPATH=src python -m paper_digest.main --dry-run --reuse-archive --date 2026-07-17

# 同时将结构化状态和预览 HTML 写入本地 Vault
PYTHONPATH=src python -m paper_digest.main --dry-run --date 2026-07-17 \
  --vault ../PaperLearning-Vault
```

输出：

- `preview.html`：邮件预览；
- `out/email.html`：采用单列 table 与全内联样式的 Gmail 兼容正文；
- `out/shortlist.json`：结构化双通道 shortlist；
- `out/delivery.json`：本次投递状态；
- `docs/daily/YYYY/MM/YYYY-MM-DD.html`：每日归档。
- `docs/data/YYYY/MM/YYYY-MM-DD.json`：供本地 Vault 同步的结构化日报（含内容哈希）。
- `docs/data/latest.json`：指向最新 JSON 与 HTML 的稳定同步入口。
- `<Vault>/03_Daily_Digests/YYYY-MM-DD.html`：可选的 Obsidian 本地预览。
- `<Vault>/99_System/state/YYYY-MM-DD-daily-digest.json`：可选的多通道导入状态。

arXiv 公开 Atom API 不需要 Cookie 或登录。程序遵守单连接且相邻分页请求至少间隔 3 秒的限制；如果 Atom API 发生临时 TLS/服务错误，当日任务自动降级到 arXiv 官方分类 RSS，不会回退到第三方论文源。如果希望在 User-Agent 中标识联系人，可设置 `ARXIV_CONTACT_EMAIL`。

## GitHub Actions 配置

工作流每天北京时间 13:00 运行，也支持手动指定日期和 dry-run。

Repository secrets：

| 名称 | 用途 |
|---|---|
| `LLM_API_KEY` | 可选；缺失时使用确定性筛选 |
| `EMAIL_USER` | 发件邮箱 |
| `EMAIL_PASS` | SMTP 授权码 |
| `EMAIL_TO` | 收件邮箱，多个地址用逗号分隔 |
| `XHS_COOKIE` | 可选；小红书网页版完整 Cookie，缺失或过期时跳过小红书 |
| `BILIBILI_COOKIE` | 必需（B站通道）；B站网页版完整 Cookie，缺失时跳过 B站 |
| `ZHIHU_COOKIE` | 必需（知乎通道）；知乎网页版完整 Cookie，必须包含 `d_c0`，缺失时跳过知乎 |
| `X_COOKIE` | 必需（X 通道）；登录 `x.com` 后复制完整 Cookie，必须包含 `auth_token` 与 `ct0` |

Repository variables：

| 名称 | 默认值 |
|---|---|
| `LLM_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `LLM_MODEL` | `qwen-plus` |
| `ARXIV_CONTACT_EMAIL` | 可选；arXiv User-Agent 联系邮箱 |

定时运行会正式发送；首次配置后应先通过 `Run workflow` 选择 `dry_run: true` 验证 Artifact，再手动选择 `false` 验证邮件。

获取知乎 Cookie 时，请在浏览器登录 `www.zhihu.com`，从开发者工具 Network 中任意发往 `www.zhihu.com` 的请求复制完整 `Cookie` 请求头，并将其保存为 GitHub Actions Repository secret `ZHIHU_COOKIE`。Cookie 必须包含 `d_c0`；不要把 Cookie 写入 `config.yml`、日志或提交记录。状态 `invalid-cookie-missing-d_c0` 表示内容不完整，`cookie-expired-or-risk-control` 表示登录态过期或请求被风控。

获取 X Cookie 时，请在浏览器登录 `x.com`，从开发者工具 Network 中任意发往 `x.com/i/api/` 的请求复制完整 `Cookie` 请求头，并保存为 Repository secret `X_COOKIE`。Cookie 必须同时包含 `auth_token` 和 `ct0`；不要粘贴到 Issue、日志、配置文件或提交记录。`invalid-cookie-missing-*` 表示 Cookie 不完整，`cookie-expired-or-risk-control` 表示会话已过期或被拒绝。建议使用专门的只读学习账号，并控制为每日一次。

每次 Action 会把 HTML、带 SHA-256 校验的 JSON 和 `latest.json` 一起提交到仓库；手动补跑旧日期不会让 `latest.json` 回退。Vault 可以把这一组公开归档当作唯一同步接口，邮件只承担提醒作用。

默认使用阿里云百炼中国内地 DashScope OpenAI 兼容接口。若 API Key 属于国际站，请将 `LLM_BASE_URL` 改为对应国际站地址。LLM 鉴权、额度或输出解析失败时，任务会自动使用确定性 shortlist 继续生成和投递日报。

## 与 Vault 的边界

- 本仓库不保存 PDF、LaTeX、私人笔记或 Vault 状态。
- 本仓库只负责发现、预筛和投递。
- 小红书、B站、知乎与 X 内容可进入邮件、日报预览 HTML 和对应的生成状态，但不写入 Inbox 论文包或 `02_Indexes/`。
- 论文的正式结论必须回到 PaperLearning Vault，完成 `acquired → explained → indexed` 三阶段流程。

## Inspiration

邮件投递与 GitHub Actions 思路受到 [yzbcs/Daily-Digest-Assistant](https://github.com/yzbcs/Daily-Digest-Assistant) 启发。本项目采用独立实现，并保留对原项目的致谢。

小红书抓取与请求签名运行时固定使用该项目 commit `4957c3e40354816edbb2114e3aad7a3b53be47d4`。Cookie 通常约 30 天需要更新；请仅以低频个人学习用途使用，并遵守平台条款。

B站通道的场景设计参考 [tooandy/bili-auto](https://github.com/tooandy/bili-auto)，本项目采用独立的 Cookie 会话只读搜索实现；缺失 Cookie 时状态为 `missing-cookie`，不会匿名请求。程序不执行关注、点赞、投币、评论或下载视频。请保持低频个人学习用途并遵守平台条款。

知乎请求签名运行时固定使用 [NanmiCoder/MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) commit `0625e01a6bc717a3fc9c96d3dac7fb8957043838` 中的 `libs/zhihu.js`，仅在 GitHub Actions 运行时检出，不复制进本仓库。知乎通道只执行低频只读搜索，不点赞、不评论、不关注，也不抓取个人主页；请仅用于个人学习并遵守平台条款及上游非商业学习许可证。

X 通道使用 [d60/twikit](https://github.com/d60/twikit) 解析 Cookie 并执行网页搜索，并固定到 [SearchTimeline 兼容修复 PR #419](https://github.com/d60/twikit/pull/419) 的精确 commit；上游发布包含等价修复后应恢复使用正式版本。程序只调用搜索能力，不点赞、不转发、不回复、不关注、不发帖，也不抓取私信。网页内部接口可能随 X 改版而失效，且自动化访问存在账号风控风险；请仅以低频个人学习用途使用并遵守平台条款。若需要长期稳定或商业使用，应改用 X 官方 API。
