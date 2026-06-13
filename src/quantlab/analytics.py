import numpy as np

def sharpe_ratio(
    equity_curve,

    annual_factor=252
):

    equity_curve = np.array(
        equity_curve
    )

    returns = (

        equity_curve[1:]

        /

        equity_curve[:-1]

        - 1
    )

    if len(returns) == 0:

        return 0

    std = returns.std()

    if std == 0:

        return 0

    return (

        returns.mean()

        /

        std

    ) * np.sqrt(
        annual_factor
    )


def max_drawdown(

    equity_curve

):

    equity_curve = np.array(
        equity_curve
    )

    peak = np.maximum.accumulate(
        equity_curve
    )

    drawdown = (
        equity_curve
        - peak
    ) / peak

    return drawdown.min()

def total_return(
equity_curve
):


    if len(equity_curve) == 0:

        return 0

    return (

        equity_curve[-1]

        /

        equity_curve[0]

        - 1
    )
