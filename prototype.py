
import json
import time
import sqlite3
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

# =========================================================
# SETTINGS
# =========================================================

NTFY_TOPIC    = "my-contract-alerts"
MIN_AWARD_USD = 5_000_000
CHECK_MINUTES = 60
DATABASE      = "contracts.db"

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log"),
    ]
)
log = logging.getLogger(__name__)

# =========================================================
# COMPANY DATABASE
# All major publicly traded defence/tech contractors
# Format: "name fragment": {ticker, exchange, currency}
# =========================================================

COMPANIES = {
    # ── USA ──────────────────────────────────────────────
    "Booz Allen":          {"ticker": "BAH",    "exchange": "NYSE",   "currency": "USD"},
    "Leidos":              {"ticker": "LDOS",   "exchange": "NYSE",   "currency": "USD"},
    "SAIC":                {"ticker": "SAIC",   "exchange": "NYSE",   "currency": "USD"},
    "Parsons":             {"ticker": "PSN",    "exchange": "NYSE",   "currency": "USD"},
    "Palantir":            {"ticker": "PLTR",   "exchange": "NYSE",   "currency": "USD"},
    "Accenture":           {"ticker": "ACN",    "exchange": "NYSE",   "currency": "USD"},
    "Raytheon":            {"ticker": "RTX",    "exchange": "NYSE",   "currency": "USD"},
    "Northrop":            {"ticker": "NOC",    "exchange": "NYSE",   "currency": "USD"},
    "Lockheed":            {"ticker": "LMT",    "exchange": "NYSE",   "currency": "USD"},
    "L3Harris":            {"ticker": "LHX",    "exchange": "NYSE",   "currency": "USD"},
    "General Dynamics":    {"ticker": "GD",     "exchange": "NYSE",   "currency": "USD"},
    "Textron":             {"ticker": "TXT",    "exchange": "NYSE",   "currency": "USD"},
    "TransDigm":           {"ticker": "TDG",    "exchange": "NYSE",   "currency": "USD"},
    "Mercury Systems":     {"ticker": "MRCY",   "exchange": "NASDAQ", "currency": "USD"},
    "Kratos":              {"ticker": "KTOS",   "exchange": "NASDAQ", "currency": "USD"},
    "Leonardo DRS":        {"ticker": "DRS",    "exchange": "NASDAQ", "currency": "USD"},
    "Curtiss-Wright":      {"ticker": "CW",     "exchange": "NYSE",   "currency": "USD"},
    "KBR":                 {"ticker": "KBR",    "exchange": "NYSE",   "currency": "USD"},
    "Fluor":               {"ticker": "FLR",    "exchange": "NYSE",   "currency": "USD"},
    "Jacobs":              {"ticker": "J",      "exchange": "NYSE",   "currency": "USD"},
    "Tetra Tech":          {"ticker": "TTEK",   "exchange": "NASDAQ", "currency": "USD"},
    "AECOM":               {"ticker": "ACM",    "exchange": "NYSE",   "currency": "USD"},
    "Maximus":             {"ticker": "MMS",    "exchange": "NYSE",   "currency": "USD"},
    "ICF":                 {"ticker": "ICFI",   "exchange": "NASDAQ", "currency": "USD"},
    "CACI":                {"ticker": "CACI",   "exchange": "NYSE",   "currency": "USD"},
    "ManTech":             {"ticker": "MANT",   "exchange": "NASDAQ", "currency": "USD"},
    "Heico":               {"ticker": "HEI",    "exchange": "NYSE",   "currency": "USD"},
    "BWX Technologies":    {"ticker": "BWXT",   "exchange": "NYSE",   "currency": "USD"},
    "Rocket Lab":          {"ticker": "RKLB",   "exchange": "NASDAQ", "currency": "USD"},
    "Aerojet":             {"ticker": "AJRD",   "exchange": "NYSE",   "currency": "USD"},
    "Spirit AeroSystems":  {"ticker": "SPR",    "exchange": "NYSE",   "currency": "USD"},
    "Triumph Group":       {"ticker": "TGI",    "exchange": "NYSE",   "currency": "USD"},
    "Kaman":               {"ticker": "KAMN",   "exchange": "NYSE",   "currency": "USD"},
    "VSE Corporation":     {"ticker": "VSEC",   "exchange": "NASDAQ", "currency": "USD"},
    "DXC":                 {"ticker": "DXC",    "exchange": "NYSE",   "currency": "USD"},
    "Humana":              {"ticker": "HUM",    "exchange": "NYSE",   "currency": "USD"},
    "IBM":                 {"ticker": "IBM",    "exchange": "NYSE",   "currency": "USD"},

    # ── UK ───────────────────────────────────────────────
    "BAE Systems":         {"ticker": "BA.",    "exchange": "LSE",    "currency": "GBP"},
    "Rolls-Royce":         {"ticker": "RR.",    "exchange": "LSE",    "currency": "GBP"},
    "QinetiQ":             {"ticker": "QQ.",    "exchange": "LSE",    "currency": "GBP"},
    "Babcock":             {"ticker": "BAB",    "exchange": "LSE",    "currency": "GBP"},
    "Serco":               {"ticker": "SRP",    "exchange": "LSE",    "currency": "GBP"},
    "Capita":              {"ticker": "CPI",    "exchange": "LSE",    "currency": "GBP"},
    "Ultra Electronics":   {"ticker": "ULE",    "exchange": "LSE",    "currency": "GBP"},
    "Cobham":              {"ticker": "COB",    "exchange": "LSE",    "currency": "GBP"},
    "Meggitt":             {"ticker": "MGGT",   "exchange": "LSE",    "currency": "GBP"},
    "Senior":              {"ticker": "SNR",    "exchange": "LSE",    "currency": "GBP"},

    # ── CANADA ───────────────────────────────────────────
    "CAE":                 {"ticker": "CAE",    "exchange": "TSX",    "currency": "CAD"},
    "MDA":                 {"ticker": "MDA",    "exchange": "TSX",    "currency": "CAD"},
    "Magellan Aerospace":  {"ticker": "MAL",    "exchange": "TSX",    "currency": "CAD"},
    "Heroux-Devtek":       {"ticker": "HRX",    "exchange": "TSX",    "currency": "CAD"},
    "SNC-Lavalin":         {"ticker": "SNC",    "exchange": "TSX",    "currency": "CAD"},
    "Calian":              {"ticker": "CGY",    "exchange": "TSX",    "currency": "CAD"},
    "GDI Integrated":      {"ticker": "GDI",    "exchange": "TSX",    "currency": "CAD"},

    # ── ISRAEL ───────────────────────────────────────────
    "Elbit Systems":       {"ticker": "ESLT",   "exchange": "NASDAQ", "currency": "USD"},
    "Rafael":              {"ticker": "RFL",    "exchange": "TASE",   "currency": "ILS"},
    "Israel Aerospace":    {"ticker": "ARSP",   "exchange": "TASE",   "currency": "ILS"},
    "Silicom":             {"ticker": "SILC",   "exchange": "NASDAQ", "currency": "USD"},
    "CyberArk":            {"ticker": "CYBR",   "exchange": "NASDAQ", "currency": "USD"},
    "Check Point":         {"ticker": "CHKP",   "exchange": "NASDAQ", "currency": "USD"},
    "NICE Systems":        {"ticker": "NICE",   "exchange": "NASDAQ", "currency": "USD"},
    "Radware":             {"ticker": "RDWR",   "exchange": "NASDAQ", "currency": "USD"},
}

# =========================================================
# DATABASE
# =========================================================

def init_db():
    db = sqlite3.connect(DATABASE, check_same_thread=False)
    db.execute("""
        CREATE TABLE IF NOT EXISTS seen_awards (
            uid         TEXT PRIMARY KEY,
            award_id    TEXT,
            recipient   TEXT,
            amount_usd  REAL,
            agency      TEXT,
            country     TEXT,
            ticker      TEXT,
            exchange    TEXT,
            seen_at     TEXT
        )
    """)
    db.commit()
    return db

DB = init_db()

def already_seen(uid):
    return DB.execute(
        "SELECT 1 FROM seen_awards WHERE uid=?", (uid,)
    ).fetchone() is not None

def mark_seen(uid, award, amount_usd, country, ticker, exchange):
    DB.execute("""
        INSERT OR IGNORE INTO seen_awards
            (uid, award_id, recipient, amount_usd, agency, country, ticker, exchange, seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        uid,
        award.get("id", ""),
        award.get("recipient", "Unknown"),
        amount_usd,
        award.get("agency", ""),
        country,
        ticker,
        exchange,
        datetime.now().isoformat(),
    ))
    DB.commit()

# =========================================================
# HELPERS
# =========================================================

def retry(fn, attempts=3, delay=2):
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            log.warning(f"Attempt {i+1}/{attempts} failed: {e}")
            if i == attempts - 1:
                raise
            time.sleep(delay ** i)

def fmt_usd(n):
    v = float(n or 0)
    if v >= 1e9: return f"${v/1e9:.2f}B"
    if v >= 1e6: return f"${v/1e6:.2f}M"
    return f"${v/1e3:.0f}K"

def fmt_local(n, currency):
    symbols = {"USD": "$", "GBP": "£", "CAD": "CA$", "ILS": "₪"}
    s = symbols.get(currency, "$")
    v = float(n or 0)
    if v >= 1e9: return f"{s}{v/1e9:.2f}B"
    if v >= 1e6: return f"{s}{v/1e6:.2f}M"
    return f"{s}{v/1e3:.0f}K"

def get_fx_rate(currency):
    if currency == "USD":
        return 1.0
    try:
        pairs = {"GBP": "GBPUSD", "CAD": "CADUSD", "ILS": "ILSUSD"}
        pair  = pairs.get(currency, "GBPUSD")
        url   = f"https://query1.finance.yahoo.com/v8/finance/chart/{pair}=X?interval=1d&range=1d"
        req   = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        return data["chart"]["result"][0]["meta"]["regularMarketPrice"]
    except:
        defaults = {"GBP": 1.27, "CAD": 0.73, "ILS": 0.27}
        return defaults.get(currency, 1.0)

def get_stock_info(ticker, exchange):
    try:
        yf_ticker = ticker
        if exchange == "LSE":
            yf_ticker = ticker + ".L"
        elif exchange == "TSX":
            yf_ticker = ticker + ".TO"
        elif exchange == "TASE":
            yf_ticker = ticker + ".TA"

        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_ticker}?interval=1d&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        meta  = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice", 0)
        cap   = meta.get("marketCap", 0)
        curr  = meta.get("currency", "USD")
        return price, fmt_usd(cap) if cap else "N/A", curr
    except:
        return None, None, None

def find_company(name):
    name_lower = name.lower()
    for company, info in COMPANIES.items():
        if company.lower() in name_lower:
            return company, info["ticker"], info["exchange"], info["currency"]
    return None, None, None, None

# =========================================================
# SEC INSIDER TRADING (Form 4)
# =========================================================

def get_insider_activity(ticker):
    try:
        url = f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt={( datetime.now()-timedelta(days=30)).strftime('%Y-%m-%d')}&enddt={datetime.now().strftime('%Y-%m-%d')}&forms=4"
        req = urllib.request.Request(url, headers={"User-Agent": "contractbot@email.com"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            return None
        latest = hits[0]["_source"]
        filed  = latest.get("file_date", "")
        name   = latest.get("display_names", ["Unknown"])[0]
        return f"Form 4 filed {filed} by {name} — check SEC EDGAR for details"
    except:
        return None

# =========================================================
# FETCH US CONTRACTS (USASpending.gov)
# =========================================================

def fetch_us_awards():
    end   = datetime.now()
    start = end - timedelta(hours=3)
    payload = json.dumps({
        "filters": {
            "award_type_codes": ["A","B","C","D"],
            "time_period": [{"start_date": start.strftime("%Y-%m-%d"),
                             "end_date":   end.strftime("%Y-%m-%d")}],
            "award_amounts": [{"lower_bound": MIN_AWARD_USD}],
        },
        "fields": ["Award ID","Recipient Name","Award Amount",
                   "Awarding Agency","Description","Start Date","End Date",
                   "Place of Performance City Name",
                   "Place of Performance State Code"],
        "sort": "Award Amount", "order": "desc",
        "limit": 100, "page": 1,
    }).encode()
    req = urllib.request.Request(
        "https://api.usaspending.gov/api/v2/search/spending_by_award/",
        data=payload,
        headers={"Content-Type": "application/json",
                 "User-Agent": "ContractBot/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    results = []
    for a in data.get("results", []):
        results.append({
            "id":        a.get("Award ID", ""),
            "recipient": a.get("Recipient Name", ""),
            "amount":    float(a.get("Award Amount") or 0),
            "currency":  "USD",
            "agency":    a.get("Awarding Agency", ""),
            "desc":      (a.get("Description") or "")[:200],
            "awarded":   a.get("Start Date", ""),
            "expires":   a.get("End Date", ""),
            "location":  ", ".join(filter(None, [
                a.get("Place of Performance City Name",""),
                a.get("Place of Performance State Code","")
            ])),
            "country":   "USA",
            "source":    "USASpending.gov",
        })
    return results

# =========================================================
# FETCH UK CONTRACTS (Contracts Finder)
# =========================================================

def fetch_uk_awards():
    try:
        min_gbp = int(MIN_AWARD_USD * 0.79)
        url = f"https://www.contractsfinder.service.gov.uk/Published/Notices/PublishedNoticesSearchApi/Search?publishedFrom={( datetime.now()-timedelta(hours=6)).strftime('%Y-%m-%dT%H:%M:%S')}&publishedTo={datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}&type=Award&valueFrom={min_gbp}&size=100&page=1"
        req = urllib.request.Request(url, headers={"User-Agent": "ContractBot/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        results = []
        fx = get_fx_rate("GBP")
        for a in data.get("results", []):
            notice = a.get("notice", {})
            amount_gbp = float(notice.get("value", {}).get("amount", 0) or 0)
            results.append({
                "id":        notice.get("id", ""),
                "recipient": notice.get("suppliers", [{}])[0].get("name", "Unknown") if notice.get("suppliers") else "Unknown",
                "amount":    amount_gbp,
                "amount_usd": amount_gbp * fx,
                "currency":  "GBP",
                "agency":    notice.get("organisations", [{}])[0].get("name", "") if notice.get("organisations") else "",
                "desc":      (notice.get("description") or "")[:200],
                "awarded":   notice.get("awardedDate", "")[:10] if notice.get("awardedDate") else "",
                "expires":   notice.get("contractEnd", "")[:10] if notice.get("contractEnd") else "",
                "location":  "United Kingdom",
                "country":   "UK",
                "source":    "Contracts Finder (UK)",
            })
        return results
    except Exception as e:
        log.warning(f"UK fetch failed: {e}")
        return []

# =========================================================
# FETCH CANADA CONTRACTS (Buyandsell.gc.ca)
# =========================================================

def fetch_canada_awards():
    try:
        min_cad = int(MIN_AWARD_USD * 1.36)
        url = f"https://buyandsell.gc.ca/procurement-data/award-notice/search/page/1?data-format=json&contract_value_from={min_cad}"
        req = urllib.request.Request(url, headers={"User-Agent": "ContractBot/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        results = []
        fx = get_fx_rate("CAD")
        for a in data.get("data", []):
            amount_cad = float(a.get("contract_value", 0) or 0)
            results.append({
                "id":        a.get("reference_number", ""),
                "recipient": a.get("vendor_name", "Unknown"),
                "amount":    amount_cad,
                "amount_usd": amount_cad * fx,
                "currency":  "CAD",
                "agency":    a.get("owner_org_title", ""),
                "desc":      (a.get("description") or "")[:200],
                "awarded":   a.get("contract_date", ""),
                "expires":   a.get("delivery_date", ""),
                "location":  "Canada",
                "country":   "Canada",
                "source":    "Buyandsell.gc.ca (Canada)",
            })
        return results
    except Exception as e:
        log.warning(f"Canada fetch failed: {e}")
        return []

# =========================================================
# FETCH ISRAEL CONTRACTS (Mr. Tender)
# =========================================================

def fetch_israel_awards():
    try:
        url = "https://www.mr.gov.il/OpenGovDataDownload/Awards.json"
        req = urllib.request.Request(url, headers={"User-Agent": "ContractBot/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        results = []
        fx = get_fx_rate("ILS")
        min_ils = MIN_AWARD_USD / fx
        for a in data[:200]:
            amount_ils = float(a.get("Amount", 0) or 0)
            if amount_ils < min_ils:
                continue
            results.append({
                "id":        str(a.get("ID", "")),
                "recipient": a.get("SupplierName", "Unknown"),
                "amount":    amount_ils,
                "amount_usd": amount_ils * fx,
                "currency":  "ILS",
                "agency":    a.get("PublisherName", ""),
                "desc":      (a.get("Description") or "")[:200],
                "awarded":   (a.get("AwardDate") or "")[:10],
                "expires":   (a.get("EndDate") or "")[:10],
                "location":  "Israel",
                "country":   "Israel",
                "source":    "Mr. Tender (Israel)",
            })
        return results
    except Exception as e:
        log.warning(f"Israel fetch failed: {e}")
        return []

# =========================================================
# PUSH NOTIFICATION
# =========================================================

def send_push(award, company, ticker, exchange, stock_currency,
              price, cap, amount_usd, insider):
    recipient  = award.get("recipient", "Unknown")
    currency   = award.get("currency", "USD")
    amount_loc = fmt_local(award.get("amount", 0), currency)
    awarded    = award.get("awarded", "Unknown")
    expires    = award.get("expires", "Unknown")
    agency     = award.get("agency", "")
    desc       = award.get("desc", "")[:150]
    country    = award.get("country", "")
    source     = award.get("source", "")
    award_id   = award.get("id", "")
    alerted_at = datetime.now().strftime("%b %d %Y at %I:%M %p")
    amt_val    = float(amount_usd or 0)
    priority   = "urgent" if amt_val >= 50_000_000 else "high"

    title = f"${ticker} | {recipient}" if ticker else recipient

    lines = []
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("CONTRACT")
    lines.append(f"Value    : {amount_loc} ({fmt_usd(amount_usd)} USD)")
    lines.append(f"Awarded  : {awarded}")
    lines.append(f"Expires  : {expires}")
    lines.append(f"Agency   : {agency}")
    lines.append(f"Country  : {country}")
    lines.append(f"What     : {desc}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("STOCK")
    lines.append(f"Exchange : {exchange}")
    lines.append(f"Ticker   : {ticker}")
    if price:
        lines.append(f"Price    : {price:.2f} {stock_currency}")
    if cap:
        lines.append(f"Mkt Cap  : {cap}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    if insider:
        lines.append("INSIDER ACTIVITY")
        lines.append(insider)
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"Source   : {source}")
    lines.append(f"Alert    : {alerted_at}")

    body = "\n".join(lines)

    link = ""
    if award.get("country") == "USA":
        link = f"https://www.usaspending.gov/award/{award_id}"
    elif award.get("country") == "UK":
        link = f"https://www.contractsfinder.service.gov.uk/Notice/{award_id}"
    elif award.get("country") == "Israel":
        link = f"https://www.mr.gov.il"

    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=body.encode(),
        headers={
            "Title":    title,
            "Priority": priority,
            "Tags":     "money_bag,chart_with_upwards_trend",
            "Click":    link,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10):
        pass

# =========================================================
# MAIN CHECK
# =========================================================

def check():
    log.info("─" * 55)
    log.info(f"Checking all markets — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    all_awards = []

    # Fetch from all four sources
    try:
        us = fetch_us_awards()
        log.info(f"USA: {len(us)} contracts fetched")
        all_awards.extend(us)
    except Exception as e:
        log.error(f"USA fetch failed: {e}")

    try:
        uk = fetch_uk_awards()
        log.info(f"UK: {len(uk)} contracts fetched")
        all_awards.extend(uk)
    except Exception as e:
        log.error(f"UK fetch failed: {e}")

    try:
        ca = fetch_canada_awards()
        log.info(f"Canada: {len(ca)} contracts fetched")
        all_awards.extend(ca)
    except Exception as e:
        log.error(f"Canada fetch failed: {e}")

    try:
        il = fetch_israel_awards()
        log.info(f"Israel: {len(il)} contracts fetched")
        all_awards.extend(il)
    except Exception as e:
        log.error(f"Israel fetch failed: {e}")

    log.info(f"Total fetched: {len(all_awards)}")

    new_count = 0
    for award in all_awards:
        uid = f"{award['country']}:{award['id']}:{award['amount']}"
        if already_seen(uid):
            continue

        company, ticker, exchange, currency = find_company(award["recipient"])
        if not company:
            continue

        # Get amount in USD
        amount_usd = award.get("amount_usd", award["amount"])

        log.info(f"NEW ★ [{award['country']}] {award['recipient']} | {fmt_usd(amount_usd)} | {ticker or 'PRIVATE'}")

        # Get stock info
        price, cap, stock_currency = None, None, None
        if ticker:
            price, cap, stock_currency = get_stock_info(ticker, exchange)

        # Get insider activity
        insider = None
        if ticker and award.get("country") == "USA":
            insider = get_insider_activity(ticker)

        # Send push
        try:
            send_push(award, company, ticker, exchange, stock_currency,
                      price, cap, amount_usd, insider)
            log.info(f"  Pushed to ntfy.sh/{NTFY_TOPIC}")
        except Exception as e:
            log.error(f"  Push failed: {e}")

        mark_seen(uid, award, amount_usd, award["country"], ticker or "", exchange or "")
        new_count += 1

    log.info(f"Done — {new_count} new alerts sent")

# =========================================================
# START
# =========================================================

print("=" * 55)
print("  GLOBAL CONTRACT ALERT BOT")
print("=" * 55)
print(f"  Markets  : USA, UK, Canada, Israel")
print(f"  Min award: {fmt_usd(MIN_AWARD_USD)}")
print(f"  Interval : every {CHECK_MINUTES} minutes")
print(f"  ntfy     : ntfy.sh/{NTFY_TOPIC}")
print("=" * 55)

check()
while True:
    time.sleep(CHECK_MINUTES * 60)
    check()
