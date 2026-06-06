from __future__ import annotations

from .models import StockUniverseItem


SH_MAINBOARD_PREFIXES = ("600", "601", "603", "605")
SZ_MAINBOARD_PREFIXES = ("000", "001", "002", "003")


def is_mainboard_symbol(symbol: str) -> bool:
    normalized = symbol.strip().upper()
    if "." not in normalized:
        return False
    code, exchange = normalized.rsplit(".", 1)
    if len(code) != 6 or not code.isdigit():
        return False
    return (exchange == "SH" and code.startswith(SH_MAINBOARD_PREFIXES)) or (
        exchange == "SZ" and code.startswith(SZ_MAINBOARD_PREFIXES)
    )


def is_st_or_delisting_name(name: str) -> bool:
    normalized = name.strip().upper()
    return "ST" in normalized or "退" in normalized


def is_mainboard_eligible(item: StockUniverseItem) -> bool:
    return is_mainboard_symbol(item.symbol) and not item.is_st and not is_st_or_delisting_name(item.name)


def mainboard_symbol_sql(column: str) -> str:
    return (
        f"({column} ~ '^(600|601|603|605)[0-9]{{3}}[.]SH$' OR "
        f"{column} ~ '^(000|001|002|003)[0-9]{{3}}[.]SZ$')"
    )
