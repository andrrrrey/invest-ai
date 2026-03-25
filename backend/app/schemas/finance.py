from pydantic import BaseModel, Field
from typing import Optional, List


class CostRow(BaseModel):
    category: str
    mode: str  # percent_revenue | cac | manual
    param: float = 0.0
    values: List[float] = Field(default_factory=lambda: [0.0] * 5)


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
    conversionRate: float = 85.0
    churnRate: float = -10.0
    quarterlyChurnIncrease: float = 0.0015


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

    # Cost rows
    costs: List[CostRow] = Field(default_factory=list)

    # Discount
    keyRate: float = 10.0
    riskPremium: float = 3.0

    # Zero-period investment (negative values; initialInvestment kept for backward compat)
    initialInvestment: float = 0.0
    nwc: float = 0.0


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
    arpu: float
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
