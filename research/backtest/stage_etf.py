"""Cash-account replay for whole-lot domestic equity ETFs on unadjusted daily bars.

One net order at most per open. Close decisions survive a suspension until replaced.
No splits, financing, cash interest, automatic dividend reinvestment or forced exit.
"""

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
TICK = Decimal("0.001")
ZERO = Decimal(0)
LOT = 100


def _number(value):
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError(f"non-finite input: {value!r}")
    return number


def _fraction(value):
    result = _number(value)
    if not 0 <= result <= 1:
        raise ValueError(f"target outside [0,1]: {value}")
    return result


def _date(value):
    return date.fromisoformat(str(value)).isoformat()


def _money(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _weight(shares, mark, nav):
    return float(shares * mark / nav) if nav else 0.0


def _order(signal_date, goal, reason, episode_id):
    return dict(
        signal_date=signal_date,
        target=float(_fraction(goal)),
        reason=reason,
        episode_id=episode_id,
        status="pending",
        resolved_date=None,
    )


def _close_orders(actions, start, end):
    groups = defaultdict(list)
    for action in actions:
        day = _date(action["date"])
        if not start <= day <= end:
            raise ValueError(f"signal outside replay period: {day}")
        order = _order(day, action["target"], action["reason"], action["episode_id"])
        groups[day].append((action.get("sequence"), order))
    schedule, ledger = {}, []
    for day, group in sorted(groups.items()):
        targets = {order["target"] for _, order in group}
        sequences = [seq for seq, _ in group]
        if len(targets) > 1 and (None in sequences or len(set(sequences)) != len(sequences)):
            raise ValueError(f"conflicting close signals on {day} need distinct sequence values")
        # Identical instructions are idempotent, independent of input ordering.
        group.sort(
            key=lambda row: (
                row[0] is not None,
                row[0],
                str(row[1]["episode_id"]),
                str(row[1]["reason"]),
            )
        )
        winner = group[-1][1]
        schedule[day] = winner
        for _, order in group[:-1]:
            status = "duplicate" if order["target"] == winner["target"] else "superseded"
            order.update(status=status, resolved_date=day)
        ledger.extend(order for _, order in group)
    return schedule, ledger


def _dividend_events(corporate_actions):
    events = defaultdict(list)
    entitlements = []
    for i, row in enumerate(corporate_actions):
        if row["type"] != "cash":
            raise ValueError(f"unsupported corporate action {row['type']!r}; cash dividends only")
        rec, ex, pay = (_date(row[key]) for key in ("record_date", "ex_date", "pay_date"))
        amount = _number(row["cash_per_share"])
        if not rec <= ex <= pay or amount < 0:
            raise ValueError("expected record_date <= ex_date <= pay_date and nonnegative dividend")
        entitlements.append(
            {
                "id": row.get("id", i),
                "record_date": rec,
                "ex_date": ex,
                "pay_date": pay,
                "cash_per_share": float(amount),
                "record_shares": None,
                "amount": None,
                "status": "pending",
            }
        )
        for day, event in ((rec, "record"), (ex, "accrue"), (pay, "pay")):
            events[day].append((i, event, amount))
    return events, entitlements


class _Account:
    def __init__(self, cash, rate, minimum, slippage):
        self.cash = cash
        self.shares = 0
        self.receivable = ZERO
        self.fees = ZERO
        self.rate = rate
        self.minimum = minimum
        self.slippage = slippage

    def nav(self, mark):
        return _money(self.cash + self.receivable + self.shares * mark)

    def _amounts(self, price, shares):
        gross = _money(price * shares)
        fee = _money(max(self.minimum, self.rate * gross)) if shares else ZERO
        return gross, fee

    def _affordable_lots(self, price, lots):
        low, high = 0, lots
        while low < high:
            mid = (low + high + 1) // 2
            if sum(self._amounts(price, mid * LOT)) <= self.cash:
                low = mid
            else:
                high = mid - 1
        return low

    def fill(self, order, day, opened, sellable):
        desired = int(self.nav(opened) * _number(order["target"]) / opened / LOT) * LOT
        delta = desired - self.shares
        if not delta:
            order.update(status="no_lot_change", resolved_date=day)
            return None
        buy = delta > 0
        price = (opened * (1 + self.slippage if buy else 1 - self.slippage)).quantize(
            TICK, rounding=ROUND_HALF_UP
        )
        if price <= 0:
            raise ValueError("slippage implies a nonpositive fill price")
        if buy:
            qty = self._affordable_lots(price, delta // LOT) * LOT
        else:
            qty = min(sellable, -delta)
        gross, fee = self._amounts(price, qty)
        flow = -gross - fee if buy else gross - fee
        if not qty or self.cash + flow < 0:
            order.update(status="insufficient_cash", resolved_date=day)
            return None
        self.cash += flow
        self.fees += fee
        self.shares += qty if buy else -qty
        order.update(status="filled", resolved_date=day)
        return {
            "date": day,
            **{k: order[k] for k in ("signal_date", "episode_id", "reason", "target")},
            "side": "buy" if buy else "sell",
            "shares": qty,
            "price": float(price),
            "gross": float(gross),
            "fee": float(fee),
            "net_cash": float(flow),
            "cash_after": float(self.cash),
            "shares_after": self.shares,
        }

    def dividend_event(self, dividend, event, rate):
        if event == "record":
            dividend["record_shares"] = self.shares
            dividend["amount"] = float(_money(rate * self.shares))
            dividend["status"] = "registered"
        elif event == "accrue":
            self.receivable += _money(rate * dividend["record_shares"])
            dividend["status"] = "receivable"
        else:
            amount = _money(rate * dividend["record_shares"])
            self.receivable -= amount
            self.cash += amount
            dividend["status"] = "paid"


def simulate(
    bars, actions, corporate_actions, *, cash, target, commission_rate, minimum_fee, slippage_bps=0
):
    """Return daily, trades, orders and dividends as JSON-safe records.

    Initial target applies at the first tradable open. Later target changes apply
    once at the next tradable open. Same-close conflicts require explicit sequence.
    commission_rate is a fraction per side and minimum_fee is in CNY per fill.
    Fill assumption is the published unadjusted open plus signed slippage, with
    ample depth. Optional volume (or volume_lots) must be positive to fill. An absent open cannot
    fill. Ex-date receivables are marked at face value; a payment dated after the
    record day is assumed available before that session's open. Record dates use
    closing holdings. Cash is kept after distributions until a target change.
    Supply raw prices and all relevant cash actions; splits require a different
    position ledger and are explicitly rejected.
    """
    cash, rate, minimum, bps = map(_number, (cash, commission_rate, minimum_fee, slippage_bps))
    if cash <= 0 or cash != _money(cash) or rate < 0 or minimum < 0 or not 0 <= bps < 10000:
        raise ValueError("invalid starting cash, commission or slippage")
    prices = {}
    for bar in bars:
        day = _date(bar["date"])
        if day in prices:
            raise ValueError(f"duplicate ETF bar on {day}")
        prices[day] = bar
    if not prices:
        raise ValueError("no ETF bars")
    start, end = min(prices), max(prices)
    schedule, orders = _close_orders(actions, start, end)
    events, dividends = _dividend_events(corporate_actions)
    account = _Account(cash, rate, minimum, bps / 10000)
    pending = _order(None, target, "initial", None)
    orders.insert(0, pending)
    active_target, last_close = None, None
    days = sorted(set(prices) | set(schedule) | {d for d in events if d <= end})
    daily, trades = [], []
    for day in days:
        # Rights registered before the account's inception belong to zero units.
        closing_events = []
        for idx, event, per_share in events.get(day, []):
            dividend = dividends[idx]
            if day == dividend["record_date"]:
                closing_events.append((dividend, event, per_share))
            else:
                account.dividend_event(dividend, event, per_share)

        row = None
        if day in prices:
            bar = prices[day]
            opened = _number(bar["open"]) if bar.get("open") is not None else None
            closed = _number(bar["close"]) if bar.get("close") is not None else None
            if any(p is not None and p <= 0 for p in (opened, closed)):
                raise ValueError(f"nonpositive ETF price on {day}")
            volume_key = "volume" if "volume" in bar else "volume_lots"
            volume = _number(bar[volume_key]) if bar.get(volume_key) is not None else None
            if volume is not None and volume < 0:
                raise ValueError(f"negative ETF volume on {day}")
            tradable = opened is not None and (volume_key not in bar or (volume or ZERO) > 0)
            if closed is None and (tradable or last_close is None and account.shares):
                raise ValueError(f"missing closing mark on {day}")
            if closed is None and account.shares and any(e == "accrue" for _, e, _ in events[day]):
                raise ValueError(f"missing ex-date closing mark on {day}")
            sellable = account.shares  # domestic equity ETF shares bought today unlock next day
            open_nav = account.nav(opened) if opened is not None else None
            if pending is not None and tradable:
                trade = account.fill(pending, day, opened, sellable)
                if trade is not None:
                    trades.append(trade)
                    if trade["side"] == "sell":
                        sellable -= trade["shares"]
                active_target, pending = pending["target"], None
            open_nav_after = account.nav(opened) if opened is not None else None
            row = {
                "date": day,
                "open": float(opened) if opened is not None else None,
                "open_nav_before": float(open_nav) if open_nav is not None else None,
                "open_nav_after": float(open_nav_after) if open_nav_after is not None else None,
                "open_weight": _weight(account.shares, opened, open_nav_after) if opened else None,
                "tradable": tradable,
                "sellable_shares_close": sellable,
            }
            if closed is not None:
                last_close = closed
            row.update(
                close=float(closed) if closed is not None else None,
                mark=float(last_close) if last_close is not None else None,
                carried_mark=closed is None,
            )

        for dividend, event, per_share in closing_events:
            account.dividend_event(dividend, event, per_share)
        if row is not None:
            mark = last_close or ZERO
            nav = account.nav(mark)
            row.update(
                shares=account.shares,
                cash=float(account.cash),
                receivable=float(account.receivable),
                nav=float(nav),
                position_weight=_weight(account.shares, mark, nav),
                fees=float(account.fees),
            )
            daily.append(row)
        if day in schedule:
            action = schedule[day]
            if pending is not None and action["target"] == pending["target"]:
                action.update(status="duplicate", resolved_date=day)
                continue
            if pending is not None:
                pending.update(status="superseded", resolved_date=day)
                pending = None
            if action["target"] == active_target:
                action.update(status="duplicate", resolved_date=day)
            else:
                pending = action
    return {"daily": daily, "trades": trades, "orders": orders, "dividends": dividends}
