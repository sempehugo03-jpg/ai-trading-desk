"""Research universe and provider symbol mapping for LAB V0.2."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Instrument:
    symbol: str
    provider_symbol: str
    description: str

UNIVERSE = (
    Instrument("XAUUSD", "xauusd", "Spot gold vs US dollar"),
    Instrument("NAS100", "usatechidxusd", "USA 100 Technical Index CFD"),
    Instrument("US500", "usa500idxusd", "USA 500 Index CFD"),
    Instrument("EURUSD", "eurusd", "Euro vs US dollar"),
    Instrument("GBPUSD", "gbpusd", "British pound vs US dollar"),
)

BY_SYMBOL = {item.symbol: item for item in UNIVERSE}
BY_PROVIDER = {item.provider_symbol: item for item in UNIVERSE}
