"""
Financial calculation engine for the Investment Processor.

Formulas implement the specification exactly:
  1.1.x — user / revenue / cost tables
  1.2.x — key metrics (NPV, IRR, DPP, PI, CAC, ARPA, LTV, …)

All calculations mirror finance.js so server-side validation gives
identical results to real-time client-side previews.
"""

from typing import Optional
import numpy as np
import numpy_financial as npf

from ..schemas.finance import FinancialModelInput, FinancialMetrics, ProductStream, ProductMetrics


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe2d(matrix: list, y: int, q: int, default: float = 0.0) -> float:
    try:
        v = matrix[y][q]
        return float(v) if v is not None else default
    except (IndexError, TypeError):
        return default


def _safe1d(arr: list, i: int, default: float = 0.0) -> float:
    try:
        v = arr[i]
        return float(v) if v is not None else default
    except (IndexError, TypeError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# Per-product calculation helper
# ─────────────────────────────────────────────────────────────────────────────

def _calculate_product(p: ProductStream, ny: int, granularity: str = "quarter") -> ProductMetrics:
    """Calculate user tables and revenue for a single product stream."""
    conv = p.conversionRate / 100.0
    init_churn = p.churnRate / 100.0
    q_inc = p.quarterlyChurnIncrease

    def price_for_year(y: int) -> float:
        manual = _safe1d(p.prices, y)
        if manual != 0:
            return manual
        base = _safe1d(p.prices, 0)
        if p.applyIndexation and y > 0:
            return base * (1 + p.indexationRate / 100) ** y
        return base

    if granularity == "month" and p.usersMonthly:
        # Monthly path: calculate at monthly granularity, aggregate to quarterly output
        m_churn_base = init_churn / 3
        m_churn_inc  = q_inc / 3

        paid_without_churn = [[0.0] * 4 for _ in range(ny)]
        paid_users         = [[0.0] * 4 for _ in range(ny)]
        new_paid_users     = [[0.0] * 4 for _ in range(ny)]
        revenue            = [[0.0] * 4 for _ in range(ny)]
        prev_pwc: Optional[float] = None
        m_idx = 0

        for y in range(ny):
            py = price_for_year(y)
            for m in range(12):
                q = m // 3
                total = _safe1d(p.usersMonthly[y] if y < len(p.usersMonthly) else [], m)
                pwc   = round(total * conv)
                m_churn = m_churn_base + m_idx * m_churn_inc
                paid  = round(pwc * (1 + m_churn))
                npu   = pwc if prev_pwc is None else pwc - prev_pwc

                if p.revenueModel == "subscription":
                    rev = paid * py
                elif p.revenueModel == "transactional":
                    rev = (_safe2d(p.transactions, y, q) * _safe2d(p.avgChecks, y, q)) / 3
                else:  # hybrid
                    rev = paid * py + _safe2d(p.hybridTransactional, y, q) / 3

                paid_without_churn[y][q] += pwc
                paid_users[y][q]         += paid
                new_paid_users[y][q]     += max(0.0, float(npu))
                revenue[y][q]            += rev
                prev_pwc = float(pwc)
                m_idx += 1

        annual_revenue = [sum(revenue[y]) for y in range(ny)]
        return ProductMetrics(
            name=p.name,
            paidWithoutChurn=paid_without_churn,
            paidUsers=paid_users,
            newPaidUsers=new_paid_users,
            revenue=revenue,
            annualRevenue=annual_revenue,
        )

    # Quarterly path (default)
    churn_table: list[list[float]] = []
    q_idx = 0
    for y in range(ny):
        row = []
        for q in range(4):
            row.append(init_churn + q_idx * q_inc)
            q_idx += 1
        churn_table.append(row)

    paid_without_churn = []
    paid_users         = []
    new_paid_users     = []
    revenue            = []
    prev_pwc: Optional[int] = None

    for y in range(ny):
        pwc_row, pu_row, npu_row, rev_row = [], [], [], []
        py = price_for_year(y)
        for q in range(4):
            total = _safe2d(p.users, y, q)
            pwc = round(total * conv)
            pwc_row.append(pwc)
            paid = round(pwc * (1 + churn_table[y][q]))
            pu_row.append(paid)
            npu = pwc if prev_pwc is None else pwc - prev_pwc
            npu_row.append(npu)
            prev_pwc = pwc
            if p.revenueModel == "subscription":
                rev = paid * py
            elif p.revenueModel == "transactional":
                rev = _safe2d(p.transactions, y, q) * _safe2d(p.avgChecks, y, q)
            else:  # hybrid
                rev = paid * py + _safe2d(p.hybridTransactional, y, q)
            rev_row.append(rev)
        paid_without_churn.append(pwc_row)
        paid_users.append(pu_row)
        new_paid_users.append(npu_row)
        revenue.append(rev_row)

    annual_revenue = [sum(revenue[y]) for y in range(ny)]
    return ProductMetrics(
        name=p.name,
        paidWithoutChurn=paid_without_churn,
        paidUsers=paid_users,
        newPaidUsers=new_paid_users,
        revenue=revenue,
        annualRevenue=annual_revenue,
    )


def _sum_tables(tables: list[list[list[float]]], ny: int) -> list[list[float]]:
    """Element-wise sum of multiple [year][quarter] tables."""
    result = [[0.0] * 4 for _ in range(ny)]
    for tbl in tables:
        for y in range(ny):
            for q in range(4):
                result[y][q] += _safe2d(tbl, y, q)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Main calculation
# ─────────────────────────────────────────────────────────────────────────────

def calculate_metrics(model: FinancialModelInput) -> FinancialMetrics:
    ny   = model.numYears

    # ── Multi-product vs single-product path ─────────────────────────────────
    product_metrics_list: list[ProductMetrics] = []

    granularity = model.granularity or "quarter"

    if model.products:
        # Multi-product: calculate each stream and sum tables
        for p in model.products:
            product_metrics_list.append(_calculate_product(p, ny, granularity))

        paid_without_churn = _sum_tables(
            [pm.paidWithoutChurn for pm in product_metrics_list], ny)
        paid_users = _sum_tables(
            [pm.paidUsers for pm in product_metrics_list], ny)
        new_paid_users = _sum_tables(
            [pm.newPaidUsers for pm in product_metrics_list], ny)
        revenue = _sum_tables(
            [pm.revenue for pm in product_metrics_list], ny)

        # Churn table: use first product's churn (representative for metrics display)
        p0 = model.products[0]
        init_churn = p0.churnRate / 100.0
        q_inc = p0.quarterlyChurnIncrease
        churn_table: list[list[float]] = []
        q_idx = 0
        for y in range(ny):
            row = []
            for q in range(4):
                row.append(init_churn + q_idx * q_inc)
                q_idx += 1
            churn_table.append(row)
    else:
        # Single-product legacy path
        conv = model.conversionRate / 100.0
        init_churn = model.churnRate / 100.0
        q_inc      = model.quarterlyChurnIncrease

        # ── 1.1.2  Churn table ──────────────────────────────────────────────────
        churn_table = []
        q_idx = 0
        for y in range(ny):
            row = []
            for q in range(4):
                row.append(init_churn + q_idx * q_inc)
                q_idx += 1
            churn_table.append(row)

        if granularity == "month" and model.usersMonthly:
            # Monthly path: compute at monthly granularity, aggregate to quarterly
            m_churn_base = init_churn / 3
            m_churn_inc  = q_inc / 3
            paid_without_churn = [[0.0] * 4 for _ in range(ny)]
            paid_users         = [[0.0] * 4 for _ in range(ny)]
            new_paid_users     = [[0.0] * 4 for _ in range(ny)]
            prev_pwc: Optional[float] = None
            m_idx = 0
            for y in range(ny):
                for m in range(12):
                    q = m // 3
                    total = _safe1d(
                        model.usersMonthly[y] if y < len(model.usersMonthly) else [], m)
                    pwc   = round(total * conv)
                    m_churn = m_churn_base + m_idx * m_churn_inc
                    paid  = round(pwc * (1 + m_churn))
                    npu   = pwc if prev_pwc is None else pwc - prev_pwc
                    paid_without_churn[y][q] += pwc
                    paid_users[y][q]         += paid
                    new_paid_users[y][q]     += max(0.0, float(npu))
                    prev_pwc = float(pwc)
                    m_idx += 1
        else:
            # ── 1.1.1 / 1.1.3 / 1.1.4  User tables ─────────────────────────────
            paid_without_churn = []
            paid_users         = []
            new_paid_users     = []
            prev_pwc: Optional[int] = None

            for y in range(ny):
                pwc_row, pu_row, npu_row = [], [], []
                for q in range(4):
                    total = _safe2d(model.users, y, q)
                    pwc = round(total * conv)
                    pwc_row.append(pwc)
                    paid = round(pwc * (1 + churn_table[y][q]))
                    pu_row.append(paid)
                    npu = pwc if prev_pwc is None else pwc - prev_pwc
                    npu_row.append(npu)
                    prev_pwc = pwc
                paid_without_churn.append(pwc_row)
                paid_users.append(pu_row)
                new_paid_users.append(npu_row)

        # ── Price per year (with optional indexation) ────────────────────────────
        def price_for_year(y: int) -> float:
            manual = _safe1d(model.prices, y)
            if manual != 0:
                return manual
            base = _safe1d(model.prices, 0)
            if model.applyIndexation and y > 0:
                return base * (1 + model.indexationRate / 100) ** y
            return base

        # ── 1.1.5  Quarterly revenue ─────────────────────────────────────────────
        revenue = []
        for y in range(ny):
            py = price_for_year(y)
            row = []
            for q in range(4):
                if model.revenueModel == "subscription":
                    rev = paid_users[y][q] * py
                elif model.revenueModel == "transactional":
                    rev = _safe2d(model.transactions, y, q) * _safe2d(model.avgChecks, y, q)
                else:  # hybrid
                    rev = paid_users[y][q] * py + _safe2d(model.hybridTransactional, y, q)
                row.append(rev)
            revenue.append(row)

    # ── 1.1.6  Annual revenue ────────────────────────────────────────────────
    annual_revenue = [sum(revenue[y]) for y in range(ny)]

    # ── 1.1.7 / 1.1.8  Annual costs (negative values = expenses) ───────────
    # Two-pass: percent_costs depends on all other categories computed first.
    annual_costs_by_cat: dict[str, list[float]] = {}
    for c in model.costs:
        if c.mode == "percent_costs":
            continue
        cat_costs = []
        for y in range(ny):
            if c.mode == "manual":
                val = -(_safe1d(c.values, y))
            elif c.mode == "percent_revenue":
                val = -(annual_revenue[y] * c.param / 100.0)
            elif c.mode == "cac":
                new_users_y = sum(new_paid_users[y])
                val = -(new_users_y * c.param)
            else:
                val = 0.0
            cat_costs.append(val)
        annual_costs_by_cat[c.category] = cat_costs
    for c in model.costs:
        if c.mode != "percent_costs":
            continue
        cat_costs = []
        for y in range(ny):
            dev_total = sum(
                abs(annual_costs_by_cat[k][y])
                for k in annual_costs_by_cat
                if k != c.category
                and "маркетинг" not in k.lower()
                and "marketing" not in k.lower()
                and "support" not in k.lower()
                and "поддержк" not in k.lower()
            )
            cat_costs.append(-(dev_total * c.param / 100.0))
        annual_costs_by_cat[c.category] = cat_costs

    total_costs = [
        sum(annual_costs_by_cat[cat][y] for cat in annual_costs_by_cat)
        for y in range(ny)
    ]

    # ── 1.1.9  Operating cash flows per year (years 1..N) ───────────────────
    operating_cf = [annual_revenue[y] + total_costs[y] for y in range(ny)]

    # ── 1.1.10  Calculated NWC = sum of consecutive negative operating years
    #            from year 1 until the first positive year (mirrors finance.js)
    nwc_calc = 0.0
    for v in operating_cf:
        if v < 0:
            nwc_calc += v
        else:
            break

    # ── 1.1.9 (continued)  Net cash flow ────────────────────────────────────
    # Year 0: use manual NWC override when nwcManual=True, otherwise auto nwcCalc.
    # initialInvestment is kept only for legacy projects that pre-date the
    # NWC-based UI; new projects always go through the nwcCalc path.
    if model.nwcManual and model.nwc != 0.0:
        zero_period = model.nwc
    else:
        zero_period = nwc_calc
    net_cash_flow = [zero_period] + operating_cf

    # ── 1.2.1  Discount factors (annual) ────────────────────────────────────
    discount_rate = (model.keyRate + model.riskPremium) / 100.0
    discount_factors = [1.0 / (1 + discount_rate) ** yr for yr in range(ny + 1)]

    # ── 1.2.2  Discounted cash flow ──────────────────────────────────────────
    discounted_cf = [net_cash_flow[yr] * discount_factors[yr] for yr in range(ny + 1)]

    # ── 1.2.3  Cumulative discounted CF ─────────────────────────────────────
    cum_dcf: list[float] = []
    running = 0.0
    for d in discounted_cf:
        running += d
        cum_dcf.append(running)

    # ── 1.2.4  NPV ───────────────────────────────────────────────────────────
    npv = cum_dcf[-1] if cum_dcf else 0.0

    # ── 1.2.5  DPP (linear interpolation between years) ─────────────────────
    dpp: Optional[float] = None
    for yr in range(1, len(cum_dcf)):
        if cum_dcf[yr] > 0 and cum_dcf[yr - 1] < 0:
            span = cum_dcf[yr] - cum_dcf[yr - 1]
            dpp = round(yr - cum_dcf[yr] / span, 2) if span != 0 else float(yr)
            break

    # ── 1.2.6  PI ────────────────────────────────────────────────────────────
    nwc_abs = abs(zero_period) if zero_period != 0 else 1.0
    sum_disc_1_n = sum(discounted_cf[1:])
    pi = round(sum_disc_1_n / nwc_abs, 2)

    # ── 1.2.7  IRR (annual cash flows) ───────────────────────────────────────
    irr_annual: Optional[float] = None
    try:
        irr_val = npf.irr(net_cash_flow)
        if np.isfinite(irr_val):
            irr_annual = round(float(irr_val) * 100, 1)
    except Exception:
        pass

    # ── 1.2.8  CAC = total_marketing_cost / total_new_paid_users (1.1.4) ────
    mkt_cat = next(
        (cat for cat in annual_costs_by_cat
         if "маркетинг" in cat.lower() or "marketing" in cat.lower()),
        None,
    )

    cac_by_year: list[float] = []
    for y in range(ny):
        new_u_y = sum(max(0.0, float(v)) for v in new_paid_users[y])
        if mkt_cat and new_u_y > 0:
            cac_by_year.append(abs(annual_costs_by_cat[mkt_cat][y]) / new_u_y)
        else:
            cac_fixed = next((c.param for c in model.costs if c.mode == "cac"), 0.0)
            cac_by_year.append(cac_fixed)

    total_new_clients = sum(max(0.0, float(v)) for row in new_paid_users for v in row)
    total_mkt_cost = (
        sum(abs(annual_costs_by_cat[mkt_cat][y]) for y in range(ny))
        if mkt_cat else 0.0
    )
    if total_new_clients > 0:
        avg_cac = total_mkt_cost / total_new_clients
    else:
        avg_cac = next((c.param for c in model.costs if c.mode == "cac"), 0.0)

    # ── 1.2.9  ARPA (average quarterly revenue per paying account) ──────────
    arpa_vals = [
        revenue[y][q] / paid_users[y][q]
        for y in range(ny)
        for q in range(4)
        if paid_users[y][q] > 0
    ]
    arpa = float(np.mean(arpa_vals)) if arpa_vals else 0.0

    # ── 1.2.10  Average quarterly churn ─────────────────────────────────────
    all_churn = [churn_table[y][q] for y in range(ny) for q in range(4)]
    avg_churn = float(np.mean(all_churn)) if all_churn else 0.0

    # ── 1.2.11  Lifetime = 1 / |avgChurn|  (in months; always positive)
    #           avg_churn is negative quarterly rate (e.g. -0.10 = 10% churn per quarter)
    lifetime_months = (1.0 / abs(avg_churn)) if avg_churn != 0 else float(ny * 12)

    # ── 1.2.12  LTV = ARPA × lifetime_quarters × grossMargin ───────────────
    # lifetime_months == 1/|churn_q| which equals lifetime in quarters numerically
    # grossMargin = 1 - COGS% - Support%
    gross_margin = 1.0
    for c in model.costs:
        if c.mode == "percent_revenue" and (
            "cogs" in c.category.lower() or "support" in c.category.lower()
        ):
            gross_margin -= c.param / 100.0
    gross_margin = max(0.0, gross_margin)
    ltv = arpa * lifetime_months * gross_margin

    # ── 1.2.13  LTV/CAC ─────────────────────────────────────────────────────
    ltv_cac = round(ltv / avg_cac, 2) if avg_cac > 0 else 0.0

    return FinancialMetrics(
        discountRate=round(discount_rate * 100, 2),
        discountFactors=discount_factors,
        discountedCF=discounted_cf,
        cumulativeDcfSeries=cum_dcf,
        npv=round(npv),
        dpp=dpp,
        pi=pi,
        irr=irr_annual,
        cac=round(avg_cac),
        arpa=round(arpa),
        avgChurn=round(avg_churn * 100, 2),
        lifetime=round(lifetime_months, 1),
        ltv=round(ltv),
        ltvCac=ltv_cac,
        grossMargin=round(gross_margin * 100, 1),
        nwcCalc=round(nwc_calc),
        churnTable=churn_table,
        paidWithoutChurn=paid_without_churn,
        paidUsers=paid_users,
        newPaidUsers=new_paid_users,
        revenue=revenue,
        annualRevenue=annual_revenue,
        totalCosts=total_costs,
        netCashFlow=net_cash_flow,
        cacByYear=cac_by_year,
        productMetrics=product_metrics_list,
    )
