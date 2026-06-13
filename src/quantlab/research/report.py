import json

from .experiment import (
    ExperimentResult
)


class Report:

    # 基于 ExperimentResult 生成可读报告
    #
    # 现在：generate() → 文本
    # 未来：to_html() → 网页
    #      to_json() → 给前端
    #
    # 报告里包含：
    #   - 标识信息（name / strategy / params / 时间 / commit）
    #   - 关键指标（Sharpe / MaxDD / Return / 交易数）
    #   - 风险指标（WinRate / ProfitFactor）
    #   - 元数据（commit_id）— 出问题能追溯到具体代码

    def __init__(self, result: ExperimentResult):

        self.result = result

    def _section(self, title, lines):

        out = [
            "",
            "-" * 50,
            f"  {title}",
            "-" * 50,
        ]
        for k, v in lines:

            out.append(
                f"  {k:<18}: {v}"
            )
        return "\n".join(out)

    def generate(self) -> str:

        r = self.result

        m = r.metrics

        out = []

        out.append("=" * 50)

        out.append(
            f"  Experiment: {r.name}"
        )

        out.append("=" * 50)

        out.append(
            self._section(
                "Identification",
                [
                    ("Strategy", r.strategy_name),
                    ("Params", str(r.params)),
                    ("Run Time", r.run_time),
                    ("Commit", r.commit_id)
                ]
            )
        )

        out.append(
            self._section(
                "Performance",
                [
                    ("Final Equity", m.get("final_equity")),
                    ("Total Return (%)", m.get("total_return")),
                    ("Sharpe", m.get("sharpe")),
                    ("Max Drawdown (%)", m.get("max_drawdown")),
                    ("Exposure (%)", m.get("exposure"))
                ]
            )
        )

        out.append(
            self._section(
                "Trading",
                [
                    ("Fill Count", m.get("fill_count")),
                    ("Trade Count", m.get("trade_count")),
                    ("Win Rate (%)", m.get("win_rate")),
                    ("Profit Factor", m.get("profit_factor")),
                    ("Avg Trade", m.get("avg_trade"))
                ]
            )
        )

        out.append("=" * 50)

        return "\n".join(out)

    def to_dict(self):

        return self.result.to_dict()

    def to_json(self, indent=2):

        return json.dumps(
            self.result.to_dict(),
            indent=indent,
            default=str
        )

    def to_html(self) -> str:

        # 未来：完整 HTML 模板
        # V1：最简 table
        r = self.result
        m = r.metrics

        rows = "".join(

            f"<tr><td>{k}</td><td>{v}</td></tr>"
            for k, v in m.items()
        )

        return (
            "<html><body>"
            f"<h1>{r.name}</h1>"
            f"<p>Strategy: {r.strategy_name} "
            f"Params: {r.params}</p>"
            f"<p>Run: {r.run_time} "
            f"Commit: {r.commit_id}</p>"
            "<table border='1'>"
            f"{rows}"
            "</table>"
            "</body></html>"
        )
