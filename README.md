# Entertainment Law Daily

每日英文娱乐法学习工具，专为中国娱乐法律师设计。

**功能：** 每天自动抓取真实娱乐法新闻/案例 → 生成结构化学习卡片 → 部署到 GitHub Pages 即开即用。

## 快速开始（5 分钟部署）

### 1. Fork / Clone 本仓库

```bash
git clone https://github.com/YOUR_USERNAME/entertainment-law-daily.git
cd entertainment-law-daily
```

### 2. 配置 GitHub Secrets

进入仓库 **Settings → Secrets and variables → Actions**，添加：

| Secret 名称 | 值 |
|---|---|
| `ANTHROPIC_API_KEY` | 你的 Anthropic API Key |

### 3. 开启 GitHub Pages

进入 **Settings → Pages**：
- Source: `Deploy from a branch`
- Branch: `main`，文件夹: `/ (root)`

保存后，访问 `https://YOUR_USERNAME.github.io/entertainment-law-daily/`

### 4. 手动触发第一次生成

进入 **Actions → Generate Daily Content → Run workflow**

等待约 1 分钟后刷新页面即可看到当天内容。

---

## 自动运行时间

每天 **北京时间早上 7:00**（UTC 23:00）自动运行并提交。

---

## 本地开发

```bash
# 安装依赖
pip install -r requirements.txt

# 运行生成脚本（需要 API Key）
export ANTHROPIC_API_KEY=sk-ant-...
python scripts/generate.py

# 预览前端（需要 Python 3）
python -m http.server 8000
# 打开 http://localhost:8000
```

---

## 目录结构

```
├── .github/workflows/generate.yml   # 定时任务
├── scripts/generate.py              # 内容生成脚本
├── data/
│   ├── latest.json                  # 最新一期（前端读取）
│   └── archive/YYYY-MM-DD.json      # 历史归档
├── index.html                       # 单文件前端
└── requirements.txt
```

---

## 前端功能

- **英文精读**：排版精美，支持 Web Speech API TTS 朗读（语速 0.85）
- **词汇学习**：点击展开例句
- **句式分析**：模板 + 原文例句 + 中文说明
- **法律解读**：中文分析 + 相关法规标签
- **思考题**：每期配一道讨论题

---

*Powered by Claude AI (claude-sonnet-4-20250514) with web search*
