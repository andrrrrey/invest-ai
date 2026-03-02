from pydantic import BaseModel, Field
from typing import Optional, List, Any


class CostRow(BaseModel):
    category: str
    mode: str  # percent_revenue | cac | manual
    param: float = 0.0
    values: List[float] = Field(default_factory=lambda: [0.0] * 5)


class FinancialModelInput(BaseModel):
    # Revenue model
    revenueModel: str = "subscription"  # subscription | transactional | hybrid
    subscriptionFreq: str = "monthly"  # monthly | annual
    indexationRate: float = 10.0
    applyIndexation: bool = True
    numYears: int = 5

    # Subscription prices [year][quarter]
    prices: List[List[float]] = Field(default_factory=lambda: [[0]*4]*5)

    # Transactional
    transactions: List[List[float]] = Field(default_factory=lambda: [[0]*4]*5)
    avgChecks: List[List[float]] = Field(default_factory=lambda: [[0]*4]*5)

    # Hybrid
    hybridSubscription: List[List[float]] = Field(default_factory=lambda: [[0]*4]*5)
    hybridTransactional: List[List[float]] = Field(default_factory=lambda: [[0]*4]*5)

    # Users
    users: List[List[float]] = Field(default_factory=lambda: [[0]*4]*5)
    conversionRate: float = 85.0
    churnRate: float = -10.0
    quarterlyChurnIncrease: float = 0.0015

    # Costs
    costs: List[CostRow] = Field(default_factory=list)

    # Discount
    keyRate: float = 10.0
    riskPremium: float = 3.0

    # Zero period
    initialInvestment: float = 0.0
    nwc: float = 0.0


class FinancialMetrics(BaseModel):
    discountRate: float
    dcf: float
    cumulativeDcf: float
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
    churnTable: List[List[float]]
    revenue: List[List[float]]
    costs: List[List[float]]
    cashFlows: List[float]
    dcfSeries: List[float]
    cumulativeDcfSeries: List[float]
