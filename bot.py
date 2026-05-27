import csv
import io
import json
import re
import time
import sqlite3
import logging
import threading
import urllib.request
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from pathlib import Path

# =========================================================
# SETTINGS
# =========================================================

NTFY_TOPIC          = "my-contract-alerts"
MIN_AWARD_USD       = 5_000_000
CHECK_MINUTES       = 60
LOOKBACK_HOURS      = 2
DATABASE            = "contracts.db"
MIN_DEAL_SCORE      = 5
MIN_INSIDER_BUY_USD = 250_000   # Only alert on buys over $250K

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
# KEEP-ALIVE WEB SERVER
# =========================================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(f"Contract Bot running. {datetime.now()}".encode())
    def log_message(self, format, *args):
        pass

def start_web_server():
    server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
    log.info("Health server running on port 8080")
    server.serve_forever()

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
    "RTX Corp":            {"ticker": "RTX",    "exchange": "NYSE",   "currency": "USD"},
    "Northrop Grumman":    {"ticker": "NOC",    "exchange": "NYSE",   "currency": "USD"},
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
    "Honeywell":           {"ticker": "HON",    "exchange": "NASDAQ", "currency": "USD"},
    "General Electric":    {"ticker": "GE",     "exchange": "NYSE",   "currency": "USD"},
    "Boeing":              {"ticker": "BA",     "exchange": "NYSE",   "currency": "USD"},
    "Huntington Ingalls":  {"ticker": "HII",    "exchange": "NYSE",   "currency": "USD"},
    "Huntington-Ingalls":  {"ticker": "HII",    "exchange": "NYSE",   "currency": "USD"},
    "Humana":              {"ticker": "HUM",    "exchange": "NYSE",   "currency": "USD"},
    "Oracle":              {"ticker": "ORCL",   "exchange": "NYSE",   "currency": "USD"},
    "Microsoft":           {"ticker": "MSFT",   "exchange": "NASDAQ", "currency": "USD"},
    "Amazon":              {"ticker": "AMZN",   "exchange": "NASDAQ", "currency": "USD"},
    "Google":              {"ticker": "GOOGL",  "exchange": "NASDAQ", "currency": "USD"},
    "Alphabet":            {"ticker": "GOOGL",  "exchange": "NASDAQ", "currency": "USD"},
    "Vectrus":             {"ticker": "VEC",    "exchange": "NYSE",   "currency": "USD"},
    "Amentum":             {"ticker": "AMTM",   "exchange": "NYSE",   "currency": "USD"},
    "Pratt and Whitney":   {"ticker": "RTX",    "exchange": "NYSE",   "currency": "USD"},
    "Pratt & Whitney":     {"ticker": "RTX",    "exchange": "NYSE",   "currency": "USD"},
    "Collins Aerospace":   {"ticker": "RTX",    "exchange": "NYSE",   "currency": "USD"},
    "Sikorsky":            {"ticker": "LMT",    "exchange": "NYSE",   "currency": "USD"},
    "BAE Systems":         {"ticker": "BA.L",   "exchange": "LSE",    "currency": "GBP"},
    "Rolls-Royce":         {"ticker": "RR.L",   "exchange": "LSE",    "currency": "GBP"},
    "QinetiQ":             {"ticker": "QQ.L",   "exchange": "LSE",    "currency": "GBP"},
    "Babcock":             {"ticker": "BAB.L",  "exchange": "LSE",    "currency": "GBP"},
    "Serco":               {"ticker": "SRP.L",  "exchange": "LSE",    "currency": "GBP"},
    "Capita":              {"ticker": "CPI.L",  "exchange": "LSE",    "currency": "GBP"},
    "Kier":                {"ticker": "KIE.L",  "exchange": "LSE",    "currency": "GBP"},
    "Balfour Beatty":      {"ticker": "BBY.L",  "exchange": "LSE",    "currency": "GBP"},
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

# Tickers to monitor for standalone insider activity
# These are our highest conviction watchlist companies
INSIDER_WATCHLIST = [
    "KTOS","MRCY","DRS","PSN","RKLB","VSEC","LDOS","BAH","SAIC",
    "CACI","LMT","NOC","RTX","GD","LHX","HII","TXT","KBR","TTEK",
    "ACM","PLTR","HON","GE","BA","BWXT","CW","HEI","TGI","AJRD",
    "ICFI","MMS","MANT","SPR","KAMN","FLR","DXC","IBM","AMTM",
    "ESLT","CYBR","CHKP","NICE","RDWR",
]

# C-suite titles that matter
INSIDER_TITLES = [
    "chief executive", "ceo", "chief financial", "cfo",
    "chief operating", "coo", "president", "chairman",
    "chief technology", "cto", "director", "executive vice president",
    "senior vice president",
]

# =========================================================
# DATABASE
# =========================================================

def init_db():
    db = sqlite3.connect(DATABASE, check_same_thread=False)
    db.execute("""
        CREATE TABLE IF NOT EXISTS seen_awards (
            uid TEXT PRIMARY KEY, recipient TEXT, amount_usd REAL,
            agency TEXT, country TEXT, ticker TEXT, exchange TEXT,
            deal_score REAL, seen_at TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS ticker_cache (
            name TEXT PRIMARY KEY, ticker TEXT, exchange TEXT, found_at TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS seen_insider (
            uid TEXT PRIMARY KEY, ticker TEXT, insider_name TEXT,
            title TEXT, amount_usd REAL, seen_at TEXT
        )
    """)
    db.commit()
    return db

DB = init_db()

def already_seen(uid):
    return DB.execute("SELECT 1 FROM seen_awards WHERE uid=?", (uid,)).fetchone() is not None

def already_seen_insider(uid):
    return DB.execute("SELECT 1 FROM seen_insider WHERE uid=?", (uid,)).fetchone() is not None

def mark_seen(uid, award, amount_usd, country, ticker, exchange, deal_score):
    DB.execute("""
        INSERT OR IGNORE INTO seen_awards
        (uid, recipient, amount_usd, agency, country, ticker, exchange, deal_score, seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (uid, award.get("recipient",""), amount_usd, award.get("agency",""),
          country, ticker, exchange, deal_score, datetime.now().isoformat()))
    DB.commit()

def mark_seen_insider(uid, ticker, insider_name, title, amount_usd):
    DB.execute("""
        INSERT OR IGNORE INTO seen_insider
        (uid, ticker, insider_name, title, amount_usd, seen_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (uid, ticker, insider_name, title, amount_usd, datetime.now().isoformat()))
    DB.commit()

def get_cached_ticker(name):
    row = DB.execute("SELECT ticker, exchange FROM ticker_cache WHERE name=?", (name,)).fetchone()
    return (row[0], row[1]) if row else None

def cache_ticker(name, ticker, exchange):
    DB.execute("INSERT OR REPLACE INTO ticker_cache (name, ticker, exchange, found_at) VALUES (?, ?, ?, ?)",
               (name, ticker, exchange, datetime.now().isoformat()))
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
        meta = data["chart"]["result"][0]["meta"]
        return (meta.get("regularMarketPrice",0), meta.get("marketCap",0),
                meta.get("currency","USD"), meta.get("exchangeName",""))
    except:
        return None, None, None, None

# =========================================================
# DEAL SCORING
# =========================================================

def get_contract_years(awarded, expires):
    try:
        if not awarded or not expires: return 1.0
        start = datetime.strptime(awarded[:10], "%Y-%m-%d")
        end   = datetime.strptime(expires[:10], "%Y-%m-%d")
        return max((end - start).days / 365.25, 0.1)
    except:
        return 1.0

def score_deal(amount_usd, market_cap, years, insider):
    score = 0
    reasons = []
    if not market_cap or market_cap <= 0:
        return 25, "NOTABLE", ["Market cap unavailable — verify manually"]
    pct = (amount_usd / market_cap) * 100
    if pct >= 50:   score += 60; reasons.append(f"Contract is {pct:.0f}% of market cap — TRANSFORMATIVE")
    elif pct >= 25: score += 50; reasons.append(f"Contract is {pct:.0f}% of market cap — EXCEPTIONAL")
    elif pct >= 10: score += 35; reasons.append(f"Contract is {pct:.0f}% of market cap — VERY STRONG")
    elif pct >= 5:  score += 20; reasons.append(f"Contract is {pct:.0f}% of market cap — SOLID")
    elif pct >= 2:  score += 10; reasons.append(f"Contract is {pct:.1f}% of market cap — MODERATE")
    else:           score += 2;  reasons.append(f"Contract is {pct:.1f}% of market cap — MINOR")
    if amount_usd >= 500_000_000: score += 20; reasons.append("Mega contract $500M+")
    elif amount_usd >= 100_000_000: score += 15; reasons.append("Large contract $100M+")
    elif amount_usd >= 50_000_000:  score += 10; reasons.append("Significant contract $50M+")
    elif amount_usd >= 10_000_000:  score += 5;  reasons.append("Notable contract $10M+")
    if years >= 5:   score += 10; reasons.append(f"{years:.0f} year contract — long term revenue")
    elif years >= 3: score += 7;  reasons.append(f"{years:.0f} year contract — multi-year revenue")
    elif years >= 2: score += 4;  reasons.append(f"{years:.0f} year contract")
    elif years >= 1: score += 2;  reasons.append(f"{years:.0f} year contract")
    if insider: score += 10; reasons.append("Insider buying detected — strong confirmation")
    score = min(score, 100)
    if score >= 70:   rating = "STRONG BUY"
    elif score >= 50: rating = "HIGH VALUE"
    elif score >= 30: rating = "NOTABLE"
    elif score >= 15: rating = "WATCH"
    else:             rating = "LOW IMPACT"
    return score, rating, reasons

# =========================================================
# COMPANY LOOKUP
# =========================================================

def search_edgar(company_name):
    try:
        clean = company_name
        for s in [" LLC"," Inc"," Corp"," Ltd"," LP"," LLP"," Co"," Group",","," plc"," PLC"," LIMITED"," Incorporated"]:
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
        if not matches: return None, None
        ticker = matches[0]
        _, cap, _, exch = get_stock_info(ticker)
        if cap and cap > 0:
            log.info(f"  EDGAR found: {company_name} → ${ticker} ({exch})")
            return ticker, exch
        return None, None
    except Exception as e:
        log.debug(f"EDGAR lookup failed for {company_name}: {e}")
        return None, None

def find_company(name):
    name_lower = name.lower()
    for company, info in KNOWN.items():
        if company.lower() in name_lower:
            return info["ticker"], info["exchange"], info["currency"]
    cached = get_cached_ticker(name)
    if cached:
        ticker, exchange = cached
        if ticker == "NONE": return None, None, None
        return ticker, exchange, "USD"
    log.info(f"  Searching EDGAR for: {name}")
    ticker, exchange = search_edgar(name)
    if ticker:
        cache_ticker(name, ticker, exchange or "NASDAQ")
        return ticker, exchange or "NASDAQ", "USD"
    cache_ticker(name, "NONE", "NONE")
    return None, None, None

# =========================================================
# SEC INSIDER TRADING — PROPER XML PARSER
#
# Architecture:
#   1. Search SEC EDGAR for recent Form 4 filings by ticker
#   2. Get accession number for each filing
#   3. Fetch the actual Form 4 XML document
#   4. Parse structured fields:
#      - transactionCode (P=purchase, S=sale, M=option, A=grant)
#      - transactionShares
#      - transactionPricePerShare
#      - officerTitle / isDirector / isOfficer
#      - directOrIndirectOwnership
#   5. Filter for: P only, direct, C-suite, over threshold
#   6. Cache parsed results to avoid re-fetching same filing
# =========================================================

SEC_HEADERS = {
    "User-Agent": "ContractAlertBot/2.0 admin@contractbot.app",
    "Accept":     "application/json, text/html, application/xml",
}

def fetch_recent_form4s(ticker):
    """
    Step 1: Find recent Form 4 filings for a ticker via SEC EDGAR full-text search.
    Returns list of {accession_number, filed_date, filer_name, cik}
    """
    try:
        since = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")
        url   = (f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22"
                 f"&dateRange=custom&startdt={since}&enddt={today}&forms=4")
        req = urllib.request.Request(url, headers=SEC_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        filings = []
        for hit in data.get("hits",{}).get("hits",[]):
            src = hit.get("_source",{})
            acc = src.get("file_num","") or src.get("accession_no","")
            # Convert accession number format: 0001234567-26-000123
            raw_acc = hit.get("_id","")
            filings.append({
                "accession":  raw_acc,
                "filed":      src.get("file_date",""),
                "filer":      src.get("display_names",["Unknown"])[0],
                "cik":        src.get("entity_id",""),
            })
        return filings
    except Exception as e:
        log.debug(f"Form4 search failed for {ticker}: {e}")
        return []

def get_form4_xml_url(accession_raw, cik):
    """
    Step 2: Get the XML document URL from the filing index.
    SEC filing index: /Archives/edgar/data/{cik}/{accession}/
    """
    try:
        # Normalize accession number
        acc = accession_raw.replace("-","")
        acc_formatted = f"{acc[:10]}-{acc[10:12]}-{acc[12:]}"
        cik_padded = str(cik).zfill(10)

        # Fetch filing index JSON
        idx_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
        req = urllib.request.Request(idx_url, headers=SEC_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        # Find XML document in recent filings
        # Try direct filing index page
        filing_url = (f"https://www.sec.gov/cgi-bin/browse-edgar"
                     f"?action=getcompany&CIK={cik}&type=4"
                     f"&dateb=&owner=include&count=5&search_text=&output=atom")
        req2 = urllib.request.Request(filing_url, headers=SEC_HEADERS)
        with urllib.request.urlopen(req2, timeout=10) as r2:
            atom = r2.read().decode("utf-8")

        # Find accession numbers in atom feed
        acc_matches = re.findall(r'Accession Number.*?([0-9]{10}-[0-9]{2}-[0-9]{6})', atom)
        if not acc_matches:
            return None

        # Use the most recent accession
        latest_acc = acc_matches[0].replace("-","")
        xml_index  = (f"https://www.sec.gov/Archives/edgar/data/{cik}"
                     f"/{latest_acc}/{latest_acc}-index.htm")
        req3 = urllib.request.Request(xml_index, headers=SEC_HEADERS)
        with urllib.request.urlopen(req3, timeout=10) as r3:
            idx_html = r3.read().decode("utf-8")

        # Find the XML file
        xml_files = re.findall(r'href="([^"]+\.xml)"', idx_html, re.IGNORECASE)
        for xml_file in xml_files:
            if "form4" in xml_file.lower() or "xsl" not in xml_file.lower():
                if xml_file.startswith("/"):
                    return f"https://www.sec.gov{xml_file}"
                else:
                    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{latest_acc}/{xml_file}"

        return None
    except Exception as e:
        log.debug(f"XML URL lookup failed: {e}")
        return None

def parse_form4_xml(xml_url, ticker, filer_name, filed_date):
    """
    Step 3: Parse the Form 4 XML and extract structured transaction data.
    Returns list of validated insider buy signals.
    """
    try:
        req = urllib.request.Request(xml_url, headers=SEC_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            xml = r.read().decode("utf-8", errors="ignore")

        signals = []

        # Extract reporter info
        officer_title = ""
        is_director   = False
        is_officer    = False

        title_match = re.search(r'<officerTitle>(.*?)</officerTitle>', xml, re.IGNORECASE)
        if title_match:
            officer_title = title_match.group(1).strip()

        dir_match = re.search(r'<isDirector>(.*?)</isDirector>', xml, re.IGNORECASE)
        if dir_match:
            is_director = dir_match.group(1).strip() in ("1","true","True")

        off_match = re.search(r'<isOfficer>(.*?)</isOfficer>', xml, re.IGNORECASE)
        if off_match:
            is_officer = off_match.group(1).strip() in ("1","true","True")

        # Only process C-suite and directors
        if not is_director and not is_officer:
            return []

        title_lower = officer_title.lower()
        is_csuite = any(t in title_lower for t in [
            "chief executive","ceo","chief financial","cfo",
            "chief operating","coo","president","chairman",
            "chief technology","cto","executive vice",
        ])
        # Accept directors too but flag them differently
        role = "C-Suite" if is_csuite else "Director"

        # Parse non-derivative transactions (actual stock purchases)
        # Find all nonDerivativeTransaction blocks
        nd_blocks = re.findall(
            r'<nonDerivativeTransaction>(.*?)</nonDerivativeTransaction>',
            xml, re.DOTALL | re.IGNORECASE
        )

        for block in nd_blocks:
            # Transaction code — P = open market purchase
            code_match = re.search(r'<transactionCode>(.*?)</transactionCode>', block, re.IGNORECASE)
            if not code_match or code_match.group(1).strip() != "P":
                continue

            # Direct ownership only (D = direct, I = indirect)
            ownership_match = re.search(r'<directOrIndirectOwnership>.*?<value>(.*?)</value>', block, re.DOTALL | re.IGNORECASE)
            if ownership_match and ownership_match.group(1).strip() == "I":
                continue  # Skip indirect ownership

            # Shares
            shares_match = re.search(r'<transactionShares>.*?<value>(.*?)</value>', block, re.DOTALL | re.IGNORECASE)
            shares = 0
            if shares_match:
                try: shares = float(shares_match.group(1).strip().replace(",",""))
                except: shares = 0

            # Price per share
            price_match = re.search(r'<transactionPricePerShare>.*?<value>(.*?)</value>', block, re.DOTALL | re.IGNORECASE)
            price_per_share = 0
            if price_match:
                try: price_per_share = float(price_match.group(1).strip().replace(",",""))
                except: price_per_share = 0

            # Calculate total value
            total_value = shares * price_per_share
            if total_value < MIN_INSIDER_BUY_USD:
                continue

            # Security type
            sec_match = re.search(r'<securityTitle>.*?<value>(.*?)</value>', block, re.DOTALL | re.IGNORECASE)
            security = sec_match.group(1).strip() if sec_match else "Common Stock"

            signals.append({
                "ticker":        ticker,
                "insider":       filer_name,
                "title":         officer_title or role,
                "role":          role,
                "shares":        int(shares),
                "price":         price_per_share,
                "amount":        total_value,
                "security":      security,
                "filed":         filed_date,
                "uid":           f"INSIDER:{ticker}:{filer_name}:{filed_date}:{total_value:.0f}",
            })

        return signals

    except Exception as e:
        log.debug(f"Form4 XML parse failed for {xml_url}: {e}")
        return []

# Cache for parsed Form 4 results to avoid re-fetching
_insider_cache = {}  # uid -> parsed result

def check_insider_buys():
    """
    Scan all watchlist tickers for significant insider buys.
    Uses proper SEC XML parsing for accuracy.
    """
    log.info("Checking insider activity across watchlist...")
    alerts_sent = 0

    for ticker in INSIDER_WATCHLIST:
        try:
            # Step 1: Find recent Form 4 filings
            filings = fetch_recent_form4s(ticker)
            if not filings:
                time.sleep(0.5)
                continue

            for filing in filings[:3]:  # Check last 3 filings max
                acc      = filing["accession"]
                filed    = filing["filed"]
                filer    = filing["filer"]
                cik      = filing["cik"]

                # Check cache first
                cache_key = f"{ticker}:{acc}"
                if cache_key in _insider_cache:
                    signals = _insider_cache[cache_key]
                else:
                    # Step 2: Get XML URL
                    xml_url = get_form4_xml_url(acc, cik)
                    if not xml_url:
                        _insider_cache[cache_key] = []
                        time.sleep(0.5)
                        continue

                    # Step 3: Parse XML
                    signals = parse_form4_xml(xml_url, ticker, filer, filed)
                    _insider_cache[cache_key] = signals
                    time.sleep(0.5)  # Respectful delay for SEC servers

                # Step 4: Alert on new significant buys
                for signal in signals:
                    uid = signal["uid"]
                    if already_seen_insider(uid):
                        continue

                    log.info(f"INSIDER BUY ★ ${ticker} | {signal['insider']} ({signal['title']}) | "
                             f"{fmt_usd(signal['amount'])} | {signal['shares']:,} shares @ ${signal['price']:.2f}")

                    price, cap, currency, exchange = get_stock_info(ticker)

                    try:
                        send_insider_push(
                            ticker, signal["insider"], signal["title"],
                            signal["role"], signal["shares"], signal["price"],
                            signal["amount"], signal["security"], filed,
                            price, cap, exchange
                        )
                        alerts_sent += 1
                    except Exception as e:
                        log.error(f"Insider push failed for {ticker}: {e}")

                    mark_seen_insider(uid, ticker, signal["insider"], signal["title"], signal["amount"])

        except Exception as e:
            log.debug(f"Insider check failed for {ticker}: {e}")

        time.sleep(0.5)  # Respectful rate limiting

    log.info(f"Insider check done — {alerts_sent} alerts sent")

def get_insider_buys(ticker):
    """
    Lightweight version for contract cross-reference.
    Returns a note string if recent insider buys found, else None.
    """
    try:
        filings = fetch_recent_form4s(ticker)
        for filing in filings[:2]:
            cache_key = f"{ticker}:{filing['accession']}"
            if cache_key in _insider_cache:
                signals = _insider_cache[cache_key]
            else:
                xml_url = get_form4_xml_url(filing["accession"], filing["cik"])
                if not xml_url:
                    continue
                signals = parse_form4_xml(xml_url, ticker, filing["filer"], filing["filed"])
                _insider_cache[cache_key] = signals

            if signals:
                s = signals[0]
                return (f"{s['insider']} ({s['title']}) bought "
                        f"{s['shares']:,} shares @ ${s['price']:.2f} "
                        f"= {fmt_usd(s['amount'])} on {s['filed']}")
        return None
    except:
        return None

# =========================================================
# FETCH DoD — war.gov DIRECT (real time, 5pm Eastern daily)
# war.gov uses JavaScript rendering so we can't scrape the listing page.
# Instead we brute-force try article IDs around today's expected range.
# Known IDs: May19=4496137, May20=4496900, May21=4498916, May22=4499778
# IDs increase by ~800-2000 per day
# =========================================================

# Known war.gov article IDs — bot updates this automatically
# Format: "YYYY-MM-DD": article_id
WAR_GOV_KNOWN = {
    "2026-05-19": 4496137,
    "2026-05-20": 4496900,
    "2026-05-21": 4498916,
    "2026-05-22": 4499778,
}

def get_dod_article(dt, headers):
    """
    Find and fetch the war.gov contract page for a given date.
    Uses binary search around estimated ID — max 10 requests.
    """
    used_date = dt.strftime("%Y-%m-%d")
    date_slug = dt.strftime("%B-%-d-%Y").lower()

    # Calculate estimated ID using linear regression on known IDs
    known_dates = sorted(WAR_GOV_KNOWN.keys())
    if known_dates:
        last_known_date = known_dates[-1]
        last_known_id   = WAR_GOV_KNOWN[last_known_date]
        days_diff = (dt - datetime.strptime(last_known_date, "%Y-%m-%d")).days
        # Average 900 IDs per day
        estimated_id = last_known_id + (days_diff * 900)
    else:
        estimated_id = 4503000

    # Try IDs in expanding steps from estimate — fast binary approach
    # Try: estimate, estimate±500, estimate±1000, estimate±1500, estimate±2000
    candidates = [estimated_id]
    for step in [500, 1000, 1500, 2000, 2500, 3000]:
        candidates.extend([estimated_id + step, estimated_id - step])

    for article_id in candidates:
        if article_id < 4000000: continue
        url = f"https://www.war.gov/News/Contracts/Contract/Article/{article_id}/contracts-for-{date_slug}/"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=6) as r:
                html = r.read().decode("utf-8", errors="ignore")
            if "was awarded" in html.lower() or "is awarded" in html.lower():
                # Update our known IDs
                WAR_GOV_KNOWN[used_date] = article_id
                log.info(f"DoD: found article {article_id} for {used_date}")
                return article_id, html
        except:
            continue

    return None, None

def parse_dod_contracts(article_id, used_date, article):
    """Parse contract awards from a war.gov article page."""
    results   = []
    seen_uids = set()
    award_pattern = re.compile(
        r'([A-Z][A-Za-z0-9 &.,\-]{2,70}?),\*?\s+[A-Z][a-zA-Z .]+,\s+[A-Z]{2},?\s+(?:was awarded|is awarded|are awarded|is being awarded)\s+(?:a\s+)?(?:not-to-exceed\s+)?\$([0-9,]+(?:\.[0-9]+)?)',
        re.IGNORECASE
    )
    for match in award_pattern.finditer(article):
        company = match.group(1).strip().rstrip(",*").strip()
        if len(company) < 3 or company[0].islower():
            continue
        amt_str = match.group(2).replace(",", "")
        try:
            amount = float(amt_str)
            if amount < 1_000:
                amount *= 1_000_000
        except:
            continue
        if amount < MIN_AWARD_USD:
            continue
        uid = f"DOD:{article_id}:{company[:30]}:{amount:.0f}"
        if uid in seen_uids:
            continue
        seen_uids.add(uid)
        end  = min(len(article), match.end() + 500)
        desc = re.sub(r'<[^>]+>', '', article[match.end():end]).strip()[:200]
        results.append({
            "id":         uid,
            "recipient":  company,
            "amount":     amount,
            "amount_usd": amount,
            "currency":   "USD",
            "agency":     "Department of Defense",
            "desc":       desc,
            "awarded":    used_date,
            "expires":    "",
            "location":   "USA",
            "country":    "USA",
            "source":     "war.gov (DoD — Real Time)",
        })
    return results

def fetch_dod_awards():
    try:
        today   = datetime.now()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept":     "text/html,application/xhtml+xml",
        }
        results = []

        for dt in [today, today - timedelta(days=1)]:
            used_date = dt.strftime("%Y-%m-%d")
            cutoff    = (today - timedelta(days=2)).strftime("%Y-%m-%d")
            if used_date < cutoff:
                continue
            article_id, html = get_dod_article(dt, headers)
            if html:
                contracts = parse_dod_contracts(article_id, used_date, html)
                log.info(f"DoD: parsed {len(contracts)} contracts for {used_date}")
                results.extend(contracts)
            else:
                log.info(f"DoD: no contracts found for {used_date}")

        log.info(f"DoD: {len(results)} total contracts")
        return results

    except Exception as e:
        log.warning(f"DoD fetch failed: {e}")
        return []

# =========================================================
# FETCH USA — USASpending.gov (comprehensive, 1-2 day delay)
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
        "fields": ["Award ID","Recipient Name","Award Amount","Awarding Agency",
                   "Description","Start Date","End Date",
                   "Place of Performance City Name","Place of Performance State Code"],
        "sort": "Award Amount", "order": "desc", "limit": 100, "page": 1,
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
            "id": a.get("Award ID",""), "recipient": a.get("Recipient Name",""),
            "amount": float(a.get("Award Amount") or 0),
            "amount_usd": float(a.get("Award Amount") or 0),
            "currency": "USD", "agency": a.get("Awarding Agency",""),
            "desc": (a.get("Description") or "")[:200],
            "awarded": a.get("Start Date",""), "expires": a.get("End Date",""),
            "location": ", ".join(filter(None,[
                a.get("Place of Performance City Name",""),
                a.get("Place of Performance State Code","")])),
            "country": "USA", "source": "USASpending.gov",
        })
    return results

# =========================================================
# FETCH UK — Contracts Finder (direct)
# =========================================================

def fetch_uk_awards():
    try:
        since = (datetime.now()-timedelta(hours=LOOKBACK_HOURS)).strftime("%Y-%m-%dT%H:%M:%S")
        now   = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        url   = (f"https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"
                 f"?publishedFrom={since}&publishedTo={now}&stages=award&limit=100")
        req = urllib.request.Request(url, headers={"User-Agent":"ContractBot/1.0","Accept":"application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        fx = get_fx_rate("GBP")
        results = []
        for release in data.get("releases", []):
            for award in release.get("awards", []):
                amount_gbp = float((award.get("value") or {}).get("amount",0) or 0)
                if amount_gbp * fx < MIN_AWARD_USD: continue
                suppliers = award.get("suppliers",[{}])
                name = suppliers[0].get("name","Unknown") if suppliers else "Unknown"
                results.append({
                    "id": release.get("ocid",""), "recipient": name,
                    "amount": amount_gbp, "amount_usd": amount_gbp * fx,
                    "currency": "GBP", "agency": release.get("buyer",{}).get("name",""),
                    "desc": (release.get("tender",{}).get("description") or "")[:200],
                    "awarded": (award.get("date") or "")[:10],
                    "expires": ((award.get("contractPeriod") or {}).get("endDate") or "")[:10],
                    "location": "United Kingdom", "country": "UK",
                    "source": "Contracts Finder (UK — Direct)",
                })
        return results
    except Exception as e:
        log.warning(f"UK fetch failed: {e}")
        return []

# =========================================================
# FETCH CANADA — CanadaBuys direct CSV
# =========================================================

def fetch_canada_awards():
    try:
        fx      = get_fx_rate("CAD")
        min_cad = MIN_AWARD_USD / fx
        since   = (datetime.now()-timedelta(hours=LOOKBACK_HOURS)).strftime("%Y-%m-%d")
        url = "https://canadabuys.canada.ca/opendata/pub/2026-2027-awardNotice-avisAttribution.csv"
        req = urllib.request.Request(url, headers={"User-Agent":"ContractBot/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            content = r.read().decode("utf-8-sig")
        results = []
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            val_str = ""
            for f in ["contractValue-valeurContrat","totalValue-valeurTotale","contract_value"]:
                if row.get(f): val_str = row[f]; break
            try: amount_cad = float(str(val_str).replace(",","").replace("$","").strip() or 0)
            except: amount_cad = 0
            if amount_cad < min_cad: continue
            awarded = ""
            for f in ["publicationDate-datePublication","contractDate-dateContrat","contract_date"]:
                if row.get(f): awarded = str(row[f])[:10]; break
            if awarded and awarded < since: continue
            vendor = ""
            for f in ["vendorName-nomFournisseur","vendor_name","supplierName-nomFournisseur"]:
                if row.get(f): vendor = row[f]; break
            if not vendor: continue
            desc = ""
            for f in ["description-descriptionDuContrat","description","title-titre"]:
                if row.get(f): desc = str(row[f])[:200]; break
            ref = ""
            for f in ["referenceNumber-numeroReference","reference_number"]:
                if row.get(f): ref = row[f]; break
            if not ref: ref = str(hash(vendor+awarded))
            results.append({
                "id": ref, "recipient": vendor,
                "amount": amount_cad, "amount_usd": amount_cad * fx,
                "currency": "CAD", "agency": row.get("ownerAcronym-acronymeProprietaire",""),
                "desc": desc, "awarded": awarded, "expires": "",
                "location": "Canada", "country": "Canada",
                "source": "CanadaBuys.canada.ca (Direct)",
            })
        return results
    except Exception as e:
        log.warning(f"Canada fetch failed: {e}")
        return []

# =========================================================
# FETCH ISRAEL — OpenBudget direct API
# =========================================================

def fetch_israel_awards():
    try:
        fx      = get_fx_rate("ILS")
        min_ils = MIN_AWARD_USD / fx
        since   = (datetime.now()-timedelta(hours=LOOKBACK_HOURS)).strftime("%Y-%m-%d")
        url = (f"https://next.obudget.org/api/query?"
               f"query=SELECT%20*%20FROM%20procurement_winner_detail"
               f"%20WHERE%20start_date%3E%3D%27{since}%27"
               f"%20ORDER%20BY%20volume%20DESC%20LIMIT%20100&num_rows=100")
        req = urllib.request.Request(url, headers={"User-Agent":"ContractBot/1.0","Accept":"application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        results = []
        for a in data.get("rows", []):
            try: amount_ils = float(a.get("volume") or 0)
            except: amount_ils = 0
            if amount_ils < min_ils: continue
            results.append({
                "id": str(a.get("order_id","")), "recipient": a.get("supplier_name","Unknown"),
                "amount": amount_ils, "amount_usd": amount_ils * fx,
                "currency": "ILS", "agency": a.get("purchasing_unit_name",""),
                "desc": (a.get("description") or "")[:200],
                "awarded": str(a.get("start_date",""))[:10],
                "expires": str(a.get("end_date",""))[:10],
                "location": "Israel", "country": "Israel",
                "source": "OpenBudget.org.il (Direct)",
            })
        return results
    except Exception as e:
        log.warning(f"Israel fetch failed: {e}")
        return []

# =========================================================
# PUSH — CONTRACT ALERT
# =========================================================

def send_push(award, ticker, exchange, stock_currency, price,
              cap_raw, amount_usd, insider, deal_score, rating, reasons):
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
    if deal_score >= 70:   priority = "urgent"
    elif deal_score >= 40: priority = "high"
    else:                  priority = "default"
    title  = f"[{rating}] ${ticker} | {recipient}" if ticker else f"[{rating}] {recipient}"
    cap_str = fmt_usd(cap_raw) if cap_raw else "Unknown"
    pct_str = f"{(amt_val/cap_raw)*100:.1f}% of market cap" if cap_raw and cap_raw > 0 else ""
    lines = [
        f"DEAL SCORE: {deal_score}/100 — {rating}",
        "━━━━━━━━━━━━━━━━━━━━",
        "CONTRACT",
        f"Value    : {amount_loc} ({fmt_usd(amount_usd)} USD)",
        f"Awarded  : {awarded}",
    ]
    if expires:
        lines.append(f"Expires  : {expires}")
        years = get_contract_years(awarded, expires)
        if years > 0: lines.append(f"Duration : {years:.1f} years")
    lines += [f"Agency   : {agency}", f"Country  : {country}", f"What     : {desc}",
              "━━━━━━━━━━━━━━━━━━━━", "STOCK",
              f"Exchange : {exchange}", f"Ticker   : {ticker}"]
    if price:   lines.append(f"Price    : {price:.2f} {stock_currency or ''}")
    if cap_str: lines.append(f"Mkt Cap  : {cap_str}")
    if pct_str: lines.append(f"Impact   : {pct_str}")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("WHY THIS MATTERS")
    for r in reasons: lines.append(f"• {r}")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    if insider: lines += ["INSIDER ACTIVITY", insider, "━━━━━━━━━━━━━━━━━━━━"]
    lines += [f"Source   : {source}", f"Alert    : {alerted_at}"]
    body = "\n".join(lines)
    if country == "USA":  link = f"https://www.usaspending.gov/award/{award_id}"
    elif country == "UK": link = f"https://www.contractsfinder.service.gov.uk/Notice/{award_id}"
    else:                 link = "https://www.usaspending.gov"
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=body.encode(),
        headers={"Title":title,"Priority":priority,
                 "Tags":"money_bag,chart_with_upwards_trend","Click":link},
        method="POST",
    )
    retry(lambda: urllib.request.urlopen(req, timeout=10).close())
    log.info(f"  Pushed [{rating} {deal_score}/100]: {title}")

# =========================================================
# PUSH — INSIDER BUY ALERT
# =========================================================

def send_insider_push(ticker, insider, amount, filed, price, cap, exchange):
    cap_str    = fmt_usd(cap) if cap else "Unknown"
    alerted_at = datetime.now().strftime("%b %d %Y at %I:%M %p")
    title      = f"🔔 INSIDER BUY | ${ticker}"

    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        "INSIDER BUY DETECTED",
        f"Ticker   : ${ticker}",
        f"Insider  : {insider}",
        f"Amount   : {fmt_usd(amount)}",
        f"Filed    : {filed}",
        f"Type     : Open market purchase",
        "━━━━━━━━━━━━━━━━━━━━",
        "STOCK",
        f"Exchange : {exchange or 'NYSE/NASDAQ'}",
    ]
    if price: lines.append(f"Price    : ${price:.2f}")
    if cap_str: lines.append(f"Mkt Cap  : {cap_str}")
    lines += [
        "━━━━━━━━━━━━━━━━━━━━",
        "WHY THIS MATTERS",
        f"• Executive bought {fmt_usd(amount)} of own stock",
        "• Insiders only buy when they expect price to rise",
        "• Watch for contract announcement to follow",
        "━━━━━━━━━━━━━━━━━━━━",
        "Source   : SEC EDGAR Form 4",
        f"Alert    : {alerted_at}",
    ]
    body = "\n".join(lines)
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=body.encode(),
        headers={
            "Title":    title,
            "Priority": "high",
            "Tags":     "chart_with_upwards_trend,eyes",
            "Click":    f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={ticker}&type=4&dateb=&owner=include&count=10",
        },
        method="POST",
    )
    retry(lambda: urllib.request.urlopen(req, timeout=10).close())
    log.info(f"  Insider push sent: ${ticker} — {insider} — {fmt_usd(amount)}")

# =========================================================
# TEST PUSH
# =========================================================

def send_test_push():
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data="Contract Bot live. Monitoring war.gov, UK, Canada, Israel + insider buys.".encode(),
            headers={"Title":"Contract Bot Started","Priority":"default","Tags":"white_check_mark"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10).close()
        log.info("Test push sent")
    except Exception as e:
        log.warning(f"Test push failed: {e}")

# =========================================================
# MAIN CHECK
# =========================================================

def check():
    log.info("─" * 55)
    log.info(f"Checking all markets — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    all_awards = []
    for name, fn in [("DoD/war.gov", fetch_dod_awards),
                     ("USA",         fetch_us_awards),
                     ("UK",          fetch_uk_awards),
                     ("Canada",      fetch_canada_awards),
                     ("Israel",      fetch_israel_awards)]:
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
        if already_seen(uid): continue
        ticker, exchange, currency = find_company(award["recipient"])
        if not ticker:
            mark_seen(uid, award, award.get("amount_usd",0), award["country"], "", "", 0)
            continue
        amount_usd = award.get("amount_usd", award["amount"])
        price, cap_raw, stock_currency, _ = get_stock_info(ticker)

        # Check if this ticker also has recent insider buys — bonus signal
        insider_note = None
        insider_buys = get_insider_buys(ticker)
        if insider_buys:
            top = insider_buys[0]
            insider_note = f"Insider bought {fmt_usd(top['amount'])} on {top['filed']}"

        years = get_contract_years(award.get("awarded",""), award.get("expires",""))
        deal_score, rating, reasons = score_deal(amount_usd, cap_raw, years, insider_note)

        log.info(f"NEW ★ [{award['country']}] {award['recipient']} | "
                 f"{fmt_usd(amount_usd)} | ${ticker} | Score: {deal_score}/100 [{rating}]")

        if deal_score < MIN_DEAL_SCORE:
            log.info(f"  Skipped — score {deal_score} below minimum {MIN_DEAL_SCORE}")
            mark_seen(uid, award, amount_usd, award["country"], ticker, exchange, deal_score)
            continue

        try:
            send_push(award, ticker, exchange, stock_currency, price,
                      cap_raw, amount_usd, insider_note, deal_score, rating, reasons)
        except Exception as e:
            log.error(f"Push failed: {e}")

        mark_seen(uid, award, amount_usd, award["country"], ticker, exchange, deal_score)
        new_count += 1

    log.info(f"Done — {new_count} new contract alerts sent")

    # Check insider buys independently
    try:
        check_insider_buys()
    except Exception as e:
        log.error(f"Insider check failed: {e}")

# =========================================================
# MAIN LOOP
# =========================================================

def run_bot():
    send_test_push()
    while True:
        try:
            check()
        except Exception as e:
            log.error(f"Check error: {e}")
        log.info(f"Sleeping {CHECK_MINUTES} minutes until next check...")
        time.sleep(CHECK_MINUTES * 60)

# =========================================================
# START
# =========================================================

print("=" * 55)
print("  GLOBAL CONTRACT ALERT BOT")
print("=" * 55)
print(f"  Sources    : war.gov + USASpending + UK + Canada + Israel")
print(f"  Insider    : {len(INSIDER_WATCHLIST)} tickers monitored")
print(f"  Min award  : {fmt_usd(MIN_AWARD_USD)}")
print(f"  Min insider: {fmt_usd(MIN_INSIDER_BUY_USD)}")
print(f"  Min score  : {MIN_DEAL_SCORE}/100")
print(f"  Interval   : every {CHECK_MINUTES} minutes")
print(f"  ntfy       : ntfy.sh/{NTFY_TOPIC}")
print("=" * 55)

bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()

start_web_server()
