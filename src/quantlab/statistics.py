def win_rate(trades):

    if not trades:

        return 0

    wins = sum(
        1
        for t in trades
        if t.pnl > 0
    )

    return (
        wins
        /
        len(trades)
    )


def profit_factor(trades):

    gross_profit = sum(

        t.pnl
        for t in trades
        if t.pnl > 0
    )

    gross_loss = abs(

        sum(

            t.pnl
            for t in trades
            if t.pnl < 0
        )
    )

    if gross_loss == 0:

        return float("inf")

    return (

        gross_profit
        /
        gross_loss
    )


def average_trade(trades):

    if not trades:

        return 0

    return (

        sum(

            t.pnl
            for t in trades
        )
        /
        len(trades)
    )


def _avg_win_loss(trades):

    wins = [

        t.pnl
        for t in trades
        if t.pnl > 0
    ]

    losses = [

        t.pnl
        for t in trades
        if t.pnl < 0
    ]

    avg_win = (

        sum(wins)
        /
        len(wins)
    ) if wins else 0

    avg_loss = (

        abs(sum(losses))
        /
        len(losses)
    ) if losses else 0

    return avg_win, avg_loss


def expectancy(trades):

    if not trades:

        return 0

    p = win_rate(trades)
    avg_win, avg_loss = _avg_win_loss(trades)

    return (

        p
        * avg_win
        -
        (1 - p)
        * avg_loss
    )


def payoff_ratio(trades):

    if not trades:

        return 0

    avg_win, avg_loss = _avg_win_loss(trades)

    if avg_loss == 0:

        return float("inf")

    return (

        avg_win
        /
        avg_loss
    )


def exposure(timestamps, qty_series):

    if not timestamps:

        return 0

    in_pos = sum(
        1
        for q in qty_series
        if q != 0
    )

    return (

        in_pos
        /
        len(qty_series)
    )


def sharpe_score(result):

    # Optimizer 默认 scorer
    # 吃 BacktestResult（新）或 dict（兼容）

    from .analytics import sharpe_ratio

    # 新接口：BacktestResult
    if hasattr(result, "sharpe"):

        return result.sharpe

    # 老接口：dict
    equity = (
        result["portfolio"]
        .equity_curve
    )

    return sharpe_ratio(
        equity
    )
