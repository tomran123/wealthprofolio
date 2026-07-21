import enum


class OwnerType(str, enum.Enum):
    INDIVIDUAL = "individual"
    FAMILY_ENTITY = "family_entity"


class InstitutionType(str, enum.Enum):
    BANK = "bank"
    BROKER = "broker"
    OTHER = "other"


class AccountType(str, enum.Enum):
    CASH = "cash"
    BROKERAGE = "brokerage"
    MIXED = "mixed"


class AssetClass(str, enum.Enum):
    CASH = "cash"
    EQUITY = "equity"
    ETF = "etf"
    BOND = "bond"
    FUND = "fund"
    REAL_ESTATE = "real_estate"
    PRIVATE_EQUITY = "private_equity"
    COMPANY_EQUITY = "company_equity"
    GOLD = "gold"
    CRYPTO = "crypto"
    CUSTOM = "custom"
    LIABILITY = "liability"


class MarketRegion(str, enum.Enum):
    US = "US"
    HK = "HK"
    CN = "CN"
    CRYPTO = "CRYPTO"
    COMMODITY = "COMMODITY"
    OTHER = "OTHER"


class PriceSourceType(str, enum.Enum):
    MARKET = "market"
    MANUAL = "manual"
    FX_DERIVED = "fx_derived"
    FIXED_PRINCIPAL = "fixed_principal"


class QuoteStatus(str, enum.Enum):
    REALTIME = "realtime"
    DELAYED = "delayed"
    CLOSE = "close"
    MANUAL = "manual"
    FIXED = "fixed"


class HoldingSource(str, enum.Enum):
    MANUAL = "manual"
    IMPORT = "import"
    AGENT = "agent"
    SCREENSHOT = "screenshot"


class ImportBatchStatus(str, enum.Enum):
    PENDING = "pending"
    COMMITTED = "committed"
    FAILED = "failed"
