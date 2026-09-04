# 交付说明 · V0 已完成 · 名字已定为 `agentveto`

耀哥，名字我替你定了，代码也改完重跑过了（16 个测试全过）。

但这次查名的过程本身就是一份情报，我得先说——**它改变了路线图的顺序**。

---

## 一、名字：`agentveto`（PyPI 空、GitHub 空、无品牌冲突）

### 为什么不是原来那几个

我连查了三轮，撞了三个。这个过程比结果更有信息量：

| 候选 | 结果 | 撞了什么 |
|---|---|---|
| `agentledger` | ❌ 弃 | PyPI 空，但 `substrateagnostic/agentledger` 已把**概念**占了（详见下节）。npm 上另有 3 个同名/近名包（Solana 存证、Salesforce 审计、MCP 存证） |
| `agentredline` | ❌ 弃 | PyPI/GitHub 都空，但 `rore/agent-redline` 在做"AI agent 红区治理"，连 red zone / checkpoint / agent-policy.yaml 的词汇体系都一模一样 |
| `agentgate` | ❌ 弃 | PyPI 被一个多智能体框架占了（v0.4.0） |
| `tripwire` | ❌ 弃 | PyPI 空，但 Tripwire Inc.（Fortra 旗下）就是做**文件完整性监控/篡改检测**的——跟我们要做的"防篡改证据链"是同一片业务，商标风险实打实；且 SEO 会被完全淹没 |
| `underwrite` | ❌ 弃 | PyPI 空，但撞保险承保业（Guidewire UnderwritingCenter 等），搜索结果全是保险 |

另外，下面这些通用词在 PyPI **全都被占了**：

```
agentnotary  agentwitness  witnesskit  autopsy    agentreplay
verdict      agentverdict  redline     airlock    bulkhead
hardstop     circuitbreaker  gatekeep   deadman    killswitch
holdpoint    veto          chokepoint  wiretap    rewind
agentcourt   agentjury     agentseal   agentrail  agentbrake
```

**这张表说明一件事：Agent 治理赛道的命名已经很挤了。** 记录类（blackbox/vcr/trace）、账本类（ledger）、红线类（redline）、门闸类（gate/airlock/bulkhead/circuitbreaker）全被占满。半年内冒出这么多同类项目，痛点绝对是真的；但也意味着**心智争夺已经开始，晚半年连名字都难起**。

### 为什么是 `agentveto`

- **PyPI 空、GitHub 组织空、域名可得**
- **语义直击唯一没人占的位置**：其他所有玩家都在回答"我的 agent 做了什么"（记录），没有一个在做"我的 agent 不许做什么"（拦截）。veto = 否决权，是运行时拦截，不是事后复盘
- **法律/合规语域**，跟最终掏钱的人（合规总监）同频，不像 `leash`、`autopsy` 这类俏皮名进不了企业的门
- **一眼知道干嘛的**，不需要解释

Tagline：**Replay it. Prove it. Veto it.**
CLI 描述：**Runtime control for AI agents.**

---

## 二、更重要的坏消息：`substrateagnostic/agentledger` 把 V1 也做了一半

上一轮我说"竞品全卡在 V0，V1 是我们的护城河"。**这个判断要修正。**

这家（TypeScript / npm）做的东西，比我以为的完整得多：

- 定位原文：**"OpenTelemetry for AI accountability"**
- Hash chain + Merkle tree + Ed25519 签名，三层防篡改
- 原生映射 **FINRA 4511/3110、EU AI Act Article 12、HIPAA、SOC 2、GDPR** 五个合规框架，还带各自的保留期
- `agentledger-openai` / `-anthropic` / `-langchain` 三个集成包
- CLI 有 `verify` / `export` / `replay` / `summary`

也就是说，**"不可篡改证据链"这个我们排在 V1 的卖点，已经有人在做了。**

### 但它有两个致命缺口，正好是我们的活路

1. **它是 TypeScript / npm 生态。Python 生态里这块还是空的。** 做 Agent 的人一大半在 Python。
2. **它没有运行时拦截。** 它的 `logApproval()` 是"记录一次人工审批"，不是"在动作执行前自动拦下来"。它全程只记录，不决策。

### 路线图顺序因此要改

原来的 V0 → V1(证据链) → V1(闸门)，改成：

| 顺序 | 能力 | 竞争状态 | 为什么这个顺序 |
|---|---|---|---|
| 1 | **Replay** 确定性回放 | 红海（agentblackbox、agent-vcr 都有） | 只能当钩子，不是卖点。但它是入口——没有它没人装你 |
| 2 | **Veto** 运行时策略闸门 | **完全无人占** | 唯一能拉开身位的东西。提前到第 3 个月，而不是排在证据链后面 |
| 3 | **Prove** 防篡改证据链 | TS 那家占了心智，但**不覆盖 Python** | 合规刚需，是收钱的那一项；靠 Python 生态 + 私有化部署吃下来 |

**一句话：拦截比留证更稀缺，所以拦截先做。** 留证是"出事之后说得清"，拦截是"出事之前不让干"——后者的付费意愿更高，而且没人抢。

---

## 三、我做了什么

`agentveto/` —— 零必需依赖，纯标准库就能跑。

```
agentveto/
  agentveto/
    __init__.py     公开 API：init / @trace / report / demo / serve
    tracer.py       run / span / 装饰器，contextvars 支持嵌套与并发
    store.py        SQLite 存储，WAL，按线程独立连接
    patch.py        openai + anthropic 自动插桩，record/replay
    pricing.py      价格表，未知模型不瞎猜
    report.py       单文件 HTML 报告生成器
    demo.py         离线示例（无需 API key）
    serve.py        本地查看器（可选依赖）
    cli.py          agentveto demo / list / report / serve
  tests/test_core.py    16 个测试，全部通过
  examples/            demo.py + basic.py
  README.md            面向海外开发者的英文 README（已按新定位重写）
  pyproject.toml       零必需依赖
```

### 验证结果（全部实跑过）

```
16 passed in 0.28s
```

- **报告自包含**：20 KB 单文件，零外部引用，离线可渲染，六个月后还能打开
- **openai 自动插桩**：即使网络调用失败，model / prompt / 错误 / provider 全部记录在案
- **毒化输入不破图**：把 `</script><script>alert(1)</script>` 塞进 prompt，报告照样正常渲染
- **成本归因**：demo 里 11 步共 $0.01489，逐步可查；未知模型标 unknown 而不是编一个数
- **错误处理**：失败的 span 标红、记录异常、不吞掉原始异常
- **本地服务**：`/` 与 `/run/{id}` 均正常返回
- **CLI**：`agentveto demo / list / report / serve` 全部可用

demo 记录下来的 11 步：

```
depth  kind    dur      cost       name
0      chain   5202ms  $0.00000   agent.handle_ticket
1      llm     1180ms  $0.00417   openai.chat.completions.create
1      tool     141ms  $0.00000   lookup_order
1      llm     1420ms  $0.00500   openai.chat.completions.create
1      chain    457ms  $0.00000   verify_policy
2      llm      421ms  $0.00012   openai.chat.completions.create
2      tool      36ms  $0.00000   query_policy_db
1      tool      91ms  $0.00000   issue_refund          <-- ERROR
1      llm     1611ms  $0.00560   openai.chat.completions.create
1      tool     211ms  $0.00000   issue_refund
1      tool      90ms  $0.00000   escalate_to_human
```

---

## 四、怎么跑

```bash
cd agentveto
pip install -e ".[dev]"

python examples/demo.py        # 无需 API key，直接出报告
pytest -q                      # 16 个测试
agentveto serve --open         # 本地查看器
```

---

## 五、需要你本人去注册的（我一件都替不了）

| # | 事项 | 为什么非你不可 | 耗时 | 紧急度 |
|---|---|---|---|---|
| 1 | **GitHub 账号 + 建仓库 `agentveto`** | 需要你的身份认证；这是项目唯一的门面 | 10 分钟 | 立刻 |
| 2 | **Hacker News 账号** | Show HN 首发用。**现在就要注册**——HN 对老账号有加权，新号发帖容易被埋，账号得养一两周 | 5 分钟 | **立刻**（要养） |
| 3 | **Reddit 账号** | r/LocalLLaMA、r/AI_Agents、r/Python。同理，新号发推广会被删，需要养 | 5 分钟 | **立刻**（要养） |
| 4 | **域名 `agentveto.dev`**（`.com` 大概率被抢，先试 `.dev`） | 落地页用 | 10 分钟 | 本周 |
| 5 | **PyPI 账号 + 2FA + API token** | 发包用，名字已被我确认是空的 | 15 分钟 | 本周 |
| 6 | **Stripe 账号** | 收美元，需要身份/主体 KYC | 1–3 天审核 | 第 2 个月前 |
| 7 | **收款主体** | 个体工商户 / 香港或新加坡主体。找个做出海的会计聊一小时 | 1–2 周 | 第 2 个月前 |

**第 2、3 项有时间敏感性**：HN 和 Reddit 的账号权重跟注册时长挂钩，现在注册、两周后用，比两周后注册当天用效果好得多。这两件是唯一"早做有复利"的事。

---

## 六、唯一还卡着的你的动作：README 的 GIF

我在 README 里留了 TODO。**这个 GIF 是首周转化最关键的东西，别跳过。**

等报告界面你满意了，录一段 15 秒的（跑 demo → 打开报告 → 点几行），我帮你裁剪和压缩。

---

## 七、我下一步能做的（等你给信号）

- 你建好 GitHub 仓库 → 我写 CI、issue 模板、contributing、release 流程
- **V1 策略闸门开工（建议第 3 个月，现在就可以先出设计）** —— 这是唯一的无人区
- 你要发 Show HN → 我帮你打磨标题和第一屏

按上面的修正，**Veto 优先于 Prove**。竞品全卡在"记录"，拦截层是唯一没人的地方。

---

## 八、更新（2026-09-04 晚间）：**V1 = Veto 策略闸门，原型已落地**（commit `453dd40`）

等 token 的间隙把 V1 从"设计"做成了"能跑的原型"。路线图第 2 步提前开工，本地完成、38 个测试全过。

### 新增/变更

```
agentveto/
  agentveto/
    veto.py        V1 核心：Decision / VetoError / evaluate / @guard
    tracer.py      改动：span 支持 set_attribute（决策结束回写）
    _context.py    改动：current_tracer contextvar（guard 落到调用方自己的库）
    report.py      改动：被拦的行打紫色 "veto" 标 + 详情显示决策摘要
    cli.py         demo 子命令加 --veto
    demo.py        build_veto_run / demo_veto()
  tests/test_veto.py   22 个新测试
  examples/veto_demo.py
```

### Veto 是怎么工作的（30 秒讲清楚）

```python
from agentveto import guard, VetoError

POLICY = {"default": "allow", "rules": [
    {"name": "no-customer-email", "action": "send_email", "effect": "deny",
     "reason": "Outbound email to a customer requires a human."},
    {"name": "refund-needs-approval", "action": "issue_refund", "effect": "ask",
     "when": {"amount_usd": {"gt": 250}}, "reason": "Over $250 needs a human."},
]}

@guard(POLICY, action="issue_refund")
def issue_refund(order_id, amount_usd): ...
```

- 策略是普通 dict：规则有序、**第一条命中生效**（防火墙语义）；`when` 用点路径 + `eq/ne/gt/gte/lt/lte/in/exists`
- `deny` → 抛 `VetoError`，**被包函数不执行**
- `ask` → 终端问人；**没有人在（CI/cron/服务器）就拒绝（fail closed）**，绝不默认放行
- 每次决策（allow/deny/ask + 规则名 + 理由）都写进 trace；被拦的行在报告里显示红色 + 紫色 `veto` 标
- 支持 async、位置参数自动映射到 payload 字段名

### 验证

```
38 passed in 0.84s   （原来 16 个，新增 22 个）
```

Veto demo 报告：9 步，**3 次执行前拦截**（超 $250 退款 ask→无人拒绝、给客户发邮件 deny、全量 PII 导出 deny），整 run 状态健康——agent 处理了每次拦截。20 KB 单文件、零外部依赖。

### 关键取舍（为什么这样做）

1. **决策不新建表，复用 span**——store schema 一行没改，report/serve/CLI 全部自动兼容。克制架构本能的正确示范。
2. **策略不用 YAML 也不用 CEL**——普通 dict 起步，零依赖。CEL + 可视化编辑器是"产品化阶段"的事（第 6 个月），不是原型期的事。
3. **tracer 增加 `current_tracer` contextvar**——这样 guard 拦下来时，决策落在**正在跑的 run 自己的库里**，而不是全局单例库。这是多实例共存的关键修复。

### 还卡着的（不变）

GitHub 推送：需要你重新生成一个勾了 **`repo` + `workflow`** 的 classic token（或确认仓库建在 `StateKnot/agentveto` 还是 `jiawenyao401/agentveto`）。token 一到，`e9e88f4`（V0）+ `453dd40`（V1）一起推上去，CI 自动跑 38 个测试。
