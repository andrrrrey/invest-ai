from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Any


# ─────────────────────────────────────────────────────────────────────────────
# Sanitisation helpers
# ─────────────────────────────────────────────────────────────────────────────

def _f(v: Any) -> float:
    """Coerce a single value to float, treating None / '' / invalid as 0."""
    if v is None or v == '':
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _f1(v: Any) -> list:
    """Coerce a 1-D list to List[float]."""
    if not isinstance(v, list):
        return []
    return [_f(x) for x in v]


def _f2(v: Any) -> list:
    """Coerce a 2-D list to List[List[float]]."""
    if not isinstance(v, list):
        return []
    return [_f1(row) if isinstance(row, list) else [_f(row)] for row in v]


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────

class CostRow(BaseModel):
    category: str
    mode: str  # percent_revenue | percent_costs | cac | manual
    param: float = 0.0
    values: List[float] = Field(default_factory=lambda: [0.0] * 5)

    @model_validator(mode='before')
    @classmethod
    def _sanitize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get('param') in (None, ''):
            data['param'] = 0.0
        if 'values' in data:
            data['values'] = _f1(data['values'])
        return data


class ProductStream(BaseModel):
    """A single revenue stream (product) within a project."""
    name: str = "Продукт 1"
    revenueModel: str = "subscription"   # subscription | transactional | hybrid
    applyIndexation: bool = True
    indexationRate: float = 10.0

    # Subscription: price per paying user per quarter (₽), one value per year
    prices: List[float] = Field(default_factory=lambda: [0.0] * 5)

    # Transactional [year][quarter]
    transactions: List[List[float]] = Field(default_factory=lambda: [[0]*4]*5)
    avgChecks: List[List[float]] = Field(default_factory=lambda: [[0]*4]*5)

    # Hybrid — transactional revenue added on top of subscription
    hybridTransactional: List[List[float]] = Field(default_factory=lambda: [[0]*4]*5)

    # Users per quarter [year][quarter]
    users: List[List[float]] = Field(default_factory=lambda: [[0]*4]*5)
    # Users per month [year][month] — populated when granularity == 'month'
    usersMonthly: List[List[float]] = Field(default_factory=list)
    conversionRate: float = 85.0
    churnRate: float = -10.0
    quarterlyChurnIncrease: float = 0.0015

    @model_validator(mode='before')
    @classmethod
    def _sanitize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for scalar in ('indexationRate', 'conversionRate', 'churnRate',
                       'quarterlyChurnIncrease'):
            if data.get(scalar) in (None, ''):
                data[scalar] = 0.0
        for key1d in ('prices',):
            if key1d in data:
                data[key1d] = _f1(data[key1d])
        for key2d in ('transactions', 'avgChecks', 'hybridTransactional', 'users', 'usersMonthly'):
            if key2d in data:
                data[key2d] = _f2(data[key2d])
        return data


class FinancialModelInput(BaseModel):
    # Multi-product streams (new multi-product mode)
    products: List[ProductStream] = Field(default_factory=list)

    # Legacy single-product fields (kept for backward compatibility)
    revenueModel: str = "subscription"   # subscription | transactional | hybrid
    indexationRate: float = 10.0
    applyIndexation: bool = True
    numYears: int = 5

    # Subscription: price per paying user per quarter (₽), one value per year
    prices: List[float] = Field(default_factory=lambda: [0.0] * 5)

    # Transactional [year][quarter]
    transactions: List[List[float]] = Field(default_factory=lambda: [[0]*4]*5)
    avgChecks:    List[List[float]] = Field(default_factory=lambda: [[0]*4]*5)

    # Hybrid — transactional revenue added on top of subscription
    hybridTransactional: List[List[float]] = Field(default_factory=lambda: [[0]*4]*5)

    # Users per quarter [year][quarter]
    users: List[List[float]] = Field(default_factory=lambda: [[0]*4]*5)
    conversionRate: float = 85.0
    churnRate: float = -10.0           # e.g. -10 = −10%
    quarterlyChurnIncrease: float = 0.0015

    # Input granularity: 'quarter' | 'month' | 'half' | 'year'
    granularity: str = "quarter"

    # Users per month [year][month] — used when granularity == 'month'
    usersMonthly: List[List[float]] = Field(default_factory=list)

    # Cost rows
    costs: List[CostRow] = Field(default_factory=list)

    # Discount
    keyRate: float = 10.0
    riskPremium: float = 3.0

    # Zero-period investment (negative values; initialInvestment kept for backward compat)
    initialInvestment: float = 0.0
    nwc: float = 0.0
    # When True the user has manually overridden the auto-calculated NWC
    nwcManual: bool = False

    @model_validator(mode='before')
    @classmethod
    def _sanitize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for scalar in ('indexationRate', 'conversionRate', 'churnRate',
                       'quarterlyChurnIncrease', 'keyRate', 'riskPremium',
                       'initialInvestment', 'nwc'):
            if data.get(scalar) in (None, ''):
                data[scalar] = 0.0
        if data.get('numYears') in (None, ''):
            data['numYears'] = 5
        for key1d in ('prices',):
            if key1d in data:
                data[key1d] = _f1(data[key1d])
        for key2d in ('transactions', 'avgChecks', 'hybridTransactional', 'users', 'usersMonthly'):
            if key2d in data:
                data[key2d] = _f2(data[key2d])
        return data


class ProductMetrics(BaseModel):
    """Per-product intermediate calculation tables."""
    name: str
    paidWithoutChurn: List[List[float]]
    paidUsers: List[List[float]]
    newPaidUsers: List[List[float]]
    revenue: List[List[float]]
    annualRevenue: List[float]


class FinancialMetrics(BaseModel):
    # Discount
    discountRate: float
    discountFactors: List[float]
    discountedCF: List[float]
    cumulativeDcfSeries: List[float]

    # Key metrics
    npv: float
    dpp: Optional[float]
    pi: float
    irr: Optional[float]
    cac: float
    arpa: float
    avgChurn: float
    lifetime: float
    ltv: float
    ltvCac: float
    grossMargin: float
    nwcCalc: float

    # Intermediate tables (all [year][quarter] unless noted)
    churnTable: List[List[float]]
    paidWithoutChurn: List[List[float]]
    paidUsers: List[List[float]]
    newPaidUsers: List[List[float]]
    revenue: List[List[float]]

    # Annual aggregates (index 0 = year 0 / zero period for cashFlow)
    annualRevenue: List[float]
    totalCosts: List[float]
    netCashFlow: List[float]          # length = numYears + 1 (year 0 included)
    cacByYear: List[float]

    # Per-product breakdown (populated when model.products is non-empty)
    productMetrics: List[ProductMetrics] = Field(default_factory=list)
