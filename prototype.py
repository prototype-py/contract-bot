import csv
import io
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

NTFY_TOPIC     = "my-contract-alerts"
MIN_AWARD_USD  = 5_000_000
CHECK_MINUTES  = 60
LOOKBACK_HOURS = 2
DATABASE       = "contracts.db"

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
# KNOWN COMPANIES
# =========================================================

KNOWN = {
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
    "IBM":                 {"ticker": "IBM",    "exchange": "NYSE",   "currency": "USD"},
    "BAE Systems":         {"ticker": "BA.L",   "exchange": "LSE",    "currency": "GBP"},
    "Rolls-Royce":         {"ticker": "RR.L",   "exchange": "LSE",    "currency": "GBP"},
    "QinetiQ":             {"ticker": "QQ.L",   "exchange": "LSE",    "currency": "GBP"},
    "Babcock":             {"ticker": "BAB.L",  "exchange": "LSE",    "currency": "GBP"},
    "Serco":               {"ticker": "SRP.L",  "exchange": "LSE",    "currency": "GBP"},
    "Capita":              {"ticker": "CPI.L",  "exchange": "LSE",    "currency": "GBP"},
    "Kier":                {"ticker": "KIE.L",  "exchange": "LSE",    "currency": "GBP"},
    "Balfour Beatty":      {"ticker": "BBY.L",  "exchange": "LSE",    "currency": "GBP"},
    "G4S":                 {"ticker": "GFS.L",  "exchange": "LSE",    "currency": "GBP"},
    "CAE":                 {"ticker": "CAE.TO", "exchange": "TSX",    "currency": "CAD"},
    "MDA":                 {"ticker": "MDA.TO", "exchange": "TSX",    "currency": "CAD"},
    "Magellan Aerospace":  {"ticker": "MAL.TO", "exchange": "TSX",    "currency": "CAD"},
    "Heroux-Devtek":       {"ticker": "HRX.TO", "exchange": "TSX",    "currency": "CAD"},
    "Calian":              {"ticker": "CGY.TO", "exchange": "TSX",    "currency": "CAD"},
    "SNC-Lavalin":         {"ticker": "SNC.TO", "exchange": "TSX",    "currency": "CAD"},
    "Elbit Systems":       {"ticker": "ESLT",   "exchange": "NASDAQ", "currency": "USD"},
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
            uid        TEXT PRIMARY KEY,
            recipient  TEXT,
            amount_usd REAL,
            agency     TEXT,
            country    TEXT,
            ticker     TEXT,
            exchange   TEXT,
            seen_at    TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS ticker_cache (
            name       TEXT PRIMARY KEY,
            ticker     TEXT,
            exchange   TEXT,
            found_at   TEXT
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
            (uid, recipient, amount_usd, agency, country, ticker, exchange, seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (uid, award.get("recipient",""), amount_usd,
          award.get("agency",""), country, ticker, exchange,
          datetime.now().isoformat()))
    DB.commit()

def get_cached_ticker(name):
    row = DB.execute(
        "SELECT ticker, exchange FROM ticker_cache WHERE name=?", (name,)
    ).fetchone()
    return (row[0], row[1]) if row else None

def cache_ticker(name, ticker, exchange):
    DB.execute("""
        INSERT OR REPLACE INTO ticker_cache (name, ticker, exchange, found_at)
        VALUES (?, ?, ?, ?)
    """, (name, ticker, exchange, datetime.now().isoformat()))
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
    symbols = {"USD":"$","GBP":"£","CAD":"CA$","ILS":"₪"}
    s = symbols.get(currency, "$")
    v = float(n or 0)
    if v >= 1e9: return f"{s}{v/1e9:.2f}B"
    if v >= 1e6: return f"{s}{v/1e6:.2f}M"
    return f"{s}{v/1e3:.0f}K"

def get_fx_rate(currency):
    if currency == "USD": return 1.0
    try:
        pairs = {"GBP":"GBPUSD=X","CAD":"CADUSD=X","ILS":"ILSUSD=X"}
        url   = f"https://query1.finance.yahoo.com/v8/finance/chart/{pairs.get(currency,'GBPUSD=X')}?interval=1d&range=1d"
        req   = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        return data["chart"]["result"][0]["meta"]["regularMarketPrice"]
    except:
        return {"GBP":1.27,"CAD":0.73,"ILS":0.27}.get(currency, 1.0)

def get_stock_info(ticker):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        meta  = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice", 0)
        cap   = meta.get("marketCap", 0)
        curr  = meta.get("currency", "USD")
        exch  = meta.get("exchangeName", "")
        return price, fmt_usd(cap) if cap else "N/A", curr, exch
    except:
        return None, None, None, None

# =========================================================
# COMPANY LOOKUP
# =========================================================

def search_edgar(company_name):
    try:
        import re
        clean = company_name
        for s in [" LLC"," Inc"," Corp"," Ltd"," LP"," LLP"," Co"," Group",","," plc"," PLC"]:
            clean = clean.replace(s, "").strip()
        params = urllib.parse.urlencode({
            "company": clean, "type": "", "dateb": "",
            "owner": "include", "count": "5",
            "search_text": "", "action": "getcompany"
        })
        url = f"https://www.sec.gov/cgi-bin/browse-edgar?{params}&output=atom"
        req = urllib.request.Request(url, headers={"User-Agent":"contractbot@gmail.com"})
        with urllib.request.urlopen(req, timeout=10) as r:
            content = r.read().decode("utf-8")
        matches = re.findall(r'\(([A-Z]{1,5})\)', content)
        if not matches:
            return None, None
        ticker = matches[0]
        price, cap, curr, exch = get_stock_info(ticker)
        if cap and cap != "N/A":
            log.info(f"  EDGAR found: {company_name} → ${ticker} ({exch})")
            return ticker, exch
        return None, None
    except Exception as e:
        log.debug(f"EDGAR lookup failed for {company_name}: {e}")
        return None, None

def find_company(name):
    name_lower = name.lower()
    # Step 1 — known list
    for company, info in KNOWN.items():
        if company.lower() in name_lower:
            return info["ticker"], info["exchange"], info["currency"]
    # Step 2 — cache
    cached = get_cached_ticker(name)
    if cached:
        ticker, exchange = cached
        if ticker == "NONE":
            return None, None, None
        return ticker, exchange, "USD"
    # Step 3 — EDGAR live search
    log.info(f"  Searching EDGAR for: {name}")
    ticker, exchange = search_edgar(name)
    if ticker:
        cache_ticker(name, ticker, exchange or "NASDAQ")
        return ticker, exchange or "NASDAQ", "USD"
    cache_ticker(name, "NONE", "NONE")
    return None, None, None

# =========================================================
# SEC INSIDER TRADING
# =========================================================

def get_insider_activity(ticker):
    try:
        since = (datetime.now()-timedelta(days=30)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")
        url   = (f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22"
                 f"&dateRange=custom&startdt={since}&enddt={today}&forms=4")
        req = urllib.request.Request(url, headers={"User-Agent":"contractbot@gmail.com"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        hits = data.get("hits",{}).get("hits",[])
        if not hits: return None
        latest = hits[0]["_source"]
        return f"Form 4 filed {latest.get('file_date','')} by {latest.get('display_names',['Unknown'])[0]}"
    except:
        return None

# =========================================================
# FETCH USA
# =========================================================

def fetch_us_awards():
    end   = datetime.now()
    start = end - timedelta(hours=LOOKBACK_HOURS)
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
        headers={"Content-Type":"application/json","User-Agent":"ContractBot/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    results = []
    for a in data.get("results", []):
        results.append({
            "id":         a.get("Award ID",""),
            "recipient":  a.get("Recipient Name",""),
            "amount":     float(a.get("Award Amount") or 0),
            "amount_usd": float(a.get("Award Amount") or 0),
            "currency":   "USD",
            "agency":     a.get("Awarding Agency",""),
            "desc":       (a.get("Description") or "")[:200],
            "awarded":    a.get("Start Date",""),
            "expires":    a.get("End Date",""),
            "location":   ", ".join(filter(None,[
                a.get("Place of Performance City Name",""),
                a.get("Place of Performance State Code","")
            ])),
            "country":    "USA",
            "source":     "USASpending.gov",
        })
    return results

# =========================================================
# FETCH UK
# =========================================================

def fetch_uk_awards():
    try:
        since = (datetime.now()-timedelta(hours=LOOKBACK_HOURS)).strftime("%Y-%m-%dT%H:%M:%S")
        now   = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        url   = (f"https://www.contractsfinder.service.gov.uk"
                 f"/Published/Notices/OCDS/Search"
                 f"?publishedFrom={since}&publishedTo={now}"
                 f"&stages=award&limit=100")
        req = urllib.request.Request(url,
            headers={"User-Agent":"ContractBot/1.0","Accept":"application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        fx      = get_fx_rate("GBP")
        results = []
        for release in data.get("releases", []):
            for award in release.get("awards", []):
                amount_gbp = float((award.get("value") or {}).get("amount",0) or 0)
                if amount_gbp * fx < MIN_AWARD_USD:
                    continue
                suppliers = award.get("suppliers",[{}])
                name      = suppliers[0].get("name","Unknown") if suppliers else "Unknown"
                buyer     = release.get("buyer",{}).get("name","")
                desc      = (release.get("tender",{}).get("description") or "")[:200]
                awarded   = (award.get("date") or "")[:10]
                expires   = ((award.get("contractPeriod") or {}).get("endDate") or "")[:10]
                results.append({
                    "id":         release.get("ocid",""),
                    "recipient":  name,
                    "amount":     amount_gbp,
                    "amount_usd": amount_gbp * fx,
                    "currency":   "GBP",
                    "agency":     buyer,
                    "desc":       desc,
                    "awarded":    awarded,
                    "expires":    expires,
                    "location":   "United Kingdom",
                    "country":    "UK",
                    "source":     "Contracts Finder (UK)",
                })
        return results
    except Exception as e:
        log.warning(f"UK fetch failed: {e}")
        return []

# =========================================================
# FETCH CANADA
# =========================================================

def fetch_canada_awards():
    try:
        fx      = get_fx_rate("CAD")
        min_cad = MIN_AWARD_USD / fx
        since   = (datetime.now()-timedelta(hours=LOOKBACK_HOURS)).strftime("%Y-%m-%d")
        # Current fiscal year CSV — updated every morning by Canada government
        url = "https://canadabuys.canada.ca/opendata/pub/2026-2027-awardNotice-avisAttribution.csv"
        req = urllib.request.Request(url, headers={"User-Agent":"ContractBot/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            content = r.read().decode("utf-8-sig")
        results = []
        reader  = csv.DictReader(io.StringIO(content))
        for row in reader:
            # Contract value
            val_str = ""
            for f in ["contractValue-valeurContrat","totalValue-valeurTotale","contract_value"]:
                if row.get(f):
                    val_str = row[f]; break
            try:
                amount_cad = float(str(val_str).replace(",","").replace("$","").strip() or 0)
            except:
                amount_cad = 0
            if amount_cad < min_cad:
                continue
            # Award date
            awarded = ""
            for f in ["publicationDate-datePublication","contractDate-dateContrat","contract_date"]:
                if row.get(f):
                    awarded = str(row[f])[:10]; break
            if awarded and awarded < since:
                continue
            # Vendor
            vendor = ""
            for f in ["vendorName-nomFournisseur","vendor_name","supplierName-nomFournisseur"]:
                if row.get(f):
                    vendor = row[f]; break
            if not vendor:
                continue
            # Description
            desc = ""
            for f in ["description-descriptionDuContrat","description","title-titre"]:
                if row.get(f):
                    desc = str(row[f])[:200]; break
            # Reference
            ref = ""
            for f in ["referenceNumber-numeroReference","reference_number","solicitationNumber-numeroSollicitation"]:
                if row.get(f):
                    ref = row[f]; break
            if not ref:
                ref = str(hash(vendor+awarded))
            results.append({
                "id":         ref,
                "recipient":  vendor,
                "amount":     amount_cad,
                "amount_usd": amount_cad * fx,
                "currency":   "CAD",
                "agency":     row.get("ownerAcronym-acronymeProprietaire",""),
                "desc":       desc,
                "awarded":    awarded,
                "expires":    "",
                "location":   "Canada",
                "country":    "Canada",
                "source":     "CanadaBuys (Canada)",
            })
        return results
    except Exception as e:
        log.warning(f"Canada fetch failed: {e}")
        return []

# =========================================================
# FETCH ISRAEL
# =========================================================

def fetch_israel_awards():
    try:
        fx      = get_fx_rate("ILS")
        min_ils = MIN_AWARD_USD / fx
        since   = (datetime.now()-timedelta(hours=LOOKBACK_HOURS)).strftime("%Y-%m-%d")
        # OpenBudget Israel — open procurement API
        url = (f"https://next.obudget.org/api/query?"
               f"query=SELECT%20*%20FROM%20procurement_winner_detail"
               f"%20WHERE%20start_date%3E%3D%27{since}%27"
               f"%20ORDER%20BY%20volume%20DESC%20LIMIT%20100&num_rows=100")
        req = urllib.request.Request(url,
            headers={"User-Agent":"ContractBot/1.0","Accept":"application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        results = []
        for a in data.get("rows", []):
            try:
                amount_ils = float(a.get("volume") or 0)
            except:
                amount_ils = 0
            if amount_ils < min_ils:
                continue
            results.append({
                "id":         str(a.get("order_id","")),
                "recipient":  a.get("supplier_name","Unknown"),
                "amount":     amount_ils,
                "amount_usd": amount_ils * fx,
                "currency":   "ILS",
                "agency":     a.get("purchasing_unit_name",""),
                "desc":       (a.get("description") or "")[:200],
                "awarded":    str(a.get("start_date",""))[:10],
                "expires":    str(a.get("end_date",""))[:10],
                "location":   "Israel",
                "country":    "Israel",
                "source":     "OpenBudget Israel",
            })
        return results
    except Exception as e:
        log.warning(f"Israel fetch failed: {e}")
        return []

# =========================================================
# PUSH NOTIFICATION
# =========================================================

def send_push(award, ticker, exchange, stock_currency, price, cap, amount_usd, insider):
    recipient  = award.get("recipient","Unknown")
    currency   = award.get("currency","USD")
    amount_loc = fmt_local(award.get("amount",0), currency)
    awarded    = award.get("awarded","Unknown")
    expires    = award.get("expires","")
    agency     = award.get("agency","")
    desc       = award.get("desc","")[:150]
    country    = award.get("country","")
    source     = award.get("source","")
    award_id   = award.get("id","")
    alerted_at = datetime.now().strftime("%b %d %Y at %I:%M %p")
    amt_val    = float(amount_usd or 0)
    priority   = "urgent" if amt_val >= 50_000_000 else "high"
    title      = f"${ticker} | {recipient}" if ticker else recipient

    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        "CONTRACT",
        f"Value    : {amount_loc} ({fmt_usd(amount_usd)} USD)",
        f"Awarded  : {awarded}",
    ]
    if expires:
        lines.append(f"Expires  : {expires}")
    lines += [
        f"Agency   : {agency}",
        f"Country  : {country}",
        f"What     : {desc}",
        "━━━━━━━━━━━━━━━━━━━━",
        "STOCK",
        f"Exchange : {exchange}",
        f"Ticker   : {ticker}",
    ]
    if price: lines.append(f"Price    : {price:.2f} {stock_currency or ''}")
    if cap:   lines.append(f"Mkt Cap  : {cap}")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    if insider:
        lines += ["INSIDER ACTIVITY", insider, "━━━━━━━━━━━━━━━━━━━━"]
    lines += [f"Source   : {source}", f"Alert    : {alerted_at}"]

    body = "\n".join(lines)

    if country == "USA":
        link = f"https://www.usaspending.gov/award/{award_id}"
    elif country == "UK":
        link = f"https://www.contractsfinder.service.gov.uk/Notice/{award_id}"
    else:
        link = "https://www.usaspending.gov"

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
    retry(lambda: urllib.request.urlopen(req, timeout=10).close())
    log.info(f"  Pushed: {title}")

# =========================================================
# TEST PUSH — sends one test notification on startup
# =========================================================

def send_test_push():
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data="Contract Alert Bot is live and monitoring USA, UK, Canada and Israel.".encode(),
            headers={
                "Title":    "Contract Bot Started",
                "Priority": "default",
                "Tags":     "white_check_mark",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10).close()
        log.info("Test push sent to phone")
    except Exception as e:
        log.warning(f"Test push failed: {e}")

# =========================================================
# MAIN CHECK
# =========================================================

def check():
    log.info("─" * 55)
    log.info(f"Checking all markets — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    all_awards = []
    for name, fn in [("USA",    fetch_us_awards),
                     ("UK",     fetch_uk_awards),
                     ("Canada", fetch_canada_awards),
                     ("Israel", fetch_israel_awards)]:
        try:
            awards = fn()
            log.info(f"{name}: {len(awards)} contracts fetched")
            all_awards.extend(awards)
        except Exception as e:
            log.error(f"{name} fetch failed: {e}")

    log.info(f"Total fetched: {len(all_awards)}")

    new_count = 0
    for award in all_awards:
        uid = f"{award['country']}:{award['id']}:{award['amount']}"
        if already_seen(uid):
            continue

        ticker, exchange, currency = find_company(award["recipient"])
        if not ticker:
            mark_seen(uid, award, award.get("amount_usd",0),
                      award["country"], "", "")
            continue

        amount_usd = award.get("amount_usd", award["amount"])
        log.info(f"NEW ★ [{award['country']}] {award['recipient']} | "
                 f"{fmt_usd(amount_usd)} | ${ticker} on {exchange}")

        price, cap, stock_currency, _ = get_stock_info(ticker)
        insider = None
        if award.get("country") == "USA":
            insider = get_insider_activity(ticker)

        try:
            send_push(award, ticker, exchange, stock_currency,
                      price, cap, amount_usd, insider)
        except Exception as e:
            log.error(f"Push failed: {e}")

        mark_seen(uid, award, amount_usd, award["country"], ticker, exchange)
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
print(f"  Lookback : {LOOKBACK_HOURS} hours per check")
print(f"  Interval : every {CHECK_MINUTES} minutes")
print(f"  ntfy     : ntfy.sh/{NTFY_TOPIC}")
print("=" * 55)

# Send test push so you know phone is connected
send_test_push()

# First check
check()

# Loop forever
while True:
    log.info(f"Sleeping {CHECK_MINUTES} minutes until next check...")
    time.sleep(CHECK_MINUTES * 60)
    check()
