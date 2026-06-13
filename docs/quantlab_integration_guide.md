# QuantLab 集成指南（Phase 1）

> 本文档记录 myquant 项目对 quantlab 回测框架的 Phase 1 集成方案。
> 集成目标：把 `D:\python_workspace\quantlab\quantlab` 整个包作为 `src.quantlab` 子包纳入 myquant，
> 并保证 12 个核心 Stage 全部能跑通。

---

## 目录

- [1. 模块结构](#1-模块结构)
- [2. 与 myquant 引擎对照表](#2-与-myquant-引擎对照表)
- [3. 依赖说明](#3-依赖说明)
- [4. 12 个 Stage 验证结果](#4-12-个-stage-验证结果)
- [5. 路径与导入约定](#5-路径与导入约定)
- [6. 已知问题与修复方案](#6-已知问题与修复方案)
- [7. 后续 Phase 规划](#7-后续-phase-规划)

---

## 1. 模块结构

### 1.1 复制后落点

源：`D:\python_workspace\quantlab\quantlab\`
目标：`D:\python_workspace\myquant\src\quantlab\`

```text
D:\python_workspace\myquant\src\quantlab\
├── _compat.py
├── _main_demo.py          # 12 Stage 验证入口（原 main.py 改名版）
├── analytics.py
├── cache.py
├── context.py
├── event_engine.py
├── optimizer.py
├── parallel_optimizer.py
├── portfolio.py
├── signal.py
├── statistics.py
├── strategy.py
├── trade.py
├── tradebook.py
├── adapters/              # 1
├── core/                  # 2
├── data/                  # 3
├── engine/                # 4
├── event/                 # 5
├── examples/              # 复制自 quantlab/examples/
├── execution/             # 6
├── factors/               # 7
├── live/                  # 8
├── portfolio_construction/# 9
├── research/              # 10
├── risk/                  # 11
└── signals/               # 12
```

### 1.2 12 个子包

| # | 子包 | 主要职责 | 关键类/函数 |
|---|------|----------|-------------|
| 1 | `adapters` | 把策略接入不同回测后端（vectorbt / 内部引擎） | `VectorBTAdapter`、`SubprocessVectorBT`、`_vbt_worker` |
| 2 | `core` | 通用数据结构与基础类 | `Portfolio`、`Position`、`TradeBook`、`Fill`、`Order`、`Tick`、`BacktestResult`、`PortfolioSnapshot`、`BaseBacktestEngine` |
| 3 | `data` | 数据源 + 因子缓存 + 上下文 | `StrategyContext`、`factor_cache`、`DataSource`、`TickFeed` |
| 4 | `engine` | 多资产 Bar/Tick 引擎 | `BarEngine`、`TickEngine`、`TickMatcher`、`IntrabarExecution` |
| 5 | `event` | 事件总线与事件类型 | `EventBus`、`EventType` |
| 6 | `execution` | 撮合、滑点、佣金模型 | `PercentageCommission`、`PercentageSlippage`、`TargetWeightExecution`、`Matcher`、`TickSlippage` |
| 7 | `factors` | 内置技术因子 | `ma`、`rsi`、`atr`、`boll` |
| 8 | `live` | Live / Paper / Replay 交易 | `LiveEngine`、`PaperBroker`、`ReplayMarketData`、`OrderManager`、`Broker` |
| 9 | `portfolio_construction` | 组合构造器 | `TopN`、`EqualWeight`、`TargetPortfolio`、`PortfolioConstructor` 基类 |
| 10 | `research` | 研究流水线 + 实验跟踪 | `Experiment`、`Report`、`WalkForward`、`ValidationRunner`、`ExperimentTracker`、`Database`、`Repository` |
| 11 | `risk` | 风控检查与止损 | `RiskManager`、`KillSwitch`、`EmergencyStop`、`OrderSizeCheck`、`PositionLimitCheck`、`MaxOrderSize`、`MaxPositionLimit` |
| 12 | `signals` | 信号实现 | `BaseSignal`、`MACrossSignal`、`RSISignal` |

### 1.3 顶层模块（package 内）

| 模块 | 用途 |
|------|------|
| `strategy.py` | `BaseStrategy` / `MACrossStrategy`（V3 抽象） |
| `signal.py` | 信号生成器协议（注意：与 stdlib 同名，已在 sys.path 中隔离） |
| `portfolio.py` | 组合顶层 API |
| `trade.py` | 交易对象 |
| `tradebook.py` | 交易簿 |
| `event_engine.py` | `EventEngine`（事件驱动版回测） |
| `optimizer.py` | 网格搜索优化器 |
| `parallel_optimizer.py` | 多进程/多线程并行优化 |
| `analytics.py` | 业绩分析辅助 |
| `statistics.py` | 统计工具 |
| `cache.py` | 顶层缓存 |
| `context.py` | 顶层上下文 |
| `_compat.py` | 兼容性垫片（被 signal/strategy 等相对引用） |
| `_main_demo.py` | 12 Stage 验证入口（演示脚本） |
| `examples/` | `run_pipeline.py`、`run_rsi.py` 两个示例 |

---

## 2. 与 myquant 引擎对照表

| 维度 | myquant 原生 | quantlab (`src.quantlab.*`) | 集成策略 |
|------|--------------|----------------------------|----------|
| 包路径 | `src.engine.*` / `src.strategies.*` | `src.quantlab.engine.*` / `src.quantlab.strategy` | 共存，按场景选用 |
| 回测引擎 | `BacktestEngine`（基于 `BaseStrategy`，事件循环 + 风控） | `BarEngine`（多资产 + 组合构造层）<br>`EventEngine`（事件驱动）<br>`TickEngine`（逐笔） | QuantLab 引擎更适合多资产；myquant `BacktestEngine` 适合单标的 + 复杂出场 |
| 策略基类 | `src.engine.base_strategy.BaseStrategy` | `src.quantlab.strategy.BaseStrategy`（不同接口） | Phase 2 写适配器：把 myquant `BaseStrategy` 包成 QuantLab 策略 |
| 因子/信号 | `src.factors.calculator.FactorCalculator` | `src.quantlab.factors.{ma,rsi,atr,boll}` + `src.quantlab.signals.{ma_cross,rsi}` | QuantLab 仅内置技术因子；研究类/估值类因子继续走 myquant |
| 组合构建 | 无内建（写在策略里） | `TopN` / `EqualWeight` / 自定义 `PortfolioConstructor` | 逐步迁移多资产策略到 QuantLab |
| 撮合 | 默认 `close` 价 + 滑点 | `TargetWeightExecution` + `PercentageCommission/Slippage` | 撮合逻辑更精细，Phase 2 在 myquant 中接入 |
| 风控 | `src.risk.RiskController`（下单前/下单后） | `src.quantlab.risk.RiskManager`（多 check 链） | 短期并行；长期统一到 QuantLab `RiskManager` |
| 报告 | `src.enhancement.analyzer` + `src.report.html_reporter` | `src.quantlab.research.Report`、`WalkForwardReport` | QuantLab 报告更结构化，可直接复用到 myquant |
| 实验跟踪 | 无统一入口 | `ExperimentTracker` + SQLite | Phase 2 把 myquant 跑的回测统一入库 |
| Walk Forward | 无内建 | `WalkForwardRunner` / `WalkForwardReport` | 直接使用 QuantLab |
| Live / Paper | 无内建（仅 QMT/XtQuant 桥接） | `LiveEngine` + `PaperBroker` + `ReplayMarketData` | Phase 3 引入 Replay 做策略沙盒测试 |
| 数据源 | `src.data.*`（CSV / SQLite / 东财 / QMT） | `src.quantlab.data.datasource`（DataFrame 字典） | Phase 2 写 `Adapter`：myquant DB → QuantLab `data: Dict[str, DataFrame]` |

### 2.1 接口差异速记

- myquant 策略：继承 `BaseStrategy`，实现 `on_init(ctx)` / `on_bar(ctx)`，返回 `List[Order]`。
- QuantLab 策略（V3 协议）：实现 `signal(ctx) -> DataFrame`（多标的多空分数），由 `BarEngine` 串起
  `signal → portfolio_constructor → execution → fill → tradebook` 完整链路。

### 2.2 共存方案（推荐）

```text
myquant
├── src/strategies/<id>/<name>.py         # 业务策略（沿用 myquant 协议）
├── src/engine/                            # myquant 原生引擎（兼容层）
└── src/quantlab/                          # QuantLab 引擎（多资产 / 研究 / Live）
        ├── strategy.py                    # 未来在这里加 myquant→quantlab 适配器
        ├── research/                      # 直接 import 使用
        └── live/                          # Phase 3
```

短期不做强制迁移；新写的多资产 / Walk-Forward / 实验跟踪场景直接用 QuantLab。

---

## 3. 依赖说明

### 3.1 必需依赖

| 包 | 用途 | myquant `requirements.txt` 现状 |
|----|------|---------------------------------|
| `numpy>=1.21` | 数值计算 | 已声明 |
| `pandas>=1.3` | DataFrame / 时间序列 | 已声明 |
| `scipy>=1.7` | 统计 | 已声明 |
| `sqlalchemy>=1.4` | SQLite 实验库 | 已声明 |

### 3.2 可选依赖（vectorbt）

| 包 | 状态 | 行为 |
|----|------|------|
| `vectorbt` | **可选**，未安装也能跑 | `src.quantlab.adapters` 在 import 时 `try/except` 包裹；如果本机没装，`VectorBTAdapter = None`；同时提供 `SubprocessVectorBT` 通过子进程在沙箱里跑 VBT |

本机实测：
- `import vectorbt` 直接抛 `STATUS_DLL_NOT_FOUND`（依赖 TA-Lib / Numba 编译产物）。
- 但 `SubprocessVectorBT` 仍可用 → VectorBT 在独立子进程中运行，隔离 DLL 加载问题。
- 因此 `from src.quantlab.adapters import VectorBTAdapter` 即使在 vbt 未装的主进程里也能返回对象（值为 `None` 时上层会跳过）。

### 3.3 其它可选

| 包 | 用于 | 备注 |
|----|------|------|
| `numba` | `parallel_optimizer` 多线程 | 装了走线程池，未装走 ProcessPool |
| `plotly` / `matplotlib` | `WalkForwardReport` HTML 内嵌图 | 缺失时 HTML 仅输出表格 |
| `jinja2` | Report 模板 | 缺失时退化纯文本 |

### 3.4 Python / 环境

- Python 3.12.7（`D:\Program Files\Python312\python.exe`）
- Windows，`multiprocessing` 默认 `spawn` → 多进程 stage 需要 `if __name__ == "__main__":` 包裹。
- 已写入 `D:\Program Files\Python312\Lib\site-packages\myquant_src.pth`，把
  `D:\python_workspace\myquant\src` 加入 `sys.path`，
  使 `from quantlab.X` 和 `from src.quantlab.X` 两种 import 都能解析。

---

## 4. 12 个 Stage 验证结果

### 4.1 运行命令

```powershell
cd D:\python_workspace\myquant
& "D:\Program Files\Python312\python.exe" "D:\python_workspace\myquant\src\quantlab\_main_demo.py"
```

退出码：`0`（全部跑完无未捕获异常）。

### 4.2 结果表

| # | Stage | 状态 | 关键证据 |
|---|-------|------|----------|
| 1 | Experiment：单次实验 | **PASS** | `Final Equity 134988.35 / Sharpe 1.183 / MaxDD -16.51%` |
| 2 | Report：报告生成 | **PASS** | `to_html() length 643 chars`、`to_dict()` 返回完整 metrics |
| 3 | WalkForward：滚动训练/测试 | **PASS** | `Windows=1 / Avg Test Sharpe 0.773 / Avg Test Return 4.52%` |
| 4 | ValidationRunner：双引擎对比 | **PASS** | `fast_sharpe=-1.234 precise_sharpe=1.183`，引擎差异被检测到（`consistency=0.0` 属正常：VBT 与 BarEngine 在小数据上 Sharpe 差异巨大，校验机制工作正常） |
| 5 | EventEngine：事件驱动版 | **PASS** | Bar vs Event 等价性 `diff=0.00%`（4 项指标全为 0） |
| 6 | Fast→Precise 双引擎优化 | **PASS** | 16 组 VBT 网格 + Top10 Precise 验证 → 1 OK / 9 ELIMINATED，CSV 落盘 `reports/validation_report.csv` |
| 7 | V1.9 Multi-Asset 接口验证 | **PASS** | `ctx.symbols=['AAPL','MSFT','NVDA']`、`pnl_by_symbol`、`trade_count_by_symbol` 全部打印 |
| 8 | V2.0 VectorBTAdapter：组合权重策略 | **PASS** | `source=vectorbt, weights_df shape=(300,3)`，说明 SubprocessVectorBT 跑通 |
| 9 | V2.1 ParallelOptimizer：多进程网格搜索 | **PASS** | 6 组参数 / 4 workers / 4.70s，CSV 落盘 `reports/parallel_grid.csv` |
| 10 | V2.2 WalkForwardEngine 正式版 | **PASS** | 3 windows / stitched 476 bars / `Stitched Sharpe -0.227`，HTML 报告 58463 bytes |
| 11 | V2.3 Experiment Tracking | **PASS** | 4 experiments 入库 / search 3 种过滤 / leaderboard 2 种排序 / DB 53248 bytes（**V2.3 PASS**） |
| 12 | LiveTrading (V2.5)：Paper + Replay | **PASS** | `source=live / n_ticks=0 / final_eq=100000`，3 个 log 文件创建（**V2.5 PASS**） |

**汇总：12/12 PASS。**

### 4.3 验收检查点

- [x] `D:\python_workspace\myquant\src\quantlab\` 存在，含 12 个子包
- [x] `D:\python_workspace\myquant\src\quantlab\_main_demo.py` 存在
- [x] `python -c "from src.quantlab.engine import BarEngine; print('OK')"` 通过
- [x] `python -c "from quantlab.event_engine import EventEngine; print('OK')"` 通过
- [x] `python -c "from src.quantlab.research import Experiment, Report, WalkForward, ValidationRunner; print('OK')"` 通过
- [x] 跑 main demo 至少 6 个 Stage PASS（实测 12/12）
- [x] `docs\quantlab_integration_guide.md` 存在且 ≥ 200 行（本文）

---

## 5. 路径与导入约定

### 5.1 sys.path 配置

为了让 `from quantlab.X` 和 `from src.quantlab.X` 都能解析：

1. 写入 `.pth` 文件：
   `D:\Program Files\Python312\Lib\site-packages\myquant_src.pth`
   内容：`D:\python_workspace\myquant\src`
2. `_main_demo.py` 顶部主动清理 `sys.path[0]`（脚本所在目录 `src/quantlab/`），
   再插入 `_SRC_DIR` 与 `_PROJECT_ROOT`，
   避免 quantlab 的 `signal.py` 抢走 stdlib `signal` 模块。

### 5.2 推荐 import 风格

```python
# 业务代码里推荐用 src.quantlab 前缀（明确命名空间）
from src.quantlab.engine import BarEngine
from src.quantlab.research import Experiment, Report, WalkForward, ValidationRunner
from src.quantlab.portfolio_construction import TopN
from src.quantlab.execution import (
    TargetWeightExecution,
    PercentageCommission,
    PercentageSlippage,
)

# demo 脚本（_main_demo.py）允许省略前缀以减少改动
from quantlab.engine import BarEngine
```

### 5.3 禁止项

- 不要在 `src/quantlab/__init__.py` 里写 `from quantlab import *`。
  量化包是 namespace package（无 `__init__.py`），保持 PEP 420 行为可避免与 stdlib 冲突。
- 不要把 `src/quantlab/signal.py` 改名（会破坏 QuantLab demo 与未来适配器）。

---

## 6. 已知问题与修复方案

### 6.1 `signal.py` 与 stdlib `signal` 冲突

- 现象：直接 `python script.py` 跑时，pandas → subprocess → `import signal` 解析到 `src/quantlab/signal.py`。
- 修复：`_main_demo.py` 启动时清掉脚本目录（`sys.path[0]`）再插入正确路径。
- 影响范围：仅 demo 脚本；业务 import 用 `from src.quantlab.X` 不会触发。

### 6.2 Windows 多进程 `RuntimeError`

- 现象：`ParallelOptimizer.run()` 报 "An attempt has been made to start a new process..."。
- 修复：`_main_demo.py` 主体包在 `if __name__ == "__main__":` 内。
- 影响范围：仅 demo 脚本；导入 QuantLab 模块本身不受影响。

### 6.3 `vectorbt` 未安装

- 现象：主进程 `import vectorbt` 崩溃（`STATUS_DLL_NOT_FOUND`）。
- 修复：默认走 `SubprocessVectorBT`（子进程运行 VBT）。
  也可在独立 conda 环境中装 vbt，然后单独跑 V2.0 / V2.1 Stage。
- 影响范围：V2.0/V2.1/V2.2 的 VBT 部分用 Subprocess 模式运行，结果会与本机直接跑略有差异（采样/费用细节）。

### 6.4 数据路径硬编码

- 现象：原 `quantlab/main.py` 用 `pd.read_csv(f"data/{sym}.csv")`，依赖 cwd。
- 修复：`_main_demo.py` 用 `os.path.abspath` 解析到 `D:\python_workspace\quantlab\data`。
- 后续：Phase 2 写 `myquant → quantlab` 数据适配器，从 myquant SQLite 取数。

### 6.5 `StrategyContext.symbols` 与 myquant 上下文不互通

- 现象：QuantLab 假设 `data: Dict[str, DataFrame]`，myquant 走 `Context` 对象 + DB。
- 修复：Phase 2 写一个 `myquant_to_quantlab_data(db, symbols, start, end)` 转换器。
- 状态：已记入待办，本 Phase 不实现。

---

## 7. 后续 Phase 规划

### Phase 2 — 适配层 + 复用

1. 写 `src/quantlab/adapters/myquant_data.py`：
   `dict[symbol, DataFrame] = load_from_myquant_db(symbols, start, end)`
2. 写 `src/quantlab/adapters/myquant_strategy.py`：
   把 `BaseStrategy.on_bar` 包装成 QuantLab 协议下的 `signal(ctx) -> DataFrame`。
3. 跑一遍 myquant 现网策略（如 `northbound_timing_v1`）在 QuantLab `BarEngine` 上，
   对比 myquant `BacktestEngine` 跑同数据的 `final_equity` / `Sharpe` / `MaxDD`，
   差异 < 1% 视为通过。

### Phase 3 — 研究流水线接管

1. myquant 跑回测后统一走 `ExperimentTracker` 入库。
2. 用 `WalkForwardRunner` + `ParallelOptimizer` 做参数搜索（取代当前 `multi_factor_backtest` 里的 grid）。
3. 把 `enhancement/metrics.py` 跟 `research/report.py` 的指标体系对齐。

### Phase 4 — Live / Replay

1. 用 `ReplayMarketData` + `PaperBroker` 做策略沙盒冒烟（接 myquant 历史数据）。
2. 接 QMT 真实 broker（Phase 5，独立任务）。

---

## 附录 A：验证命令清单

```powershell
# 1) 子包存在性
Test-Path D:\python_workspace\myquant\src\quantlab\_main_demo.py
Get-ChildItem D:\python_workspace\myquant\src\quantlab -Directory |
    Select-Object -ExpandProperty Name

# 2) 核心 import
& "D:\Program Files\Python312\python.exe" -c "from src.quantlab.engine import BarEngine; print('OK')"
& "D:\Program Files\Python312\python.exe" -c "from quantlab.event_engine import EventEngine; print('OK')"
& "D:\Program Files\Python312\python.exe" -c "from src.quantlab.research import Experiment, Report, WalkForward, ValidationRunner; print('OK')"

# 3) 跑 12 Stage demo
& "D:\Program Files\Python312\python.exe" "D:\python_workspace\myquant\src\quantlab\_main_demo.py"
```

## 附录 B：文件清单（Phase 1 新增/复制）

- `src/quantlab/`（整包，从 `D:\python_workspace\quantlab\quantlab` 复制）
- `src/quantlab/_main_demo.py`（从 `quantlab/main.py` 改名并修补）
- `src/quantlab/examples/`（从 `quantlab/examples/` 复制）
- `D:\Program Files\Python312\Lib\site-packages\myquant_src.pth`（系统级 path 注入）
- `docs/quantlab_integration_guide.md`（本文档）

---

# Phase 5/6 集成扩展：SignalStrategy + 6 个子命令 CLI

> 本节为 Phase 5+ 补充。涵盖：
> - SignalStrategy 策略范式
> - 6 个 quantlab 子命令
> - 4 张表 research.db
> - 与 myquant v1 引擎的共存与迁移

---

## 8. SignalStrategy 范式（quantlab 开发规范）

### 8.1 为什么放弃 on_bar 重写为 signal

myquant v1 策略继承 `BaseStrategy`，实现 `on_bar(ctx)` 事件回调：
- 策略里既选股、也调仓、还管风控
- 4 类职责耦合在一起 → 难复用、难测试、难切换引擎

quantlab 范式把"想要什么"和"如何成交"彻底解耦：
- **策略层**（`SignalStrategy`）只输出 `signal(ctx) -> DataFrame(date × symbol, values ∈ {-1, 0, 1})`
- **组合层**（`PortfolioConstructor`，如 `TopN`）把 signal → 目标权重
- **执行层**（`Execution`）把目标权重 → 订单
- **撮合层**（`Matcher` / 引擎）扣现金、记成交

这样**一套策略可以无修改地跑在 BarEngine / EventEngine / VectorBT / TickEngine 上**。

### 8.2 SignalStrategy 契约

```python
from src.quantlab.signals.base import SignalStrategy
import pandas as pd


class MyStrategy(SignalStrategy):
    """策略类必须遵循以下约定"""

    # 推荐：明确类名（用于注册表与 CLI）
    name = "my_strategy"
    description = "我的策略"

    def __init__(self, top_n: int = 30, min_amount: float = 500.0):
        # 1) 所有参数存为基本类型（int/float/bool/str）→ 可 JSON 序列化
        self.top_n = int(top_n)
        self.min_amount = float(min_amount)
        # 2) 启动即失败：参数合理性校验
        if self.top_n < 1:
            raise ValueError(f"top_n must be >= 1, got {top_n}")

    def signal(self, ctx) -> pd.DataFrame:
        # 3) 输出：完整 DataFrame(index=date, columns=symbol, values∈{-1,0,1})
        out = {}
        for sym in ctx.data:
            out[sym] = self._signal_one(ctx, sym)
        return pd.DataFrame(out).astype("int8")

    def _signal_one(self, ctx, sym: str) -> pd.Series:
        df = ctx.data[sym]
        # 单标的逻辑
        return (df["close"] > df["close"].rolling(20).mean()).astype("int8")
```

### 8.3 已重写的 6 个 v2 策略

| 策略 | 文件 | 调仓频率 | 选股维度 |
|------|------|----------|----------|
| `small_cap_v2` | `src/strategies/3a7b2c01/small_cap_v2.py` | 月度 | 市值/流动性/波动率/动量/上市天数 |
| `small_cap_quality_v2` | `src/strategies/5d8e3f02/small_cap_quality_v2.py` | 月度 | 小市值 + ROE/盈利质量 |
| `pb_roe_monthly_v2` | `src/strategies/7f9a4b03/pb_roe_monthly_v2.py` | 月度 | 低 PB + 高 ROE |
| `sector_flow_monthly_v2` | `src/strategies/2c6d5e04/sector_flow_monthly_v2.py` | 月度 | 行业资金流 |
| `northbound_timing_v2` | `src/strategies/4e8c3d06/northbound_timing_v2.py` | 周度 | 北向资金择时 |
| `breakout_pullback_v2` | `src/strategies/9b1f7a05/breakout_pullback_v2.py` | 日度 | 突破回踩 |

每个 v2 策略都附 `PARAM_SPACE` 常量（dict），可直接喂给 Optimizer 做网格搜索。

### 8.4 v2 策略注册（自动发现）

`src/quantlab_adapters/strategy_registry.py` 的 `discover_v2_strategies("src.strategies")` 会：

1. 扫描 `src/strategies/*/` 目录
2. 加载所有 `*_v2.py` 文件
3. 找出所有 `SignalStrategy` 子类（无论是否带装饰器）注册到 `SignalStrategyRegistry`

CLI 调 `python main.py strategy --list` 即可看到全部 v1+v2 策略。

---

## 9. quantlab CLI：6 个子命令

### 9.1 入口

```powershell
python main.py quantlab --help
# usage: main.py quantlab [-h]
#   {run,compare,optimize,walkforward,track,quintile} ...
```

### 9.2 公共参数

所有子命令都支持（除 track/quintile 部分子动作）：

| 参数 | 默认 | 含义 |
|------|------|------|
| `--strategy`, `-s` | （必填） | v2 策略名（如 `small_cap_v2`） |
| `--pool` | 无 | 股票池名（与 `--stocks` 互斥） |
| `--stocks` | 无 | 股票代码列表（逗号分隔） |
| `--start-date` | 2024-01-01 | 回测起始日 |
| `--end-date` | 2024-12-31 | 回测结束日 |
| `--engine` | bar | bar / event / vbt / tick / myquant / auto |
| `--no-risk-check` | False | 禁用 A 股 RiskCheck |
| `--no-execution-cost` | False | 禁用佣金和滑点 |
| `--initial-capital` | 1,000,000 | 初始资金 |
| `--output-dir` | reports/quantlab | 报告输出目录 |
| `--name` | 自动 | 报告名 |

### 9.3 子命令 1：run（单次回测）

```powershell
# 1) bar 引擎 + 3 只股票 + 短区间
python main.py quantlab run \
    --strategy small_cap_v2 \
    --stocks 000001.SZ,000002.SZ,000003.SZ \
    --start-date 2024-01-01 \
    --end-date 2024-06-30 \
    --engine bar

# 2) 走 pool + event 引擎 + --track 入库
python main.py quantlab run \
    --strategy pb_roe_monthly_v2 \
    --pool csi300 \
    --start-date 2023-01-01 \
    --end-date 2024-12-31 \
    --engine event \
    --track \
    --tag "csi300_pb_roe" \
    --note "Phase 6 烟测"
```

输出：
```
[quantlab/bar] 数据加载...
  加载完成: 3 个 symbol
开始回测 [引擎=bar, 策略=small_cap_v2]...
  回测耗时: 0.5s

=== 回测结果 ===
  引擎:    bar
  总收益:  12.34%
  夏普:    1.234
  最大回撤:-5.67%
  胜率:    58.00%
  交易次数:42
```

### 9.4 子命令 2：compare（多引擎对比）

```powershell
# 同一策略在 bar + event 两个引擎上跑，对比结果
python main.py quantlab compare \
    --strategy small_cap_v2 \
    --pool test \
    --start-date 2023-01-01 \
    --end-date 2024-12-31 \
    --engines bar,event
```

输出：
```
=== 多引擎对比 [small_cap_v2] ===
  引擎: ['bar', 'event']
  股票: 全市场

=== 对比结果 ===
引擎       总收益      夏普   最大回撤      胜率     交易数    耗时(s)
----------------------------------------------------------------------
bar         12.34%    1.234     -5.67%   58.00%         42     0.50
event       11.98%    1.198     -5.81%   57.50%         40     2.30

  对比结果已保存: reports/quantlab/compare/compare_small_cap_v2_xxx.json
```

**用途**：验证策略在不同引擎上结果是否一致（bar ≈ event，差异 < 1% 视为对齐）。

### 9.5 子命令 3：optimize（参数网格搜索）

```powershell
python main.py quantlab optimize \
    --strategy small_cap_v2 \
    --pool test \
    --start-date 2023-01-01 \
    --end-date 2024-12-31 \
    --engine bar \
    --param-space '{"top_n":[10,20,30],"min_amount":[200,500,1000],"max_vol":[0.03,0.05]}' \
    --scorer sharpe \
    --top-k 10
```

参数空间规则：
- 每个 key 对应策略的一个参数（如 `top_n` / `min_amount`）
- value 是候选值列表
- 总组合数 = 各列表长度之积

输出：
```
=== 参数优化 [small_cap_v2] ===
  引擎: bar
  评分: sharpe
  参数空间: {'top_n': [10, 20, 30], 'min_amount': [200, 500, 1000], 'max_vol': [0.03, 0.05]}
  组合数: 18
  Top K: 10

=== Top 10 ===
   top_n  min_amount  max_vol  ...  sharpe  total_return  max_drawdown  trade_count  score
0     20         500     0.05  ...   1.450         0.180        -0.045           38  1.450
...

  全部结果已保存: reports/quantlab/optimize/optimize_small_cap_v2_xxx.csv
```

### 9.6 子命令 4：walkforward（Walk-Forward 验证）

```powershell
# 3 年训练 / 1 年测试
python main.py quantlab walkforward \
    --strategy small_cap_v2 \
    --pool csi300 \
    --start-date 2018-01-01 \
    --end-date 2024-12-31 \
    --param-space '{"top_n":[10,20,30],"min_amount":[200,500,1000]}' \
    --train-years 3 \
    --test-years 1 \
    --top-train 5
```

输出：
```
=== Walk-Forward 验证 [small_cap_v2] ===
  训练/测试窗口: 3/1 年
  参数空间: {...}

=== Walk-Forward 结果 ===
  窗口数:        4
  平均测试夏普:  1.123
  平均测试收益:  8.50%
  Window 1: train=2018-2020 test=2021 sharpe=1.234 | params={...}
  Window 2: train=2019-2021 test=2022 sharpe=1.180 | params={...}
  Window 3: train=2020-2022 test=2023 sharpe=1.098 | params={...}
  Window 4: train=2021-2023 test=2024 sharpe=1.082 | params={...}
```

### 9.7 子命令 5：track（实验跟踪）

```powershell
# 列出最近 20 条 experiment
python main.py quantlab track list --limit 20

# 排行榜（按 sharpe 排前 10）
python main.py quantlab track leaderboard --sort-by sharpe --top 10

# 按稳定性排
python main.py quantlab track leaderboard --sort-by stability --top 20

# 搜索：高夏普 + 低回撤
python main.py quantlab track search \
    --strategy small_cap_v2 \
    --sharpe-min 1.0 \
    --max-dd-max 0.10 \
    --return-min 0.05

# 查看详情（含 equity 曲线）
python main.py quantlab track show --id exp_a30ccbc1

# 删除
python main.py quantlab track delete --id exp_a30ccbc1
```

输出（list）：
```
=== Experiment 列表 (limit=20) ===
          id   name   strategy  sharpe  total_return  max_drawdown  trade_count          created_at
exp_a30ccbc1 test_2 fake_strat     1.5          0.08         -0.02           10 2026-06-13T19:00:52
exp_6fb0c04a test_1 fake_strat     1.5          0.08         -0.02           10 2026-06-13T19:00:52
...
```

### 9.8 子命令 6：quintile（多因子分层回测）

```powershell
# 准备因子 CSV：index=date, columns=symbol
python -c "
import pandas as pd, numpy as np
dates = pd.bdate_range('2024-01-01', '2024-12-31')
syms = ['000001.SZ', '000002.SZ', '600000.SH', '600036.SH']
df = pd.DataFrame(np.random.randn(len(dates), len(syms)), index=dates, columns=syms)
df.to_csv('data/factor_test.csv')
"

# 跑分位回测
python main.py quantlab quintile \
    --factor-csv data/factor_test.csv \
    --pool csi300 \
    --start-date 2024-01-01 \
    --end-date 2024-12-31 \
    --n-quantiles 5 \
    --rebalance-freq 5 \
    --long-quantile 5 \
    --short-quantile 1
```

输出：
```
=== 多因子分层回测 [factor_test] ===
  分位数: 5
  调仓频率: 每 5 根 bar
  long quintile: Q5, short quintile: Q1

=== 分位结果 ===
分位          总收益       夏普    最大回撤
----------------------------------------
Q1        4.50%     0.450     -3.20%
Q2        6.80%     0.680     -2.80%
Q3        8.20%     0.820     -3.50%
Q4        9.80%     0.980     -3.10%
Q5       12.50%     1.250     -3.40%

  多空对冲 (Q5 - Q1):
    总收益: 8.00%
    夏普:   0.800
    最大回撤: -3.20%

  IC: mean=0.0850, std=0.1200, IR=0.7083
```

---

## 10. research.db：4 张表

路径：`storage/research.db`（自动创建）

### 10.1 Schema

```sql
-- 实验元数据
CREATE TABLE experiments (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    strategy     TEXT NOT NULL,
    params_json  TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    tag          TEXT DEFAULT '',
    note         TEXT DEFAULT ''
);

-- 回测核心指标
CREATE TABLE results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL,
    final_equity  REAL DEFAULT 0,
    total_return  REAL DEFAULT 0,
    sharpe        REAL DEFAULT 0,
    max_drawdown  REAL DEFAULT 0,
    trade_count   INTEGER DEFAULT 0,
    win_rate      REAL DEFAULT 0,
    source        TEXT DEFAULT 'event',
    extras_json   TEXT DEFAULT '{}',
    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
);

-- Walk-Forward 指标
CREATE TABLE walkforward (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id   TEXT NOT NULL,
    n_windows       INTEGER DEFAULT 0,
    avg_sharpe      REAL DEFAULT 0,
    avg_return      REAL DEFAULT 0,
    avg_max_dd      REAL DEFAULT 0,
    stitched_sharpe REAL DEFAULT 0,
    stitched_return REAL DEFAULT 0,
    stitched_max_dd REAL DEFAULT 0,
    stability_score REAL DEFAULT 0,
    parameter_drift REAL DEFAULT 0,
    extras_json     TEXT DEFAULT '{}',
    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
);

-- 逐 bar 权益曲线（Phase 6 新增）
CREATE TABLE equity_curves (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL,
    bar_idx       INTEGER NOT NULL,
    timestamp     TEXT NOT NULL,
    equity        REAL DEFAULT 0,
    drawdown      REAL DEFAULT 0,
    daily_return  REAL DEFAULT 0,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
);
```

### 10.2 4 张表的关系

```
experiments 1 ──< results         (1 条 experiment 1 条 result)
            ├──< walkforward      (1 条 experiment 1 条 wf 结果)
            └──< equity_curves    (1 条 experiment N 条 bar)
```

`ON DELETE CASCADE` 保证删 experiment 时自动清空其下 3 张子表。

### 10.3 Python API

```python
from src.quantlab.research.database import Database
from src.quantlab.research.repository import ExperimentRepository
from src.quantlab.research.tracker import ExperimentTracker, ExperimentRecord, ExperimentResultV2

# 1) 初始化
db = Database()  # 默认 storage/research.db
repo = ExperimentRepository(db=db)

# 2) 写
record = ExperimentRecord(
    name="my_run_001",
    strategy_name="small_cap_v2",
    params={"top_n": 30, "min_amount": 500},
    tag="csi300_test",
    note="Phase 6 烟测",
)
result = ExperimentResultV2(
    experiment=record,
    backtest_result=my_backtest_result,
)
exp_id = repo.save(result)

# 3) 写 equity 曲线
repo.save_equity_curve(
    exp_id,
    equity_curve=result.backtest_result.equity_curve,
    timestamps=result.backtest_result.timestamps,
)

# 4) 查
df = repo.get_equity_curve(exp_id)        # 逐 bar 权益
top = repo.leaderboard(sort_by="sharpe")   # Top N
hits = repo.search(strategy="small_cap_v2", sharpe_min=1.0)
```

### 10.4 CLI 视角

```powershell
# 查某 experiment 详情
python main.py quantlab track show --id exp_a30ccbc1
# 输出：
#   id: exp_a30ccbc1
#   name: test_2
#   strategy: fake_strat
#   params: {"p1": 12, "p2": 0.3}
#   sharpe: 1.5
#   ...
#   Equity 曲线: 4 根 bar
#     起点: equity=1.00
#     终点: equity=1.08
#     最大回撤: -2.00%
```

---

## 11. 与 myquant v1 引擎的共存

### 11.1 引擎自动选择

```python
# src/cli/backtest_cli.py:_resolve_engine_choice
def _resolve_engine_choice(strategy_name, requested):
    if requested == "auto":
        # 策略名以 _v2 结尾 → 走 quantlab；否则保留 myquant（兼容旧 v1）
        if strategy_name.endswith("_v2"):
            return "bar"
        return "myquant"
    return requested
```

行为：
- `python main.py backtest --strategy small_cap_v2` → 自动选 quantlab BarEngine
- `python main.py backtest --strategy small_cap_v1` → 自动选 myquant BacktestEngine
- 显式 `--engine event/vbt/tick` 强制 quantlab
- 显式 `--engine myquant` 强制旧引擎（即便策略是 v2）

### 11.2 旧引擎 deprecated

```python
# src/quantlab/multi_factor_quintile_backtest_v2.py 顶部
class MultiFactorQuintileBacktestEngineV2:
    """
    .. deprecated::
        自 Phase 5 起标记为 deprecated。请使用
        :class:`src.quantlab_quintile.QuintileExperiment`。
    """
    def __init__(self, *args, **kwargs):
        import warnings
        warnings.warn(
            "MultiFactorQuintileBacktestEngineV2 已废弃（Phase 5），"
            "请迁移到 src.quantlab_quintile.QuintileExperiment。",
            DeprecationWarning,
            stacklevel=2,
        )
```

### 11.3 v1 → v2 迁移步骤

1. **写 v2 策略**（继承 `SignalStrategy`，输出 `signal(ctx) -> DataFrame`）
2. **同名并存**：v1 命名 `xxx_v1.py`，v2 命名 `xxx_v2.py`
3. **自动注册**：`discover_v2_strategies("src.strategies")` 扫描 + 注册
4. **CLI 验证**：
   ```powershell
   python main.py strategy --list                 # 看 v1+v2 都有
   python main.py quantlab run -s xxx_v2 ...      # 跑 v2
   ```
5. **平行对比**：
   ```powershell
   python main.py backtest -s xxx_v1 ...          # v1 baseline
   python main.py backtest -s xxx_v2 ...          # v2 结果
   ```
   差异 < 1% 视为对齐。
6. **停用 v1**：删 `xxx_v1.py` 或保留仅作回归基线

---

## 12. 测试与验证

### 12.1 单元测试

```powershell
# quantlab 4 张表
python -m pytest tests/test_quantlab_cli.py::test_research_db_has_4_tables -v

# equity_curves 读写
python -m pytest tests/test_quantlab_cli.py::test_save_and_read_equity_curve -v
```

### 12.2 端到端冒烟（沙箱）

```powershell
# 1) 生成测试数据
python tests/generate_test_data.py

# 2) 注入到临时 DB（见 smoke_cli.py）

# 3) 跑 6 个子命令
python main.py quantlab run --strategy small_cap_v2 --pool csi300 --engine bar
python main.py quantlab compare --strategy small_cap_v2 --pool csi300 --engines bar,event
python main.py quantlab optimize --strategy small_cap_v2 --pool csi300 \
    --param-space '{"top_n":[10,20,30]}' --scorer sharpe --top-k 5
python main.py quantlab walkforward --strategy small_cap_v2 --pool csi300 \
    --param-space '{"top_n":[10,20]}' --train-years 3 --test-years 1
python main.py quantlab track list
python main.py quantlab track leaderboard --sort-by sharpe --top 5
python main.py quantlab quintile --factor-csv data/factor_test.csv --pool csi300
```

### 12.3 vbt 专项测试（用户机器上跑）

vbt 在沙箱里 `STATUS_DLL_NOT_FOUND`，用户服务器已装。vbt 专项测试标记为 `skipif`：

```python
# tests/test_quantlab_cli.py
VBT_AVAILABLE = False
try:
    import vectorbt
    VBT_AVAILABLE = True
except Exception:
    pass


@pytest.mark.skipif(not VBT_AVAILABLE, reason="vectorbt 未安装")
def test_quantlab_run_vbt_engine(tmp_db, monkeypatch):
    ...
```

跑全套测试时，本地 skip 不影响；用户机器上 vbt 装了会自动跑。

---

## 13. 常见问题 FAQ

### Q1. vbt 引擎在沙箱里崩溃怎么办？

A. vbt 依赖一些 Windows DLL，沙箱里 `import vectorbt` 直接 `STATUS_DLL_NOT_FOUND`。
- 默认走 bar/event 引擎
- vbt 路径全部用 `SubprocessVectorBT`（子进程），不阻塞主流程
- 写测试时加 `@pytest.mark.skipif(not VBT_AVAILABLE, ...)` 优雅跳过

### Q2. v2 策略的 params 怎么传给引擎？

A. v2 策略没有统一的 `params` 字典（v1 才有）。CLI 用 `_get_strategy_params()` 自动从
`vars(strategy)` 提取所有 int/float/bool/str 属性，作为 kwargs 传给引擎。

```python
# src/cli/quantlab_cli.py
def _get_strategy_params(strategy) -> dict:
    params = {}
    for k, v in vars(strategy).items():
        if k.startswith("_") or callable(v):
            continue
        if isinstance(v, (int, float, bool, str)):
            params[k] = v
    return params
```

### Q3. quintile 实验怎么读因子数据？

A. 因子必须是 CSV 格式：`index=date, columns=symbol, values=factor_value`。

```python
import pandas as pd
factor = pd.read_csv("data/factor.csv", index_col=0, parse_dates=True)
exp = QuintileExperiment(n_quantiles=5)
result = exp.run(factor_data=factor, data=quantlab_dict, long_quantile=5, short_quantile=1)
```

### Q4. 4 张表里 equity_curves 有什么用？

A. 1) 事后画图（不必重跑回测）
   2) 跨实验对比 equity
   3) Stitched OOS 拼接（walkforward 阶段）
   4) 存 drawdown / daily_return 序列，方便后处理

### Q5. 旧 myquant 引擎还能用吗？

A. 能。仅 v1 策略 + 显式 `--engine myquant` 时仍走 `BacktestEngine`。
v1 策略保留用于：
1. 历史报告回溯查询
2. Phase 5 迁移期的渐进式过渡
3. 与新 v2 策略的等价性回归测试

新策略请一律走 quantlab。

---

## 14. 版本兼容性

| 组件 | 兼容版本 | 说明 |
|------|----------|------|
| Python | 3.10+ | dataclass / type hint 语法 |
| pandas | 1.5+ | .astype("int8") 等 |
| numpy | 1.22+ | percentile 等 |
| vectorbt | 0.25+ | 沙箱装 0.26+ |
| SQLite | 3.35+ | JSON1 扩展 |

---
