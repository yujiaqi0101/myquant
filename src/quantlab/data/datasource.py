"""
DataSource：数据源抽象
未来要接：
- CSV 单文件 / 多文件
- Parquet
- API（Wind / Tushare / JoinQuant）
- 实时：Kafka / WebSocket

V1：只做 CSV
未来：每种数据源一个实现类
"""


class DataSource:

    # 抽象基类
    # V1 暂未强制继承约束
    # 后续用 ABCMeta

    def load(self):
        raise NotImplementedError


class CSVSingleSource(DataSource):

    # 单文件 CSV
    # 包含单只标的数据

    def __init__(
        self,
        path,
        parse_dates=True,
        index_col=0,
    ):

        self.path = path
        self.parse_dates = parse_dates
        self.index_col = index_col

    def load(self):

        import pandas as pd
        return pd.read_csv(
            self.path,
            parse_dates=self.parse_dates,
            index_col=self.index_col,
        )


class CSVMultiSource(DataSource):

    # 多文件 CSV（每 symbol 一个文件）
    # 返回 Dict[symbol, DataFrame]
    # 与 StrategyContext.data 结构对齐

    def __init__(
        self,
        directory,
        symbols,
        pattern="{symbol}.csv",
    ):

        self.directory = directory
        self.symbols = symbols
        self.pattern = pattern

    def load(self):

        import os
        import pandas as pd

        data = {}
        for sym in self.symbols:

            path = os.path.join(
                self.directory,
                self.pattern.format(
                    symbol=sym,
                ),
            )

            data[sym] = pd.read_csv(
                path,
                parse_dates=True,
                index_col=0,
            )

        return data
