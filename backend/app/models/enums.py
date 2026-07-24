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


class TransactionType(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    FX_EXCHANGE = "fx_exchange"
    DIVIDEND = "dividend"
    INTEREST = "interest"
    FEE = "fee"
    MANUAL_ADJUSTMENT = "manual_adjustment"
    VALUATION_UPDATE = "valuation_update"


class TransactionSource(str, enum.Enum):
    MANUAL = "manual"
    IMPORT = "import"
    AGENT = "agent"
    SCREENSHOT = "screenshot"


class LLMRole(str, enum.Enum):
    CHAT = "chat"
    VISION = "vision"
