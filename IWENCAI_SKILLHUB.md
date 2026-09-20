# 问财 SkillHub 接入说明

本项目的 `mainline_analysis.py` 已接入以下三个官方 SkillHub 技能：

- `news-search`：补充国内和国际财经新闻。
- `hithink-sector-selector`：补充当日板块资金流入和板块涨跌数据。
- `hithink-astock-selector`：优先获取本周、本月主力资金候选股和个股字段。

当 SkillHub 缺少配置、技能未安装或请求失败时，程序会自动退回原有的
`pywencai`、Fuyao、AkShare、GDELT 和 NewsAPI 数据链路。

## 1. 安装 CLI

在项目根目录执行：

```bash
curl -fsSL https://www.iwencai.com/skillhub/static/0.0.4/download_and_install.sh | bash -s
export PATH="$HOME/.local/bin:$PATH"
```

截至 2026-09-20，官方 `0.0.4` 外层脚本可能提示
`aime-install.sh not found`：压缩包中的真实文件名是 `iwencai-install.sh`。
遇到该问题可执行：

```bash
tmp_dir="$(mktemp -d)"
curl -fsSL https://www.iwencai.com/skillhub/static/0.0.4/iwencai-skillhub-cli.zip \
  -o "$tmp_dir/cli.zip"
unzip -q "$tmp_dir/cli.zip" -d "$tmp_dir"
bash "$tmp_dir/iwencai-skillhub-cli/iwencai-install.sh"
rm -rf "$tmp_dir"
export PATH="$HOME/.local/bin:$PATH"
```

## 2. 安装三个技能

必须在项目根目录执行。CLI 默认安装到当前目录的 `skills/`：

```bash
iwencai-skillhub-cli --dir skills install news-search
iwencai-skillhub-cli --dir skills install hithink-sector-selector
iwencai-skillhub-cli --dir skills install hithink-astock-selector
```

安装后应存在：

```text
skills/news-search/scripts/news_search.py
skills/hithink-sector-selector/scripts/cli.py
skills/hithink-astock-selector/scripts/cli.py
```

## 3. 配置项目环境

推荐将密钥写入项目本地 `.env`，不要提交到 Git：

```dotenv
IWENCAI_API_KEY=你的API_KEY
IWENCAI_BASE_URL=https://openapi.iwencai.com
IWENCAI_SKILLS_DIR=skills
IWENCAI_SKILLHUB_ENABLED=true
IWENCAI_SKILL_TIMEOUT=45
# 排查接口时临时开启，完整返回会进入 Docker 日志
IWENCAI_SKILL_LOG_RAW=false
```

官方 `setup_iwencai_env.sh` 会写入 `~/.zshrc`，并在执行时回显密钥。
项目使用 `.env` 即可，不要求执行该脚本。

## 4. 运行主线分析

模拟运行，不调用 DeepSeek：

```bash
python3 mainline_analysis.py --no-ai --output data/mainline/skillhub-demo.json
```

完整运行：

```bash
python3 mainline_analysis.py --output data/mainline/latest.json
```

临时禁用 SkillHub：

```bash
python3 mainline_analysis.py --no-skillhub
```

输出 JSON 的 `source_status.iwencai_skillhub` 和
`source_diagnostics.iwencai_skillhub` 会显示技能安装、调用和数据条数状态。

## 5. 当前分析流程

1. `news-search` 分别检索最近七天国内 A 股新闻及影响 A 股的国际新闻。
2. `hithink-sector-selector` 查询当日主力资金流入靠前的行业和概念板块。
3. `hithink-astock-selector` 查询本周、本月主力净流入、行业、市值和估值字段。
4. 将新闻与板块资金映射到农业、矿产、油气、金属、科技、芯片和存储等主题。
5. 只从输入股票池选择 `6` 或 `3` 开头个股，并按资金流、涨幅和主线匹配度排序。
6. 输出市场环境、主线板块、板块候选股、持续性和风险提示。

## 6. Docker 线上更新

三个技能目录需要与代码一起提交到 Git。服务器不需要再次安装
`iwencai-skillhub-cli`，Docker 构建时会直接复制并校验 `skills/`。

服务器 `.env` 至少需要：

```dotenv
IWENCAI_API_KEY=你的线上API_KEY
IWENCAI_BASE_URL=https://openapi.iwencai.com
IWENCAI_SKILLHUB_ENABLED=true
IWENCAI_SKILL_TIMEOUT=45
```

不要把真实 API Key 写入 `Dockerfile`、Compose 文件或 Git。

在本地提交以下文件：

```bash
git add Dockerfile docker-compose.yml .dockerignore \
  mainline_analysis.py config.py utils/iwencai_skillhub.py \
  skills/news-search skills/hithink-sector-selector \
  skills/hithink-astock-selector skills/.skills_store_lock.json \
  .env.example env_example.txt IWENCAI_SKILLHUB.md
git commit -m "feat: integrate iwencai skillhub into mainline analysis"
git push
```

在服务器项目目录更新：

```bash
git pull
docker compose config --quiet
docker compose build --pull agentsstock
docker compose up -d --force-recreate agentsstock
docker compose ps
docker compose logs --tail=200 agentsstock
```

需要查看 Skill 的完整原始数据时，将服务器 `.env` 中
`IWENCAI_SKILL_LOG_RAW=true`，重建容器后执行：

```bash
docker compose logs -f agentsstock
```

排查完成后建议恢复为 `false`，避免日志文件增长过快。

验证容器内技能和 API Key 状态，不打印密钥内容：

```bash
docker compose exec agentsstock python -c \
  "import os; from utils.iwencai_skillhub import IwencaiSkillHubClient as C; c=C(); print({'api_key': bool(os.getenv('IWENCAI_API_KEY')), 'skills': c.installation_status()})"
```

模拟执行主线分析：

```bash
docker compose exec agentsstock python mainline_analysis.py \
  --no-ai --no-history --output /app/data/mainline/skillhub-demo.json
```

查看结果和 SkillHub 诊断：

```bash
docker compose exec agentsstock python -c \
  "import json; p=json.load(open('/app/data/mainline/skillhub-demo.json')); print(p['snapshot']['source_status']); print(p['snapshot']['source_diagnostics']['iwencai_skillhub'])"
```

## 7. 单独测试某个 Skill

只测试板块 Skill，不运行主线分析：

```bash
python3 test_iwencai_skill.py sector
```

自定义板块查询：

```bash
python3 test_iwencai_skill.py sector \
  --query "今日主力资金净流入前10的概念板块" --limit 10
```

测试新闻和个股 Skill：

```bash
python3 test_iwencai_skill.py news
python3 test_iwencai_skill.py stock
```

在 Docker 服务器中测试板块 Skill：

```bash
docker compose exec agentsstock python test_iwencai_skill.py sector
```

保存完整原始响应到持久化目录：

```bash
docker compose exec agentsstock python test_iwencai_skill.py sector \
  --raw --output /app/data/iwencai-sector-test.json
```

退出码含义：`0` 成功且有数据，`2` 技能未安装，`3` 缺少 API Key，
`4` 请求或鉴权失败，`5` 请求成功但结果为空。
