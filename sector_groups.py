"""Finer sector groups for sector-relative checks (display / research only).

The market-watch sector "Banking/Financial Services" lumps 60 stocks - banks, NBFCs, insurers, exchanges/brokers, realty and others - into one
bucket, so its average says little about any of them (16 Oct 2026: GODREJPROP, HDFCLIFE and BSE all sat in it). `fine_sector()` splits it;
every other sector is returned unchanged.
"""

from __future__ import annotations

BANK = {"AUBANK", "AXISBANK", "BANDHANBNK", "BANKBARODA", "BANKINDIA", "CANBK", "FEDERALBNK", "HDFCBANK", "ICICIBANK", "IDFCFIRSTB", "INDIANB",
        "INDUSINDBK", "KOTAKBANK", "MAHABANK", "PNB", "RBLBANK", "SBIN", "UJJIVANSFB", "UNIONBANK", "YESBANK"}
NBFC = {"ABCAPITAL", "BAJAJFINSV", "BAJAJHLDNG", "BAJFINANCE", "CHOLAFIN", "IREDA", "IRFC", "JIOFIN", "LICHSGFIN", "LTF", "MANAPPURAM", "MUTHOOTFIN",
        "PFC", "PNBHOUSING", "RECLTD", "SBICARD", "SHRIRAMFIN"}
INSURANCE = {"HDFCLIFE", "ICICIGI", "ICICIPRULI", "LICI", "MFSL", "SBILIFE"}
CAPITAL_MARKETS = {"360ONE", "ANANDRATHI", "ANGELONE", "BSE", "CDSL", "HDFCAMC", "MCX", "NAM-INDIA"}
REALTY = {"DLF", "GODREJPROP", "LODHA", "OBEROIRLTY", "PHOENIXLTD", "PRESTIGE"}

_FINE = {}
for _name, _members in (("Banks", BANK), ("NBFC/Finance", NBFC), ("Insurance", INSURANCE), ("Capital Markets", CAPITAL_MARKETS), ("Realty", REALTY)):
    for _s in _members:
        _FINE[_s] = _name


def fine_sector(symbol: str, sector: str) -> str:
    """The finer group for a stock in the broad financial bucket; the original sector for everything else."""
    return _FINE.get(symbol, sector) if sector.startswith("Banking/Financial") else sector


def fine_map(sectors: dict[str, str]) -> dict[str, str]:
    return {s: fine_sector(s, k) for s, k in sectors.items()}
