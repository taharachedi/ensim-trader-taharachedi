import json, math, os, time
import requests

# Feeds from the organizer (ENSIM Trade Center).
MARKET_URL = "https://raw.githubusercontent.com/exofri/ensim-trade-center/refs/heads/main/docs/data/market.json"
HOLDINGS_URL = "https://raw.githubusercontent.com/exofri/ensim-trade-center/refs/heads/main/traders/taharachedi/holdings.json"
LEADERBOARD_URL = "https://raw.githubusercontent.com/exofri/ensim-trade-center/refs/heads/main/docs/data/leaderboard.json"

MIN_MONEY_RESERVE = 50  # never let a buy signal spend below this much money

# --- My signal: "cycle forecast" ------------------------------------------------
# Observation: each product's price follows a regular cycle + a slow drift
# (A ~48 ticks, B ~96 ticks, C ~24 ticks on the first 328 ticks).
# Idea: fit  price ~ a + b*t + c*sin(2*pi*t/P) + d*cos(2*pi*t/P)  on the observed
# history, search the period P that fits best, then forecast the price H ticks ahead
# (H = 30 % of the period, i.e. "where is the cycle going next").
#   forecast above current price -> buy ; below -> sell ; size ~ expected move.
# The signal is shrunk when the fit is poor (low R^2): no confident cycle, small bets.
MIN_HISTORY = 36        # below this, not enough data to see a cycle -> hold
PERIODS = range(12, 130)
HORIZON_FRAC = 0.30     # forecast horizon as a fraction of the detected period
GAIN = 10               # +10 % expected move -> full signal (1.0)
WINDOW = 500            # use at most the last 500 ticks


def fetch_json(url):
    resp = requests.get(url, proxies={"http": None, "https": None}, timeout=(10, 20))
    resp.raise_for_status()
    return resp.json()


def _lstsq4(t, y, P):
    # Ordinary least squares for 4 parameters (normal equations, no numpy needed).
    rows = [[1.0, ti, math.sin(2 * math.pi * ti / P), math.cos(2 * math.pi * ti / P)] for ti in t]
    A = [[sum(r[i] * r[j] for r in rows) for j in range(4)] for i in range(4)]
    b = [sum(r[i] * yi for r, yi in zip(rows, y)) for i in range(4)]
    # Gaussian elimination
    for i in range(4):
        piv = max(range(i, 4), key=lambda k: abs(A[k][i]))
        A[i], A[piv], b[i], b[piv] = A[piv], A[i], b[piv], b[i]
        if abs(A[i][i]) < 1e-12:
            return None, float("inf")
        for k in range(i + 1, 4):
            f = A[k][i] / A[i][i]
            A[k] = [a - f * c for a, c in zip(A[k], A[i])]
            b[k] -= f * b[i]
    c = [0.0] * 4
    for i in reversed(range(4)):
        c[i] = (b[i] - sum(A[i][j] * c[j] for j in range(i + 1, 4))) / A[i][i]
    sse = sum((sum(ci * ri for ci, ri in zip(c, r)) - yi) ** 2 for r, yi in zip(rows, y))
    return c, sse


def analyze(prices):
    """Fit the cycle and return all indicators (also used by the dashboard)."""
    y = prices[-WINDOW:]
    n = len(y)
    if n < MIN_HISTORY:
        return {"signal": 0.0, "reason": f"only {n} ticks of history (< {MIN_HISTORY}): hold"}
    t = list(range(n))
    best = None
    for P in PERIODS:
        if P > n / 1.5:
            break
        c, sse = _lstsq4(t, y, P)
        if c is not None and (best is None or sse < best[1]):
            best = (c, sse, P)
    c, sse, P = best
    mean = sum(y) / n
    sst = sum((v - mean) ** 2 for v in y) or 1e-9
    r2 = max(0.0, 1 - sse / sst)
    h = max(1, int(P * HORIZON_FRAC))
    tf = n - 1 + h
    forecast = c[0] + c[1] * tf + c[2] * math.sin(2 * math.pi * tf / P) + c[3] * math.cos(2 * math.pi * tf / P)
    expected_move = (forecast - y[-1]) / y[-1]
    signal = max(-1.0, min(1.0, GAIN * expected_move * r2))
    direction = "buy" if signal > 0.05 else "sell" if signal < -0.05 else "hold"
    return {
        "signal": round(signal, 3),
        "period": P,
        "r2": round(r2, 3),
        "price": round(y[-1], 4),
        "forecast": round(forecast, 4),
        "horizon": h,
        "expected_move_pct": round(100 * expected_move, 2),
        "reason": f"{direction}: cycle {P} ticks (R2 {r2:.2f}) forecasts {100*expected_move:+.1f}% in {h} ticks",
    }


def compute_signal(prices):
    return analyze(prices)["signal"]


def apply_budget_guard(raw_signal, money, price, reserve=MIN_MONEY_RESERVE):
    # Provided by the manual, unchanged.
    if raw_signal <= 0:
        return raw_signal
    if money <= reserve:
        return 0.0
    max_affordable_units = (money - reserve) / price
    desired_units = 100 * raw_signal
    if desired_units <= max_affordable_units:
        return raw_signal
    return round(max_affordable_units / 100, 3)


def main():
    market = fetch_json(MARKET_URL)
    try:
        holdings = fetch_json(HOLDINGS_URL)
        registered = True
    except Exception:
        # Not registered yet by the organizer: same defaults as the market's own code.
        holdings = {"money": 1000.0, "products": {p: 1000.0 for p in market["products"]}}
        registered = False

    try:
        # Snapshot of the public leaderboard (total value of every trader incl. the 3
        # baselines): the organizer only publishes the current value, so logging it at
        # every run is what builds my "performance vs baselines over time" chart.
        leaderboard = {r["id"]: r["total_value"] for r in fetch_json(LEADERBOARD_URL)["leaderboard"]}
    except Exception:
        leaderboard = {}

    products = market["products"]
    history = market["history"]
    decision, details = {}, {}
    for p in products:
        prices = [row[p] for row in history]
        info = analyze(prices)
        current_price = prices[-1] if prices else 0
        final = round(apply_budget_guard(info["signal"], holdings["money"], current_price), 3)
        decision[p] = final
        details[p] = {**info, "final": final}

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    decision["updated_at"] = now
    with open("decision.json", "w") as f:
        json.dump(decision, f, indent=2)

    # Decision log for the dashboard (one entry per run, appended).
    log_path = "docs/data/decision_log.json"
    log = {"entries": []}
    if os.path.exists(log_path):
        with open(log_path) as f:
            log = json.load(f)
    log["entries"].append({
        "run_at": now,
        "market_tick": history[-1]["t"] if history else None,
        "registered": registered,
        "money": round(holdings["money"], 2),
        "holdings": {p: round(holdings["products"][p], 2) for p in products},
        "decision": {p: decision[p] for p in products},
        "details": details,
        "leaderboard": leaderboard,
    })
    log["entries"] = log["entries"][-500:]
    os.makedirs("docs/data", exist_ok=True)
    with open(log_path, "w") as f:
        json.dump(log, f, indent=2)

    print(f"Registered: {registered}")
    print(f"Wrote decision.json: {decision}")
    for p in products:
        print(f"  {p}: {details[p]['reason']}")


if __name__ == "__main__":
    main()
