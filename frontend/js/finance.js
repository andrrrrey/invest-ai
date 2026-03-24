/**
 * finance.js — client-side financial calculation engine.
 *
 * Implements the spec formulas 1.1.x (user/revenue/cost tables) and
 * 1.2.x (key metrics) exactly.  Mirrors backend/app/services/finance_service.py.
 *
 * All calculations are pure functions — no network calls.
 * Alpine.js watches form data and calls Finance.calculate() on every change.
 */

const Finance = {

  /* ─── Safe accessors ──────────────────────────────────────────────────── */

  _s2(m, y, q, d = 0) {
    try { const v = m?.[y]?.[q]; return (v == null || v === '') ? d : +v || d; }
    catch { return d; }
  },

  _s1(a, i, d = 0) {
    try { const v = a?.[i]; return (v == null || v === '') ? d : +v || d; }
    catch { return d; }
  },

  /* ─── 1.1.2  Churn table ──────────────────────────────────────────────── */
  /**
   * churn[y][q] = initialChurn + (quarterIndex - 1) × quarterlyIncrease
   * quarterIndex is 1-based, so 0-based qIdx maps to (quarterIndex-1).
   */
  buildChurnTable(initialChurn, quarterlyIncrease, numYears) {
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

  /* ─── Price for a given year (with optional indexation) ─────────────────*/
  _price(form, y) {
    const manual = this._s1(form.prices, y);
    if (manual !== 0) return manual;                 // explicit override
    const base = this._s1(form.prices, 0);
    if (form.applyIndexation && y > 0)
      return base * Math.pow(1 + (+form.indexationRate || 0) / 100, y);
    return base;
  },

  /* ─── IRR via Newton-Raphson ─────────────────────────────────────────── */
  _irr(cfs, guess = 0.1) {
    let r = guess;
    for (let i = 0; i < 1000; i++) {
      let f = 0, df = 0;
      for (let t = 0; t < cfs.length; t++) {
        const d = Math.pow(1 + r, t);
        f  += cfs[t] / d;
        df -= t * cfs[t] / (d * (1 + r));
      }
      if (Math.abs(df) < 1e-12) break;
      const nr = r - f / df;
      if (Math.abs(nr - r) < 1e-8) { r = nr; break; }
      r = nr;
    }
    return r;
  },

  /* ─── Main entry point ───────────────────────────────────────────────── */
  calculate(form) {
    const ny       = +form.numYears || 5;
    const conv     = (+form.conversionRate || 0) / 100;
    const initChurn = (+form.churnRate || 0) / 100;
    const qInc     = +form.quarterlyChurnIncrease || 0;

    // 1.1.2 Churn table
    const churnTable = this.buildChurnTable(initChurn, qInc, ny);

    // 1.1.1 / 1.1.3 / 1.1.4  User tables
    const paidWithoutChurn = [];
    const paidUsers        = [];
    const newPaidUsers     = [];
    let prevPaid = null;

    for (let y = 0; y < ny; y++) {
      const pwcRow = [], puRow = [], npuRow = [];
      for (let q = 0; q < 4; q++) {
        // 1.1.1
        const total = this._s2(form.users, y, q);
        const pwc   = Math.round(total * conv);
        pwcRow.push(pwc);

        // 1.1.3
        const paid = Math.round(pwc * (1 + churnTable[y][q]));
        puRow.push(paid);

        // 1.1.4
        const npu = prevPaid === null ? paid : paid - prevPaid;
        npuRow.push(npu);
        prevPaid = paid;
      }
      paidWithoutChurn.push(pwcRow);
      paidUsers.push(puRow);
      newPaidUsers.push(npuRow);
    }

    // 1.1.5  Quarterly revenue
    const revenue = [];
    for (let y = 0; y < ny; y++) {
      const py  = this._price(form, y);
      const row = [];
      for (let q = 0; q < 4; q++) {
        let rev = 0;
        if (form.revenueModel === 'subscription') {
          rev = paidUsers[y][q] * py;
        } else if (form.revenueModel === 'transactional') {
          rev = this._s2(form.transactions, y, q) * this._s2(form.avgChecks, y, q);
        } else {  // hybrid
          rev = paidUsers[y][q] * py +
                this._s2(form.transactions, y, q) * this._s2(form.avgChecks, y, q);
        }
        row.push(rev);
      }
      revenue.push(row);
    }

    // 1.1.6  Annual revenue
    const annualRevenue = revenue.map(r => r.reduce((a, b) => a + b, 0));

    // 1.1.7 / 1.1.8  Annual costs (negative values)
    const annualCostsByCat = {};
    for (const c of form.costs) {
      const arr = [];
      for (let y = 0; y < ny; y++) {
        let val = 0;
        if (c.mode === 'percent_revenue') {
          val = -(annualRevenue[y] * (+c.param || 0) / 100);
        } else if (c.mode === 'cac') {
          const newU = newPaidUsers[y].reduce((a, b) => a + b, 0);
          val = -(newU * (+c.param || 0));
        } else {  // manual
          val = -(this._s1(c.values, y));
        }
        arr.push(val);
      }
      annualCostsByCat[c.category] = arr;
    }

    const totalCosts = Array.from({ length: ny }, (_, y) =>
      Object.values(annualCostsByCat).reduce((s, a) => s + a[y], 0)
    );

    // 1.1.9  Operating cash flows per year (year 1..N, independent of year 0)
    const operatingCF = Array.from({ length: ny }, (_, y) =>
      annualRevenue[y] + totalCosts[y]
    );

    // 1.1.10  Calculated NWC = sum of consecutive negative operating years from year 1
    //         until the first year where operating CF >= 0
    let nwcCalc = 0;
    for (let i = 0; i < operatingCF.length; i++) {
      if (operatingCF[i] < 0) nwcCalc += operatingCF[i];
      else break;
    }

    // Effective NWC: use manual override if explicitly provided, otherwise use auto-calculated
    const effectiveNwc = (form.nwcManual === true && form.nwc !== '' && form.nwc !== null && form.nwc !== undefined)
      ? (+form.nwc || 0)
      : nwcCalc;

    // Net cash flow array: year 0 = CAPEX + effective NWC
    const zeroPeriod  = (+form.initialInvestment || 0) + effectiveNwc;
    const netCashFlow = [zeroPeriod, ...operatingCF];

    // 1.2.1  Discount factors (annual)
    const discountRate = ((+form.keyRate || 0) + (+form.riskPremium || 0)) / 100;
    const discountFactors = Array.from({ length: ny + 1 }, (_, yr) =>
      1 / Math.pow(1 + discountRate, yr)
    );

    // 1.2.2  Discounted CF
    const discountedCF = netCashFlow.map((cf, yr) => cf * discountFactors[yr]);

    // 1.2.3  Cumulative discounted CF
    const cumDcf = [];
    let running = 0;
    for (const d of discountedCF) { running += d; cumDcf.push(running); }

    // 1.2.4  NPV
    const npv = cumDcf.at(-1) ?? 0;

    // 1.2.5  DPP (linear interpolation between years)
    let dpp = null;
    for (let yr = 1; yr < cumDcf.length; yr++) {
      if (cumDcf[yr] > 0 && cumDcf[yr - 1] < 0) {
        const span = cumDcf[yr] - cumDcf[yr - 1];
        dpp = +(yr - cumDcf[yr - 1] / span).toFixed(2);
        break;
      }
    }

    // 1.2.6  PI = SUM(discountedCF[1..n]) / |NWC|
    const nwcAbs     = Math.abs(zeroPeriod) || 1;
    const sumDisc1N  = discountedCF.slice(1).reduce((a, b) => a + b, 0);
    const pi         = +(sumDisc1N / nwcAbs).toFixed(2);

    // 1.2.7  IRR (annual)
    let irrAnnual = null;
    try {
      const v = this._irr(netCashFlow);
      if (isFinite(v) && !isNaN(v)) irrAnnual = +(v * 100).toFixed(1);
    } catch (_) { /* ignore */ }

    // 1.2.8  CAC per year = |marketingCost[y]| / newPaidUsers[y]
    const mktKey = Object.keys(annualCostsByCat).find(k =>
      k.toLowerCase().includes('маркетинг') || k.toLowerCase().includes('marketing')
    );
    const cacByYear = Array.from({ length: ny }, (_, y) => {
      const newU = newPaidUsers[y].reduce((a, b) => a + b, 0);
      if (mktKey && newU > 0) return Math.abs(annualCostsByCat[mktKey][y]) / newU;
      return +form.costs.find(c => c.mode === 'cac')?.param || 0;
    });
    const avgCac = cacByYear.length ? cacByYear.reduce((a, b) => a + b, 0) / cacByYear.length : 0;

    // 1.2.9  ARPU = AVERAGE(revenue[y][q] / paidUsers[y][q])
    const arpuVals = [];
    for (let y = 0; y < ny; y++)
      for (let q = 0; q < 4; q++)
        if (paidUsers[y][q] > 0) arpuVals.push(revenue[y][q] / paidUsers[y][q]);
    const arpu = arpuVals.length ? arpuVals.reduce((a, b) => a + b, 0) / arpuVals.length : 0;

    // 1.2.10  Average quarterly churn
    const allChurn  = churnTable.flat();
    const avgChurn  = allChurn.reduce((a, b) => a + b, 0) / (allChurn.length || 1);

    // 1.2.11  Lifetime = 1 / |avgChurn| / 4  (quarters to years, always positive)
    //         avgChurn is negative (e.g. -0.10 = 10% churn), so we take absolute value
    const lifetimeYears = avgChurn !== 0 ? 1 / Math.abs(avgChurn) / 4 : ny; // fallback to project horizon if no churn

    // 1.2.12  LTV = ARPU × lifetimeYears × grossMargin
    let grossMargin = 1;
    for (const c of form.costs) {
      if (c.mode === 'percent_revenue' &&
          (c.category.toLowerCase().includes('cogs') ||
           c.category.toLowerCase().includes('support'))) {
        grossMargin -= (+c.param || 0) / 100;
      }
    }
    grossMargin = Math.max(0, grossMargin);
    const ltv = arpu * lifetimeYears * grossMargin;

    // 1.2.13  LTV/CAC
    const ltvCac = avgCac > 0 ? +(ltv / avgCac).toFixed(2) : 0;

    // DCF = sum of discounted operating cash flows (years 1..n, excluding year 0)
    const dcf = Math.round(discountedCF.slice(1).reduce((a, b) => a + b, 0));

    return {
      /* key metrics */
      discountRate:   +(discountRate * 100).toFixed(2),
      dcf,
      npv:            Math.round(npv),
      dpp,
      pi,
      irr:            irrAnnual,
      cac:            Math.round(avgCac),
      arpu:           Math.round(arpu),
      avgChurn:       +(avgChurn * 100).toFixed(2),
      lifetime:       +lifetimeYears.toFixed(1),
      ltv:            Math.round(ltv),
      ltvCac,
      grossMargin:    +(grossMargin * 100).toFixed(1),
      nwcCalc:        Math.round(nwcCalc),
      /* series */
      discountFactors,
      discountedCF,
      cumulativeDcfSeries: cumDcf,
      /* tables */
      churnTable,
      paidWithoutChurn,
      paidUsers,
      newPaidUsers,
      revenue,
      annualRevenue,
      totalCosts,
      netCashFlow,
      annualCostsByCat,
      cacByYear,
    };
  },

  /* ─── Formatting helpers ────────────────────────────────────────────── */

  fmt(n, suffix = '₽') {
    if (n == null || isNaN(n)) return '—';
    return new Intl.NumberFormat('ru-RU').format(Math.round(n)) + (suffix ? '\u00a0' + suffix : '');
  },

  fmtShort(n) {
    if (n == null || isNaN(n)) return '—';
    const abs = Math.abs(n);
    if (abs >= 1_000_000) return (n / 1_000_000).toFixed(2) + '\u00a0млн\u00a0₽';
    if (abs >= 1_000)     return (n / 1_000).toFixed(0)     + '\u00a0тыс\u00a0₽';
    return this.fmt(n);
  },

  fmtPct(n, dec = 2) {
    if (n == null || isNaN(n)) return '—';
    return n.toFixed(dec) + '%';
  },
};
