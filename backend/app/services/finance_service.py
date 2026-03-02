"""
Financial calculation engine for the Investment Processor.

All calculations mirror the JavaScript logic in frontend/js/finance.js
so that server-side validation produces identical results to real-time
client-side previews.
"""

from typing import Optional
import numpy as np
import numpy_financial as npf

from ..schemas.finance import FinancialModelInput, FinancialMetrics


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe(matrix: list, y: int, q: int, default: float = 0.0) -> float:
    """Safely access a 2D list by [year][quarter]."""
    try:
        return float(matrix[y][q]) if matrix[y][q] is not None else default
    except (IndexError, TypeError):
        return default


def build_churn_table(initial_churn: float, quarterly_increase: float, num_years: int) -> list:
    """
    Build quarterly churn table.
    Churn starts at `initial_churn` (e.g. -0.10) and improves
    (becomes less negative) by `quarterly_increase` each quarter.
    """
    table = []
    q_idx = 0
    for y in range(num_years):
        row = []
        for q in range(4):
            row.append(initial_churn + q_idx * quarterly_increase)
            q_idx += 1
        table.append(row)
    return table


def calc_revenue(model: FinancialModelInput) -> list:
    """Return revenue[year][quarter] in rubles."""
    ny = model.numYears
    conv = model.conversionRate / 100.0
    revenue = []

    for y in range(ny):
        row = []
        for q in range(4):
            users = _safe(model.users, y, q)
            paying = users * conv
            rev = 0.0

            if model.revenueModel == "subscription":
                price = _safe(model.prices, y, q)
                # Apply annual indexation starting from year 2
                index_factor = (
                    (1 + model.indexationRate / 100) ** y
                    if model.applyIndexation else 1.0
                )
                # price is per user per month; quarterly = price × 3
                freq_mult = 3.0 if model.subscriptionFreq == "monthly" else 0.25
                rev = paying * price * freq_mult * index_factor

            elif model.revenueModel == "transactional":
                tx = _safe(model.transactions, y, q)
                avg_check = _safe(model.avgChecks, y, q)
                rev = tx * avg_check

            elif model.revenueModel == "hybrid":
                sub_price = _safe(model.hybridSubscription, y, q)
                tx_rev = _safe(model.hybridTransactional, y, q)
                rev = paying * sub_price * 3.0 + tx_rev

            row.append(rev)
        revenue.append(row)
    return revenue


def calc_costs(model: FinancialModelInput, revenue: list) -> list:
    """Return total_costs[year][quarter] in rubles."""
    ny = model.numYears
    total_costs = []

    for y in range(ny):
        row = []
        for q in range(4):
            cost = 0.0
            rev_yq = revenue[y][q]
            users_yq = _safe(model.users, y, q)

            for c in model.costs:
                if c.mode == "percent_revenue":
                    cost += rev_yq * (c.param / 100.0)
                elif c.mode == "cac":
                    # New users acquired this quarter × CAC per user
                    cost += users_yq * c.param
                else:  # manual — annual value split by 4
                    annual_val = c.values[y] if y < len(c.values) else 0.0
                    cost += annual_val / 4.0

            row.append(cost)
        total_costs.append(row)
    return total_costs


def _irr_newton(cash_flows: list, guess: float = 0.1) -> Optional[float]:
    """IRR via Newton-Raphson. Returns None if not converged."""
    rate = guess
    for _ in range(1000):
        f = sum(cf / (1 + rate) ** t for t, cf in enumerate(cash_flows))
        df = sum(-t * cf / (1 + rate) ** (t + 1) for t, cf in enumerate(cash_flows))
        if abs(df) < 1e-12:
            break
        new_rate = rate - f / df
        if abs(new_rate - rate) < 1e-8:
            return new_rate
        rate = new_rate
    return rate if abs(f) < 1.0 else None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def calculate_metrics(model: FinancialModelInput) -> FinancialMetrics:
    ny = model.numYears
    churn_table = build_churn_table(
        model.churnRate / 100.0,
        model.quarterlyChurnIncrease,
        ny,
    )

    revenue = calc_revenue(model)
    costs = calc_costs(model, revenue)

    # Net quarterly cash flows
    ncf = [revenue[y][q] - costs[y][q] for y in range(ny) for q in range(4)]

    # Initial investment (zero period)
    initial = model.initialInvestment + model.nwc
    all_cf = [initial] + ncf

    # Discount rate
    annual_rate = (model.keyRate + model.riskPremium) / 100.0
    q_rate = (1 + annual_rate) ** 0.25 - 1

    # DCF series
    dcf_series = [cf / (1 + q_rate) ** (t + 1) for t, cf in enumerate(ncf)]

    # Cumulative DCF (includes initial investment)
    cum_dcf = []
    running = initial
    for d in dcf_series:
        running += d
        cum_dcf.append(running)

    npv = cum_dcf[-1] if cum_dcf else initial

    # DPP — first quarter where cumulative ≥ 0
    dpp = None
    for t, val in enumerate(cum_dcf):
        if val >= 0:
            dpp = round((t + 1) / 4, 1)
            break

    # PI
    pi = (1 + npv / abs(initial)) if initial < 0 else 0.0

    # IRR (annual)
    irr_annual = None
    try:
        irr_q = npf.irr(all_cf)
        if np.isfinite(irr_q):
            irr_annual = round(((1 + irr_q) ** 4 - 1) * 100, 1)
    except Exception:
        pass

    # CAC — weighted average from CAC-mode cost rows
    total_mkt_cost = 0.0
    total_new_users = 0.0
    for c in model.costs:
        if c.mode == "cac":
            for y in range(ny):
                for q in range(4):
                    u = _safe(model.users, y, q)
                    total_mkt_cost += u * c.param
                    total_new_users += u
    cac = total_mkt_cost / total_new_users if total_new_users > 0 else (
        next((c.param for c in model.costs if c.mode == "cac"), 0.0)
    )

    # ARPU — total revenue / total paying users
    conv = model.conversionRate / 100.0
    total_rev = sum(revenue[y][q] for y in range(ny) for q in range(4))
    total_paying = sum(_safe(model.users, y, q) * conv for y in range(ny) for q in range(4))
    arpu = total_rev / total_paying if total_paying > 0 else 0.0

    # Average churn
    all_churn = [churn_table[y][q] for y in range(ny) for q in range(4)]
    avg_churn = np.mean(all_churn) if all_churn else 0.0

    # Lifetime and LTV
    monthly_arpu = arpu / 3.0
    monthly_churn = abs(avg_churn) / 3.0
    lifetime_quarters = 1.0 / abs(avg_churn) if avg_churn != 0 else 0.0
    lifetime_years = round(lifetime_quarters / 4.0, 1)
    ltv = monthly_arpu / monthly_churn if monthly_churn > 0 else 0.0

    ltv_cac = ltv / cac if cac > 0 else 0.0

    return FinancialMetrics(
        discountRate=round(annual_rate * 100, 2),
        dcf=round(dcf_series[-1]) if dcf_series else 0,
        cumulativeDcf=round(cum_dcf[-1]) if cum_dcf else 0,
        npv=round(npv),
        dpp=dpp,
        pi=round(pi, 2),
        irr=irr_annual,
        cac=round(cac),
        arpu=round(arpu),
        avgChurn=round(avg_churn * 100, 2),
        lifetime=lifetime_years,
        ltv=round(ltv),
        ltvCac=round(ltv_cac, 2),
        churnTable=churn_table,
        revenue=revenue,
        costs=costs,
        cashFlows=ncf,
        dcfSeries=dcf_series,
        cumulativeDcfSeries=cum_dcf,
    )
