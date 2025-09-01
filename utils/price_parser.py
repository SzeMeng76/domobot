import logging
import re


try:
    from babel.numbers import NumberFormatError, parse_decimal

    BABEL_AVAILABLE = True
except ImportError:
    BABEL_AVAILABLE = False

from utils.country_data import SUPPORTED_COUNTRIES


logger = logging.getLogger(__name__)

# Currency symbol to code mapping
CURRENCY_SYMBOL_TO_CODE = {
    "$": "USD",
    "USD": "USD",
    "€": "EUR",
    "£": "GBP",
    "₩": "KRW",
    "₺": "TRY",
    "₽": "RUB",
    "₹": "INR",
    "₫": "VND",
    "฿": "THB",
    "₱": "PHP",
    "₦": "NGN",
    "₴": "UAH",
    "₲": "PYG",
    "₪": "ILS",
    "₡": "CRC",
    "₸": "KZT",
    "₮": "MNT",
    "៛": "KHR",
    "CFA": "XOF",
    "FCFA": "XAF",
    "S/": "PEN",
    "Rs": "LKR",
    "NZ$": "NZD",
    "A$": "AUD",
    "C$": "CAD",
    "HK$": "HKD",
    "NT$": "TWD",
    "R$": "BRL",
    "RM": "MYR",
    "Rp": "IDR",
    "Bs.": "VES",
    "лв": "BGN",
    "S$": "SGD",
    "kr": "NOK",
    "₼": "AZN",
    "￥": "CNY",
    "EGP": "EGP",
    "Ft": "HUF",
    "zł": "PLN",
    "Kč": "CZK",
    "лев": "BGN",
    "lei": "RON",
    "p.": "RUB",  # Russian ruble abbreviation used in Apple Support pages
}

# Currency multipliers for parsing
CURRENCY_MULTIPLIERS = {"ribu": 1000, "juta": 1000000, "k": 1000, "thousand": 1000}

# --- Pre-compiled Regex for performance ---
_currency_symbols = set(CURRENCY_SYMBOL_TO_CODE.keys())
_currency_symbols.add("¥")
for info in SUPPORTED_COUNTRIES.values():
    _currency_symbols.add(info["currency"])

_currency_patterns_escaped = [re.escape(cp) for cp in sorted(_currency_symbols, key=len, reverse=True)]
_currency_pattern_str = "|".join(_currency_patterns_escaped)

_PATTERN_CURRENCY_FIRST = re.compile(rf"^(?P<currency>{_currency_pattern_str})\s*(?P<amount>.*?)$")
_PATTERN_AMOUNT_FIRST = re.compile(rf"^(?P<amount>.*?)\s*(?P<currency>{_currency_pattern_str})$")
# --- End of Pre-compiled Regex ---


def detect_currency_from_context(currency_symbol: str, price_str: str, country_code: str | None = None) -> str:
    """Smartly detects currency, especially for ambiguous symbols like ¥ and $."""
    if currency_symbol == "¥":
        if country_code:
            if country_code in ["CN", "HK", "TW", "MO"]:
                return "CNY"
            if country_code == "JP":
                return "JPY"

        price_lower = price_str.lower()
        if any(keyword in price_lower for keyword in ["人民币", "元", "rmb"]):
            return "CNY"
        if any(keyword in price_lower for keyword in ["円", "yen", "jpy"]):
            return "JPY"

        numbers = re.findall(r"\d+", price_str)
        if numbers:
            max_num = max(int(num) for num in numbers)
            if max_num >= 500:
                return "JPY"
            if max_num <= 100:
                return "CNY"
        return "CNY"
    
    # Handle ambiguous $ symbol based on country context
    if currency_symbol == "$" and country_code:
        # Map country codes to their respective currencies that use $ symbol
        country_currency_map = {
            "TW": "TWD",  # Taiwan uses TWD, not USD
            "AU": "AUD",  # Australia Dollar
            "CA": "CAD",  # Canadian Dollar
            "HK": "HKD",  # Hong Kong Dollar
            "SG": "SGD",  # Singapore Dollar
            "NZ": "NZD",  # New Zealand Dollar
            # Add more countries as needed
        }
        if country_code in country_currency_map:
            return country_currency_map[country_code]

    return CURRENCY_SYMBOL_TO_CODE.get(currency_symbol, "USD")


def extract_currency_and_price(price_str: str, country_code: str | None = None) -> tuple[str, float | None]:
    """
    Extracts currency code and numerical price from a price string.
    Uses babel for robust parsing with a fallback to regex for safety.
    """
    if not price_str or price_str.lower() in ["未知", "free", "免费"]:
        return "USD", 0.0

    price_str = price_str.replace("\xa0", " ").strip()

    currency_part = None
    amount_part = price_str

    match = _PATTERN_CURRENCY_FIRST.match(price_str)
    if match and re.search(r"\d", match.group("amount")):
        currency_part = match.group("currency")
        amount_part = match.group("amount").strip()
    else:
        match = _PATTERN_AMOUNT_FIRST.match(price_str)
        if match and re.search(r"\d", match.group("amount")):
            currency_part = match.group("currency")
            amount_part = match.group("amount").strip()

    detected_currency_code = None
    if currency_part:
        detected_currency_code = detect_currency_from_context(currency_part, price_str, country_code)

    if not detected_currency_code and country_code:
        detected_currency_code = SUPPORTED_COUNTRIES.get(country_code, {}).get("currency", "USD")
    elif not detected_currency_code:
        detected_currency_code = "USD"

    price_value = None

    if BABEL_AVAILABLE:
        try:
            locale_str = SUPPORTED_COUNTRIES.get(country_code, {}).get("locale", "en_US")
            price_value = float(parse_decimal(amount_part.strip(), locale=locale_str))
        except (NumberFormatError, ValueError, TypeError) as e:
            logger.warning(
                f"Babel parsing failed for '{amount_part}' with locale '{locale_str}'. Error: {e}. Falling back."
            )
            price_value = None

    if price_value is None:
        multiplier = 1
        for key, value in sorted(CURRENCY_MULTIPLIERS.items(), key=lambda x: len(x[0]), reverse=True):
            if amount_part.lower().endswith(key):
                multiplier = value
                amount_part = amount_part[: -len(key)].strip()
                break

        if amount_part:
            amount_cleaned = re.sub(r"[^\d.,]", "", amount_part)
            # This is the line that had the syntax error. It is now fixed.
            decimal_match = re.search(r"[.,](\d{1,2})$", amount_cleaned)
            if decimal_match:
                decimal_part = decimal_match.group(1)
                integer_part = amount_cleaned[: decimal_match.start()].replace(",", "").replace(".", "")
                final_num_str = f"{integer_part}.{decimal_part}"
            else:
                final_num_str = amount_cleaned.replace(",", "").replace(".", "")

            try:
                price_value = float(final_num_str) * multiplier
            except ValueError:
                logger.error(f"Legacy regex parsing also failed for price: '{price_str}' -> '{final_num_str}'")
                price_value = None

    return detected_currency_code, price_value


def extract_price_value_from_country_info(price_str: str, country_info: dict) -> float:
    """Extracts numerical price from a price string based on country's number format."""
    try:
        price_str = price_str.replace("\xa0", " ").replace(country_info.get("symbol", ""), "").strip()
        price_str = price_str.replace(" ", "")
        if not price_str or not re.search(r"\d", price_str):
            return 0.0

        price_cleaned = re.sub(r"[^\d.,]", "", price_str)

        decimal_match = re.search(r"[.,](\d{1,3})$", price_cleaned)
        if decimal_match:
            decimal_part = decimal_match.group(1)
            if len(decimal_part) == 3:
                before_decimal = price_cleaned[: decimal_match.start()]
                if re.search(r"[.,]", before_decimal):
                    final_num_str = price_cleaned.replace(",", "").replace(".", "")
                else:
                    final_num_str = price_cleaned.replace(",", "").replace(".", "")
            else:
                integer_part = price_cleaned[: decimal_match.start()].replace(",", "").replace(".", "")
                final_num_str = f"{integer_part}.{decimal_part}"
        else:
            final_num_str = price_cleaned.replace(",", "").replace(".", "")

        return float(final_num_str)
    except Exception as e:
        logger.error(f"Price conversion failed: {e}, original price: {price_str}")
        return 0.0
