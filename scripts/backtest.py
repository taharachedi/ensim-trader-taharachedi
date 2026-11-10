"""Walk-forward backtest of my signal against the 3 baseline traders.

Replays the real market history tick by tick: at tick t the signal only sees prices
up to t (no look-ahead), the trade executes at the price of tick t+1, with the same
rules as the market (start 1000 money + 1000 units per product, can't sell what I
don't hold, can't spend money I don't have, budget guard). Baselines use the market's
own distributions (random_trader U(-1,1), random_buyer U(0,1), random_seller U(-1,0)),
averaged over 20 runs. Limitation: my own impact on prices is ignored.
Output: docs/data/backtest.json (performance + risk series for the dashboard).
"""
import json, math, os, random, sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import algorithm as a

PRODUCTS = ["A", "B", "C"]


def fast_signal(y):
    # Same model as algorithm.analyze(), vectorized with numpy for speed.
    y = np.array(y[-a.WINDOW:])
    n = len(y)
    if n < a.MIN_HISTORY:
        return 0.0
    t = np.arange(n)
    best = None
    for P in a.PERIODS:
        if P > n / 1.5:
            break
        X = np.column_stack([np.ones(n), t, np.sin(2 * np.pi * t / P), np.cos(2 * np.pi * t / P)])
        c = np.linalg.lstsq(X, y, rcond=None)[0]
        sse = float(((X @ c - y) ** 2).sum())
        if best is None or sse < best[1]:
            best = (c, sse, P)
    c, sse, P = best
    r2 = max(0.0, 1 - sse / float(((y - y.mean()) ** 2).sum()))
    h = max(1, int(P * a.HORIZON_FRAC))
    tf = n - 1 + h
    f = c[0] + c[1] * tf + c[2] * math.sin(2 * math.pi * tf / P) + c[3] * math.cos(2 * math.pi * tf / P)
    return max(-1.0, min(1.0, a.GAIN * (f - y[-1]) / y[-1] * r2))


def simulate(history, decide):
    h = {"money": 1000.0, **{p: 1000.0 for p in PRODUCTS}}
    values = []
    for t in range(len(history) - 1):
        for p in PRODUCTS:
            d = decide(t, p)
            price = history[t + 1][p]
            if d > 0:
                d = a.apply_budget_guard(d, h["money"], history[t][p])
                units = min(100 * d, h["money"] / price)
                h["money"] -= units * price
                h[p] += units
            elif d < 0:
                units = min(-100 * d, h[p])
                h["money"] += units * price
                h[p] -= units
        values.append(round(h["money"] + sum(h[p] * history[t + 1][p] for p in PRODUCTS), 2))
    return values


def stats(v):
    v = np.array(v)
    r = np.diff(v) / v[:-1]
    dd = v / np.maximum.accumulate(v) - 1
    return {"final": round(float(v[-1]), 2),
            "return_pct": round(100 * float(v[-1] / v[0] - 1), 1),
            "volatility_pct": round(100 * float(r.std()), 2),
            "max_drawdown_pct": round(100 * float(dd.min()), 1)}


def main():
    history = a.fetch_json(a.MARKET_URL)["history"]
    series = {"mine": simulate(history, lambda t, p: fast_signal([r[p] for r in history[:t + 1]]))}
    for name, lo, hi in [("random_trader", -1, 1), ("random_buyer", 0, 1), ("random_seller", -1, 0)]:
        runs = []
        for seed in range(20):
            rng = random.Random(seed)
            runs.append(simulate(history, lambda t, p: rng.uniform(lo, hi)))
        series[name] = [round(float(np.mean([r[i] for r in runs])), 2) for i in range(len(runs[0]))]
    series["hold"] = simulate(history, lambda t, p: 0.0)

    out = {"generated_ticks": len(history),
           "ticks": [r["t"] for r in history[1:]],
           "series": series,
           "stats": {k: stats(v) for k, v in series.items()}}
    os.makedirs("docs/data", exist_ok=True)
    with open("docs/data/backtest.json", "w") as f:
        json.dump(out, f, separators=(",", ":"))
    for k, s in out["stats"].items():
        print(f"{k:14s} final {s['final']:>10.2f}  return {s['return_pct']:>6.1f}%  "
              f"vol {s['volatility_pct']:.2f}%  max DD {s['max_drawdown_pct']:.1f}%")


if __name__ == "__main__":
    main()
