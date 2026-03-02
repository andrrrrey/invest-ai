/**
 * finance.js — client-side financial calculation engine.
 *
 * Mirrors the logic in backend/app/services/finance_service.py exactly.
 * Calculations run in real time (no network round-trip needed).
 *
 * Usage:
 *   const metrics = Finance.calculate(formData);
 */

const Finance = {

  /* ------------------------------------------------------------------ */
  /* Helpers                                                              */
  /* ------------------------------------------------------------------ */

  _safe(matrix, y, q, def_ = 0) {
    try {
      const v = matrix?.[y]?.[q];
      return (v === undefined || v === null || v === '') ? def_ : parseFloat(v) || def_;
    } catch { return def_; }
  },

  _safeArr(arr, i, def_ = 0) {
    const v = arr?.[i];
    return (v === undefined || v === null || v === '') ? def_ : parseFloat(v) || def_;
  },

  /* ------------------------------------------------------------------ */
  /* Churn table                                                          */
  /* ------------------------------------------------------------------ */

  buildChurnTable(initialChurn, quarterlyIncrease, numYears) {
    /**
     * initialChurn: negative, e.g. -0.10 for 10% churn
     * quarterlyIncrease: 0.0015 — churn improves each quarter
     */
    const table = [];
    let qIdx = 0;
    for (let y = 0; y < numYears; y++) {
      const row = [];
      for (let q = 0; q < 4; q++) {
        row.push(initialChurn + qIdx * quarterlyIncrease);
        qIdx++;
      }
      table.push(row);
    }
    return table;
  },

  /* ------------------------------------------------------------------ */
  /* Revenue                                                              */
  /* ------------------------------------------------------------------ */

  calcRevenue(form) {
    const ny = form.numYears;
    const conv = form.conversionRate / 100;
    const revenue = [];

    for (let y = 0; y < ny; y++) {
      const row = [];
      for (let q = 0; q < 4; q++) {
        const users = this._safe(form.users, y, q);
        const paying = users * conv;
        let rev = 0;

        if (form.revenueModel === 'subscription') {
          const price = this._safe(form.prices, y, q);
          const indexFactor = form.applyIndexation
            ? Math.pow(1 + form.indexationRate / 100, y)
            : 1;
          // price per user per month; quarterly revenue = price × 3 months
          const freqMult = form.subscriptionFreq === 'monthly' ? 3 : 0.25;
          rev = paying * price * freqMult * indexFactor;

        } else if (form.revenueModel === 'transactional') {
          const tx = this._safe(form.transactions, y, q);
          const avgCheck = this._safe(form.avgChecks, y, q);
          rev = tx * avgCheck;

        } else if (form.revenueModel === 'hybrid') {
          const subPrice = this._safe(form.hybridSubscription, y, q);
          const txRev = this._safe(form.hybridTransactional, y, q);
          rev = paying * subPrice * 3 + txRev;
        }

        row.push(rev);
      }
      revenue.push(row);
    }
    return revenue;
  },

  /* ------------------------------------------------------------------ */
  /* Costs                                                                */
  /* ------------------------------------------------------------------ */

  calcCosts(form, revenue) {
    const ny = form.numYears;
    const conv = form.conversionRate / 100;
    const totalCosts = [];

    for (let y = 0; y < ny; y++) {
      const row = [];
      for (let q = 0; q < 4; q++) {
        let cost = 0;
        const rev = revenue[y][q];
        const users = this._safe(form.users, y, q);

        for (const c of form.costs) {
          if (c.mode === 'percent_revenue') {
            cost += rev * (parseFloat(c.param) / 100);
          } else if (c.mode === 'cac') {
            cost += users * parseFloat(c.param || 0);
          } else {
            // manual: annual value / 4
            const annualVal = this._safeArr(c.values, y);
            cost += annualVal / 4;
          }
        }
        row.push(cost);
      }
      totalCosts.push(row);
    }
    return totalCosts;
  },

  /* ------------------------------------------------------------------ */
  /* IRR via Newton-Raphson                                               */
  /* ------------------------------------------------------------------ */

  irr(cashFlows, guess = 0.1) {
    let rate = guess;
    for (let i = 0; i < 1000; i++) {
      let f = 0, df = 0;
      for (let t = 0; t < cashFlows.length; t++) {
        const disc = Math.pow(1 + rate, t);
        f  += cashFlows[t] / disc;
        df -= t * cashFlows[t] / (disc * (1 + rate));
      }
      if (Math.abs(df) < 1e-12) break;
      const newRate = rate - f / df;
      if (Math.abs(newRate - rate) < 1e-8) { rate = newRate; break; }
      rate = newRate;
    }
    return rate;
  },

  /* ------------------------------------------------------------------ */
  /* Main entry: calculate all metrics                                    */
  /* ------------------------------------------------------------------ */

  calculate(form) {
    const ny = form.numYears;
    const churnTable = this.buildChurnTable(
      form.churnRate / 100,
      parseFloat(form.quarterlyChurnIncrease),
      ny,
    );

    const revenue  = this.calcRevenue(form);
    const costs    = this.calcCosts(form, revenue);

    // Net quarterly cash flows
    const ncf = [];
    for (let y = 0; y < ny; y++)
      for (let q = 0; q < 4; q++)
        ncf.push(revenue[y][q] - costs[y][q]);

    // Initial investment (zero period)
    const initial = (parseFloat(form.initialInvestment) || 0)
                  + (parseFloat(form.nwc) || 0);
    const allCf = [initial, ...ncf];

    // Discount rate
    const annualRate = ((parseFloat(form.keyRate) || 0)
                      + (parseFloat(form.riskPremium) || 0)) / 100;
    const qRate = Math.pow(1 + annualRate, 0.25) - 1;

    // DCF series
    const dcfSeries = ncf.map((cf, t) => cf / Math.pow(1 + qRate, t + 1));

    // Cumulative DCF
    const cumDcf = [];
    let running = initial;
    for (const d of dcfSeries) {
      running += d;
      cumDcf.push(running);
    }

    const npv = cumDcf.length ? cumDcf[cumDcf.length - 1] : initial;

    // DPP — first quarter where cumulative ≥ 0
    let dpp = null;
    for (let t = 0; t < cumDcf.length; t++) {
      if (cumDcf[t] >= 0) { dpp = +((t + 1) / 4).toFixed(1); break; }
    }

    // PI
    const pi = initial < 0 ? +(1 + npv / Math.abs(initial)).toFixed(2) : 0;

    // IRR (annualised)
    let irrAnnual = null;
    try {
      const irrQ = this.irr(allCf);
      if (isFinite(irrQ) && !isNaN(irrQ)) {
        irrAnnual = +((Math.pow(1 + irrQ, 4) - 1) * 100).toFixed(1);
      }
    } catch (e) { /* ignore */ }

    // CAC
    let totalMktCost = 0, totalNewUsers = 0;
    for (const c of form.costs) {
      if (c.mode === 'cac') {
        for (let y = 0; y < ny; y++)
          for (let q = 0; q < 4; q++) {
            const u = this._safe(form.users, y, q);
            totalMktCost  += u * parseFloat(c.param || 0);
            totalNewUsers += u;
          }
      }
    }
    const cac = totalNewUsers > 0
      ? totalMktCost / totalNewUsers
      : (form.costs.find(c => c.mode === 'cac')?.param || 0);

    // ARPU
    const conv = form.conversionRate / 100;
    let totalRev = 0, totalPaying = 0;
    for (let y = 0; y < ny; y++)
      for (let q = 0; q < 4; q++) {
        totalRev    += revenue[y][q];
        totalPaying += this._safe(form.users, y, q) * conv;
      }
    const arpu = totalPaying > 0 ? totalRev / totalPaying : 0;

    // Average churn
    let churnSum = 0, churnCnt = 0;
    for (let y = 0; y < ny; y++)
      for (let q = 0; q < 4; q++) {
        churnSum += churnTable[y][q];
        churnCnt++;
      }
    const avgChurn = churnCnt > 0 ? churnSum / churnCnt : 0; // negative

    // Lifetime & LTV
    const monthlyArpu  = arpu / 3;
    const monthlyChurn = Math.abs(avgChurn) / 3;
    const lifetimeQtrs = avgChurn !== 0 ? 1 / Math.abs(avgChurn) : 0;
    const lifetimeYrs  = +(lifetimeQtrs / 4).toFixed(1);
    const ltv          = monthlyChurn > 0 ? monthlyArpu / monthlyChurn : 0;
    const ltvCac       = cac > 0 ? +(ltv / cac).toFixed(2) : 0;

    return {
      discountRate: +(annualRate * 100).toFixed(2),
      dcf:          Math.round(dcfSeries.at(-1) ?? 0),
      cumulativeDcf:Math.round(cumDcf.at(-1) ?? 0),
      npv:          Math.round(npv),
      dpp,
      pi,
      irr:          irrAnnual,
      cac:          Math.round(cac),
      arpu:         Math.round(arpu),
      avgChurn:     +(avgChurn * 100).toFixed(2),
      lifetime:     lifetimeYrs,
      ltv:          Math.round(ltv),
      ltvCac,
      // raw series (for future charts)
      churnTable,
      revenue,
      costs,
      cashFlows: ncf,
      dcfSeries,
      cumulativeDcfSeries: cumDcf,
    };
  },

  /* ------------------------------------------------------------------ */
  /* Formatting helpers                                                   */
  /* ------------------------------------------------------------------ */

  fmt(n, suffix = '₽') {
    if (n == null || isNaN(n)) return '—';
    return new Intl.NumberFormat('ru-RU').format(Math.round(n)) + (suffix ? ' ' + suffix : '');
  },

  fmtPct(n) {
    if (n == null || isNaN(n)) return '—';
    return n.toFixed(2) + '%';
  },

  fmtShort(n) {
    if (n == null || isNaN(n)) return '—';
    const abs = Math.abs(n);
    if (abs >= 1_000_000) return (n / 1_000_000).toFixed(1) + ' млн ₽';
    if (abs >= 1_000)     return (n / 1_000).toFixed(0) + ' тыс ₽';
    return this.fmt(n);
  },
};
