# PaperLearning Daily Digest

PaperLearning Vault 的独立发现与推送层。它把低价值的每日筛选从主研究会话移到 GitHub Actions，让主会话集中在原文精读、证据账本和跨论文综合。邮件包含论文关注/探索双通道，以及独立的小红书实践与趋势通道。

## 核心设计

每日候选直接从 arXiv 官方 Atom API 读取 `cs.CL,cs.LG,cs.CV,cs.AI` 指定 UTC 日期的新投稿，随后经过两级筛选。北京时间日报日与 arXiv UTC 投稿日分开记录，默认查询日为日报日前 1 天：

周五、周六没有 arXiv 新公告，因此周末日报复用最近一个官方投稿窗口，并在 JSON/HTML 中明确保存实际 `arxiv_query_date`；小红书部分仍按当天抓取。

1. **确定性预筛**：关注方向使用“概念簇”而不是单一关键词；探索方向使用当日语料稀有度、跨分类、来源排序和实证/发布信号，并执行标题多样性约束。
2. **一次批量 LLM 重排**：只处理最多 36 篇预筛候选，分别选择关注方向与探索方向。没有 API Key 时自动使用确定性结果。

预览 HTML 在同一页面保留 arXiv 关注/探索双通道和小红书实践通道，支持本地搜索和通道筛选；JavaScript 被邮件客户端移除时，所有内容仍可直接阅读。其中判断明确标记为“发现阶段摘要”，不会冒充原文精读结论。

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
PYTHONPATH=src python -m paper_digest.main --dry-run --date 2026-07-17

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
- `<Vault>/99_System/state/YYYY-MM-DD-daily-digest.json`：可选的双通道导入状态。

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

Repository variables：

| 名称 | 默认值 |
|---|---|
| `LLM_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `LLM_MODEL` | `qwen-plus` |
| `ARXIV_CONTACT_EMAIL` | 可选；arXiv User-Agent 联系邮箱 |

定时运行会正式发送；首次配置后应先通过 `Run workflow` 选择 `dry_run: true` 验证 Artifact，再手动选择 `false` 验证邮件。

每次 Action 会把 HTML、带 SHA-256 校验的 JSON 和 `latest.json` 一起提交到仓库；手动补跑旧日期不会让 `latest.json` 回退。Vault 可以把这一组公开归档当作唯一同步接口，邮件只承担提醒作用。

默认使用阿里云百炼中国内地 DashScope OpenAI 兼容接口。若 API Key 属于国际站，请将 `LLM_BASE_URL` 改为对应国际站地址。LLM 鉴权、额度或输出解析失败时，任务会自动使用确定性 shortlist 继续生成和投递日报。

## 与 Vault 的边界

- 本仓库不保存 PDF、LaTeX、私人笔记或 Vault 状态。
- 本仓库只负责发现、预筛和投递。
- 小红书内容可进入邮件、日报预览 HTML 和对应的生成状态，但不写入 Inbox 论文包或 `02_Indexes/`。
- 论文的正式结论必须回到 PaperLearning Vault，完成 `acquired → explained → indexed` 三阶段流程。

## Inspiration

邮件投递与 GitHub Actions 思路受到 [yzbcs/Daily-Digest-Assistant](https://github.com/yzbcs/Daily-Digest-Assistant) 启发。本项目采用独立实现，并保留对原项目的致谢。

小红书抓取与请求签名运行时固定使用该项目 commit `4957c3e40354816edbb2114e3aad7a3b53be47d4`。Cookie 通常约 30 天需要更新；请仅以低频个人学习用途使用，并遵守平台条款。
