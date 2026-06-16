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
import hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta

# =========================================================
# SETTINGS
# =========================================================

NTFY_TOPIC          = "my-contract-alerts"
MIN_AWARD_USD       = 25_000_000  # % of cap does the real filtering
CHECK_MINUTES       = 15
DATABASE            = "contracts.db"
MIN_DEAL_SCORE      = 25
MIN_INSIDER_BUY_USD = 250_000

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")]
)
log = logging.getLogger(__name__)

# =========================================================
# HEALTH SERVER
# =========================================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/reset":
            with DB_LOCK:
                DB.execute("DELETE FROM seen_awards")
                DB.commit()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Reset done.")
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(f"Bot running. {datetime.now()}".encode())
    def log_message(self, *a): pass

def start_web_server():
    HTTPServer(("0.0.0.0", 8080), HealthHandler).serve_forever()

# =========================================================
# KNOWN COMPANIES
# =========================================================

KNOWN = {
    # Booz Allen Hamilton
    "Booz Allen":                           "BAH",
    # Leidos
    "Leidos":                               "LDOS",
    "Leidos Biomedical":                    "LDOS",
    "Leidos Holdings":                      "LDOS",
    # SAIC
    "SAIC":                                 "SAIC",
    "Science Applications":                 "SAIC",
    # Parsons
    "Parsons":                              "PSN",
    # Palantir
    "Palantir":                             "PLTR",
    # Accenture
    "Accenture":                            "ACN",
    # RTX / Raytheon
    "Raytheon":                             "RTX",
    "RTX Corp":                             "RTX",
    "Pratt and Whitney":                    "RTX",
    "Pratt & Whitney":                      "RTX",
    "Collins Aerospace":                    "RTX",
    # Northrop Grumman
    "Northrop Grumman":                     "NOC",
    "Northrop Grumman Mission Systems":     "NOC",
    "Northrop Grumman Space Systems":       "NOC",
    "Northrop Grumman Aeronautics":         "NOC",
    # Lockheed Martin
    "Lockheed Martin":                      "LMT",
    "Lockheed":                             "LMT",
    "LM Aero":                              "LMT",
    "Sikorsky":                             "LMT",
    "Lockheed Martin Aeronautics":          "LMT",
    "Lockheed Martin Rotary":               "LMT",
    "Lockheed Martin Space":                "LMT",
    "Lockheed Martin Missiles":             "LMT",
    # L3Harris
    "L3Harris":                             "LHX",
    "L3 Harris":                            "LHX",
    "Aerojet":                              "LHX",
    # General Dynamics
    "General Dynamics":                     "GD",
    "General Dynamics Information":         "GD",
    "General Dynamics Mission":             "GD",
    "General Dynamics Land":                "GD",
    "General Dynamics Ordnance":            "GD",
    # Textron
    "Textron":                              "TXT",
    "Bell Textron":                         "TXT",
    "Bell Helicopter":                      "TXT",
    # Mercury Systems
    "Mercury Systems":                      "MRCY",
    # Kratos
    "Kratos":                               "KTOS",
    # Leonardo DRS
    "Leonardo DRS":                         "DRS",
    # Curtiss-Wright
    "Curtiss-Wright":                       "CW",
    # KBR
    "KBR":                                  "KBR",
    "KBR Wyle":                             "KBR",
    # Fluor
    "Fluor":                                "FLR",
    "Fluor Marine":                         "FLR",
    "Fluor Federal":                        "FLR",
    # Jacobs
    "Jacobs":                               "J",
    # Tetra Tech
    "Tetra Tech":                           "TTEK",
    # AECOM
    "AECOM":                                "ACM",
    # Maximus
    "Maximus":                              "MMS",
    "Maximus Federal":                      "MMS",
    # ICF
    "ICF":                                  "ICFI",
    # CACI
    "CACI":                                 "CACI",
    # Heico
    "Heico":                                "HEI",
    # BWX Technologies
    "BWX Technologies":                     "BWXT",
    "BWXT":                                 "BWXT",
    # Rocket Lab
    "Rocket Lab":                           "RKLB",
    # VSE Corporation
    "VSE Corporation":                      "VSEC",
    "VSE Corp":                             "VSEC",
    # IBM
    "IBM":                                  "IBM",
    # Honeywell
    "Honeywell":                            "HON",
    "Honeywell Federal":                    "HON",
    # General Electric
    "General Electric":                     "GE",
    "GE Aerospace":                         "GE",
    # GE HealthCare
    "GE HealthCare":                        "GEHC",
    # Boeing
    "Boeing":                               "BA",
    "The Boeing":                           "BA",
    # Huntington Ingalls
    "Huntington Ingalls":                   "HII",
    "Huntington-Ingalls":                   "HII",
    "Newport News Shipbuilding":            "HII",
    "Ingalls Shipbuilding":                 "HII",
    # Humana
    "Humana":                               "HUM",
    # Oracle
    "Oracle":                               "ORCL",
    "Oracle Health":                        "ORCL",
    # Microsoft
    "Microsoft":                            "MSFT",
    # Amazon
    "Amazon":                               "AMZN",
    "Amazon Web Services":                  "AMZN",
    "AWS":                                  "AMZN",
    # Google / Alphabet
    "Alphabet":                             "GOOGL",
    "Google":                               "GOOGL",
    # Amentum
    "Amentum":                              "AMTM",
    # Spirit AeroSystems
    "Spirit AeroSystems":                   "SPR",
    # Elbit Systems
    "Elbit Systems":                        "ESLT",
    # CyberArk
    "CyberArk":                             "CYBR",
    # Check Point
    "Check Point":                          "CHKP",
}

INSIDER_WATCHLIST = [
    "KTOS","MRCY","DRS","PSN","RKLB","VSEC","LDOS","BAH","SAIC",
    "CACI","LMT","NOC","RTX","GD","LHX","HII","KBR","TTEK",
    "ACM","PLTR","HON","GE","GEHC","BA","BWXT","CW","HEI",
    "ICFI","MMS","SPR","FLR","IBM","AMTM","ESLT","CYBR","CHKP",
]

# =========================================================
# DATABASE
# =========================================================

def init_db():
    db = sqlite3.connect(DATABASE, check_same_thread=False)
    db.execute("""CREATE TABLE IF NOT EXISTS seen_awards (
        uid TEXT PRIMARY KEY, recipient TEXT, amount_usd REAL,
        agency TEXT, country TEXT, ticker TEXT, deal_score REAL, seen_at TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS seen_insider (
        uid TEXT PRIMARY KEY, ticker TEXT, insider_name TEXT,
        title TEXT, amount_usd REAL, seen_at TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS seen_8k (
        uid TEXT PRIMARY KEY, ticker TEXT, filed TEXT, seen_at TEXT)""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_sa ON seen_awards(seen_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_si ON seen_insider(seen_at)")
    db.commit()
    return db

DB      = init_db()
DB_LOCK = threading.Lock()

def already_seen(uid):
    with DB_LOCK:
        return DB.execute("SELECT 1 FROM seen_awards WHERE uid=?", (uid,)).fetchone() is not None

def already_seen_insider(uid):
    with DB_LOCK:
        return DB.execute("SELECT 1 FROM seen_insider WHERE uid=?", (uid,)).fetchone() is not None

def mark_seen(uid, recipient, amount_usd, agency, country, ticker, score):
    with DB_LOCK:
        DB.execute("INSERT OR IGNORE INTO seen_awards VALUES (?,?,?,?,?,?,?,?)",
            (uid, recipient, amount_usd, agency, country, ticker, score,
             datetime.now().isoformat()))
        DB.commit()

def mark_seen_insider(uid, ticker, name, title, amount):
    with DB_LOCK:
        DB.execute("INSERT OR IGNORE INTO seen_insider VALUES (?,?,?,?,?,?)",
            (uid, ticker, name, title, amount, datetime.now().isoformat()))
        DB.commit()

def cleanup_old():
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()
    with DB_LOCK:
        DB.execute("DELETE FROM seen_awards WHERE seen_at < ?", (cutoff,))
        DB.execute("DELETE FROM seen_insider WHERE seen_at < ?", (cutoff,))
        DB.execute("DELETE FROM seen_8k WHERE seen_at < ?", (cutoff,))
        DB.commit()
    log.info("DB cleanup done")

# =========================================================
# HELPERS
# =========================================================

def fmt_usd(n):
    v = float(n or 0)
    if v >= 1e9: return f"${v/1e9:.2f}B"
    if v >= 1e6: return f"${v/1e6:.2f}M"
    return f"${v/1e3:.0f}K"

def find_ticker(name):
    nl = name.lower()
    for company, ticker in KNOWN.items():
        if company.lower() in nl:
            return ticker
    return None

def get_years(awarded, expires):
    try:
        s = datetime.strptime(awarded[:10], "%Y-%m-%d")
        e = datetime.strptime(expires[:10], "%Y-%m-%d")
        return max((e - s).days / 365.25, 0)
    except:
        return 0

# =========================================================
# STOCK INFO — quoteSummary for reliable marketCap
# =========================================================

_stock_cache = {}

def get_stock_info(ticker):
    if ticker in _stock_cache:
        price, cap, ts = _stock_cache[ticker]
        if (datetime.now() - ts).total_seconds() < 600:
            return price, cap
    # Try Yahoo Finance
    try:
        url = (f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
               f"?modules=price")
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        p     = data["quoteSummary"]["result"][0]["price"]
        price = p.get("regularMarketPrice", {}).get("raw", 0)
        cap   = p.get("marketCap", {}).get("raw", 0)
        if cap and cap > 0:
            _stock_cache[ticker] = (price, cap, datetime.now())
            return price, cap
    except:
        pass
    # Use hardcoded market cap if Yahoo fails
    cap = MARKET_CAPS.get(ticker, 0)
    _stock_cache[ticker] = (0, cap, datetime.now())
    return None, cap


# Hardcoded market caps (approximate, update monthly)
# Source: as of June 2026
MARKET_CAPS = {
    "LMT":  110_000_000_000,
    "RTX":   95_000_000_000,
    "NOC":   70_000_000_000,
    "GD":    75_000_000_000,
    "BA":    95_000_000_000,
    "HII":    8_000_000_000,
    "LHX":   20_000_000_000,
    "TXT":   16_000_000_000,
    "LDOS":  20_000_000_000,
    "BAH":   14_000_000_000,
    "SAIC":   6_000_000_000,
    "CACI":   6_500_000_000,
    "PSN":    6_000_000_000,
    "PLTR":  300_000_000_000,
    "ACN":   200_000_000_000,
    "KTOS":    3_000_000_000,
    "MRCY":    1_500_000_000,
    "DRS":     3_500_000_000,
    "CW":      3_500_000_000,
    "KBR":     7_000_000_000,
    "FLR":     5_000_000_000,
    "J":      16_000_000_000,
    "TTEK":    5_500_000_000,
    "ACM":     9_000_000_000,
    "MMS":     4_500_000_000,
    "ICFI":    1_800_000_000,
    "HEI":    22_000_000_000,
    "BWXT":    6_000_000_000,
    "RKLB":    8_000_000_000,
    "VSEC":    1_200_000_000,
    "IBM":   150_000_000_000,
    "HON":   130_000_000_000,
    "GE":    170_000_000_000,
    "GEHC":   40_000_000_000,
    "HUM":    30_000_000_000,
    "ORCL":  400_000_000_000,
    "MSFT": 3_000_000_000_000,
    "AMZN": 2_000_000_000_000,
    "GOOGL":2_000_000_000_000,
    "AMTM":   5_000_000_000,
    "SPR":      900_000_000,
    "ESLT":   10_000_000_000,
    "CYBR":   15_000_000_000,
    "CHKP":   18_000_000_000,
    "TGI":       400_000_000,
}

# =========================================================
# SCORING
# =========================================================

def score_deal(amount_usd, market_cap, years):
    score = 0
    has_cap = market_cap and market_cap > 0

    if has_cap:
        pct = (amount_usd / market_cap) * 100
        # Only meaningful if contract is at least 1% of market cap
        if   pct >= 50: score += 70
        elif pct >= 25: score += 55
        elif pct >= 10: score += 40
        elif pct >= 5:  score += 30
        elif pct >= 2:  score += 22
        elif pct >= 1:  score += 15
        else:           score += 0  # less than 1% — not interesting
    else:
        # No market cap — only score very large contracts
        if   amount_usd >= 1_000_000_000: score += 35  # $1B+
        elif amount_usd >= 500_000_000:   score += 25  # $500M+
        elif amount_usd >= 100_000_000:   score += 15  # $100M+
        else:                             score += 0   # skip small unknown caps

    # Duration bonus
    if   years >= 5: score += 10
    elif years >= 3: score += 7
    elif years >= 2: score += 4
    elif years >= 1: score += 2

    score = min(score, 100)
    if   score >= 70: rating = "STRONG BUY"
    elif score >= 50: rating = "HIGH VALUE"
    elif score >= 30: rating = "NOTABLE"
    elif score >= 15: rating = "WATCH"
    else:             rating = "LOW IMPACT"
    return score, rating

# =========================================================
# PUSH
# =========================================================

def ntfy(title, body, priority="default", tags="money_bag", link=None):
    headers = {
        "Title":        title.encode("ascii", "ignore").decode("ascii"),
        "Priority":     priority,
        "Tags":         tags,
        "Content-Type": "text/plain; charset=utf-8",
    }
    if link:
        headers["Click"] = link
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=body.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10).close()

def send_contract_alert(award, ticker, score, rating, price, cap):
    amt     = float(award.get("amount_usd", 0))
    agency  = award.get("agency", "")[:40]
    country = award.get("country", "")
    awarded = award.get("awarded", "")
    expires = award.get("expires", "")
    name    = award.get("recipient", "")

    clean = name
    for s in [", INC.", ", LLC", ", L.P.", " INC", " LLC", " CORP",
              " FEDERAL", " FEDERAL SERVICES", " GOVERNMENT SERVICES",
              " INFORMATION TECHNOLOGY, INC.", " SYSTEMS CORPORATION"]:
        clean = clean.replace(s, "")
    clean = clean.strip().title()

    pct_str = f" • {(amt/cap)*100:.1f}% of cap" if cap else ""
    dur_str = ""
    if expires:
        yrs = get_years(awarded, expires)
        if yrs >= 1:
            dur_str = f" • {yrs:.0f}yr"

    if   score >= 70: priority = "urgent"
    elif score >= 40: priority = "high"
    else:             priority = "default"

    title = f"[{rating}] ${ticker} - {fmt_usd(amt)}"
    body  = (
        f"Company: {clean}\n"
        f"Agency:  {agency} | {country}\n"
        f"Score:   {score}/100{pct_str}{dur_str}\n"
        f"Awarded: {awarded}"
    )
    body = body.replace("\u2014","-").replace("\u2013","-").replace("\u2019","'")

    q    = urllib.parse.quote(f"{name} {agency} contract {awarded}")
    link = (f"https://www.contractsfinder.service.gov.uk/Notice/{award.get('id','')}"
            if country == "UK" else f"https://www.google.com/search?q={q}")

    ntfy(title, body, priority, "money_bag", link)
    log.info(f"  ALERT [{rating} {score}]: ${ticker} {fmt_usd(amt)}")

def send_insider_alert(ticker, name, title, role, shares, price_paid, amount, stock_price):
    price_paid   = price_paid or 0
    stock_price  = stock_price or 0

    if   "ceo" in title.lower() or "chief executive" in title.lower(): priority = "urgent"
    elif "chief" in title.lower() or "president" in title.lower():     priority = "high"
    else:                                                                priority = "high"

    vs = ""
    if stock_price and price_paid:
        pct = ((stock_price - price_paid) / price_paid) * 100
        vs  = f" | now {pct:+.1f}%"

    push_title = f"INSIDER BUY - ${ticker} [{role}]"
    body = (
        f"{name} ({title})\n"
        f"{shares:,} shares @ ${price_paid:.2f} = {fmt_usd(amount)}{vs}"
    )
    link = (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
            f"&company={ticker}&type=4&dateb=&owner=include&count=10")
    ntfy(push_title, body, priority, "rotating_light", link)
    log.info(f"  INSIDER: ${ticker} {name} {fmt_usd(amount)}")

# =========================================================
# DOD — globalsecurity.org mirrors war.gov same day ~7pm Eastern
# =========================================================

GLOBALSECURITY_KNOWN = {
    "2026-06-01": 4505747,
    "2026-06-02": 4506825,
    "2026-06-03": 4507838,
    "2026-06-05": 4510415,
    "2026-06-06": 4511381,
}

DOD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "text/html,application/xhtml+xml",
}

def fetch_dod_page(dt):
    used_date = dt.strftime("%Y-%m-%d")
    ym        = dt.strftime("%Y/%m")

    # Fast path — known ID
    if used_date in GLOBALSECURITY_KNOWN:
        article_id = GLOBALSECURITY_KNOWN[used_date]
        url = (f"https://www.globalsecurity.org/military/library/news/"
               f"{ym}/dod-contracts_{article_id}.htm")
        try:
            req = urllib.request.Request(url, headers=DOD_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                html = r.read().decode("utf-8", errors="ignore")
            if "was awarded" in html.lower():
                log.info(f"DoD: fetched {used_date} (id={article_id})")
                return html, used_date
        except Exception as e:
            log.warning(f"DoD known ID failed {used_date}: {e}")

    # Scan — estimate ID from last known, check ±2000 in steps of 50
    known_dates = sorted(GLOBALSECURITY_KNOWN.keys())
    if known_dates:
        last_date = datetime.strptime(known_dates[-1], "%Y-%m-%d")
        last_id   = GLOBALSECURITY_KNOWN[known_dates[-1]]
        days_diff = (dt - last_date).days
        estimated = int(last_id + days_diff * 800)
    else:
        estimated = 4512000

    log.info(f"DoD: scanning for {used_date} near ID {estimated}")
    for delta in range(0, 2000, 50):
        for article_id in [estimated + delta, estimated - delta]:
            if article_id < 4000000:
                continue
            url = (f"https://www.globalsecurity.org/military/library/news/"
                   f"{ym}/dod-contracts_{article_id}.htm")
            try:
                req = urllib.request.Request(url, headers=DOD_HEADERS)
                with urllib.request.urlopen(req, timeout=4) as r:
                    html = r.read().decode("utf-8", errors="ignore")
                # Confirm it's actually this date's page
                if "was awarded" in html.lower() and used_date[5:] in html:
                    GLOBALSECURITY_KNOWN[used_date] = article_id
                    log.info(f"DoD: found {used_date} at id={article_id}")
                    return html, used_date
            except:
                continue
    log.info(f"DoD: no page yet for {used_date}")
    return None, used_date

def parse_dod_html(html, used_date):
    results = []
    seen    = set()
    pattern = re.compile(
        r'([A-Z][A-Za-z0-9 &.,\-]{2,70}?),\*?\s+[A-Z][a-zA-Z .]+,\s+[A-Z]{2},?\s+'
        r'(?:was awarded|is awarded|are awarded|is being awarded)\s+'
        r'(?:a\s+)?(?:not-to-exceed\s+)?\$([0-9,]+(?:\.[0-9]+)?)',
        re.IGNORECASE
    )
    matches = list(pattern.finditer(html))
    log.info(f"DoD: {len(matches)} raw pattern matches for {used_date}")
    for m in matches:
        company = m.group(1).strip().rstrip(",*").strip()
        if len(company) < 3 or company[0].islower():
            continue
        try:
            amount = float(m.group(2).replace(",", ""))
            if amount < 1000:
                amount *= 1_000_000
        except:
            continue
        if amount < MIN_AWARD_USD:
            continue
        uid = hashlib.sha256(
            f"DOD|{company}|{amount:.0f}|{used_date}".encode()
        ).hexdigest()
        if uid in seen:
            continue
        seen.add(uid)
        end  = min(len(html), m.end() + 300)
        desc = re.sub(r'<[^>]+>', '', html[m.end():end]).strip()[:150]
        results.append({
            "uid": uid, "recipient": company,
            "amount": amount, "amount_usd": amount,
            "agency": "Dept of Defense", "desc": desc,
            "awarded": used_date, "expires": "",
            "country": "USA", "source": "war.gov/globalsecurity.org",
        })
    return results

def fetch_dod_awards():
    results = []
    today   = datetime.now()
    for dt in [today, today - timedelta(days=1)]:
        if dt.weekday() >= 5:
            continue
        html, used_date = fetch_dod_page(dt)
        if html:
            parsed = parse_dod_html(html, used_date)
            log.info(f"DoD: {len(parsed)} contracts for {used_date}")
            results.extend(parsed)
    return results

# =========================================================
# USA — USASpending.gov transactions endpoint
# Uses action_date — when the contract action actually occurred
# This is the correct field for "new contracts awarded today"
# =========================================================

def fetch_us_awards():
    try:
        end   = datetime.now()
        start = end - timedelta(hours=48)
        payload = json.dumps({
            "filters": {
                "award_type_codes": ["A","B","C","D"],
                "time_period": [{"start_date": start.strftime("%Y-%m-%d"),
                                 "end_date":   end.strftime("%Y-%m-%d")}],
                "award_amounts": [{"lower_bound": MIN_AWARD_USD}],
            },
            "fields": ["Award ID","Recipient Name","Award Amount","Awarding Agency",
                       "Description","Start Date","End Date","Award Date"],
            "sort": "Start Date", "order": "desc", "limit": 100, "page": 1,
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
        page = 1
        while page <= 2:  # max 2 pages = 200 contracts
            payload_obj = json.loads(payload)
            payload_obj["page"] = page
            req = urllib.request.Request(
                "https://api.usaspending.gov/api/v2/search/spending_by_award/",
                data=json.dumps(payload_obj).encode() if isinstance(payload_obj, dict) else payload_obj,
                headers={"Content-Type":"application/json","User-Agent":"ContractBot/1.0"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
            page_results = data.get("results", [])
            if not page_results:
                break
            for a in page_results:
                amt = float(a.get("Award Amount") or 0)
                if amt < MIN_AWARD_USD:
                    continue
                # Hard date filter — reject contracts not recently awarded
                award_date = a.get("Award Date","") or a.get("Start Date","")
                if award_date:
                    try:
                        awarded_dt = datetime.strptime(award_date[:10], "%Y-%m-%d")
                        if (datetime.now() - awarded_dt).days > 7:
                            continue  # silently skip old contracts
                    except:
                        pass
                # Skip obvious IDIQ/modification keywords
                desc_lower = (a.get("Description") or "").lower()
                if any(x in desc_lower for x in ["idiq", "indefinite delivery",
                                                   "task order", "delivery order"]):
                    continue
                uid = hashlib.sha256(
                    f"USA|{a.get('Recipient Name','')}|{amt:.0f}|{a.get('Start Date','')}".encode()
                ).hexdigest()
                results.append({
                    "uid":        uid,
                    "recipient":  a.get("Recipient Name",""),
                    "amount":     amt,
                    "amount_usd": amt,
                    "agency":     a.get("Awarding Agency",""),
                    "desc":       (a.get("Description") or "")[:150],
                    "awarded":    a.get("Start Date",""),
                    "expires":    a.get("End Date",""),
                    "country":    "USA",
                    "source":     "USASpending.gov",
                })
            if len(page_results) < 100:
                break  # last page
            page += 1
        log.info(f"USA: {len(results)} contracts ({page-1} pages)")
        return results
    except Exception as e:
        log.warning(f"USASpending failed: {e}")
        return []

# =========================================================
# SEC INSIDER — Form 4 XML parser
# =========================================================

SEC_HEADERS = {
    "User-Agent": "ContractAlertBot/2.0 admin@contractbot.app",
    "Accept":     "application/json, text/html, application/xml",
}

_insider_cache = {}

def fetch_form4s(ticker):
    try:
        since = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")
        url   = (f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22"
                 f"&dateRange=custom&startdt={since}&enddt={today}&forms=4")
        req = urllib.request.Request(url, headers=SEC_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        out = []
        for hit in data.get("hits", {}).get("hits", []):
            src = hit.get("_source", {})
            out.append({
                "accession": hit.get("_id", ""),
                "filed":     src.get("file_date", ""),
                "filer":     src.get("display_names", ["Unknown"])[0],
                "cik":       src.get("entity_id", ""),
            })
        return out
    except Exception as e:
        log.debug(f"Form4 search failed {ticker}: {e}")
        return []

def get_xml_url(accession, cik):
    try:
        acc = accession.replace("-","").replace(":","")
        if len(acc) == 18:
            dashed = f"{acc[:10]}-{acc[10:12]}-{acc[12:]}"
        else:
            dashed = re.sub(r'(\d{10})(\d{2})(\d{6})', r'\1-\2-\3', acc)
        idx_url = (f"https://www.sec.gov/Archives/edgar/data"
                   f"/{cik}/{acc}/{dashed}-index.htm")
        req = urllib.request.Request(idx_url, headers=SEC_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode("utf-8", errors="ignore")
        for link in re.findall(r'href="([^"]*\.xml)"', html, re.IGNORECASE):
            if "xsl" in link.lower() or "stylesheet" in link.lower():
                continue
            if link.startswith("http"):  return link
            if link.startswith("/"):     return f"https://www.sec.gov{link}"
            return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{link}"
        return None
    except:
        return None

def parse_form4(xml_url, ticker, filer, filed):
    try:
        req = urllib.request.Request(xml_url, headers=SEC_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            xml = r.read().decode("utf-8", errors="ignore")

        def tag(name):
            m = re.search(rf'<{name}>(.*?)</{name}>', xml, re.IGNORECASE)
            return m.group(1).strip() if m else ""

        is_dir = tag("isDirector") in ("1","true","True")
        is_off = tag("isOfficer")  in ("1","true","True")
        if not is_dir and not is_off:
            return []

        officer_title = tag("officerTitle")
        tl = officer_title.lower()
        if any(t in tl for t in ["chief executive","ceo"]):          role = "CEO"
        elif any(t in tl for t in ["chief","president","cfo","coo"]): role = "C-Suite"
        else:                                                          role = "Director"

        signals = []
        for block in re.findall(
                r'<nonDerivativeTransaction>(.*?)</nonDerivativeTransaction>',
                xml, re.DOTALL | re.IGNORECASE):
            code = re.search(r'<transactionCode>(.*?)</transactionCode>',
                             block, re.IGNORECASE)
            if not code or code.group(1).strip() != "P":
                continue
            own = re.search(
                r'<directOrIndirectOwnership>.*?<value>(.*?)</value>',
                block, re.DOTALL | re.IGNORECASE)
            if own and own.group(1).strip() == "I":
                continue

            def val(tag_name):
                m = re.search(
                    rf'<{tag_name}>.*?<value>(.*?)</value>',
                    block, re.DOTALL | re.IGNORECASE)
                if m:
                    try: return float(m.group(1).strip().replace(",",""))
                    except: pass
                return 0.0

            shares    = val("transactionShares")
            price_per = val("transactionPricePerShare")
            total     = shares * price_per
            if total < MIN_INSIDER_BUY_USD:
                continue

            uid = f"INSIDER:{ticker}:{filer}:{filed}:{total:.0f}"
            signals.append({
                "ticker": ticker, "filer": filer,
                "title":  officer_title or role, "role": role,
                "shares": int(shares), "price": price_per,
                "amount": total, "filed": filed, "uid": uid,
            })
        return signals
    except Exception as e:
        log.debug(f"Form4 parse failed {xml_url}: {e}")
        return []

def check_insiders():
    log.info("Checking insider buys...")
    sent = 0
    for ticker in INSIDER_WATCHLIST:
        try:
            for filing in fetch_form4s(ticker)[:3]:
                key = f"{ticker}:{filing['accession']}"
                if key in _insider_cache:
                    signals = _insider_cache[key]
                else:
                    xml_url = get_xml_url(filing["accession"], filing["cik"])
                    signals = (parse_form4(xml_url, ticker, filing["filer"], filing["filed"])
                               if xml_url else [])
                    _insider_cache[key] = signals
                    time.sleep(0.3)

                for s in signals:
                    if already_seen_insider(s["uid"]):
                        continue
                    price, _ = get_stock_info(ticker)
                    log.info(f"INSIDER ★ ${ticker} {s['filer']} ({s['role']}) {fmt_usd(s['amount'])}")
                    try:
                        send_insider_alert(
                            ticker, s["filer"], s["title"], s["role"],
                            s["shares"], s["price"], s["amount"], price)
                        sent += 1
                    except Exception as e:
                        log.error(f"Insider push failed: {e}")
                    mark_seen_insider(s["uid"], ticker, s["filer"],
                                      s["title"], s["amount"])
        except Exception as e:
            log.warning(f"Insider check failed {ticker}: {e}")
        time.sleep(0.3)
    log.info(f"Insider check done — {sent} sent")



# Reverse map for SEC search — company name → better results than ticker symbol
TICKER_TO_NAME = {
    "BAH":  "Booz Allen Hamilton",
    "LDOS": "Leidos",
    "SAIC": "Science Applications International",
    "LMT":  "Lockheed Martin",
    "NOC":  "Northrop Grumman",
    "RTX":  "Raytheon Technologies",
    "GD":   "General Dynamics",
    "LHX":  "L3Harris Technologies",
    "HII":  "Huntington Ingalls",
    "BA":   "Boeing",
    "KTOS": "Kratos Defense",
    "MRCY": "Mercury Systems",
    "CACI": "CACI International",
    "PSN":  "Parsons Corporation",
    "PLTR": "Palantir Technologies",
    "RKLB": "Rocket Lab",
    "AMTM": "Amentum",
    "FLR":  "Fluor Corporation",
    "KBR":  "KBR Inc",
    "ACM":  "AECOM",
    "BWXT": "BWX Technologies",
    "VSEC": "VSE Corporation",
    "MMS":  "Maximus Inc",
    "HON":  "Honeywell International",
    "IBM":  "International Business Machines",
}

# =========================================================
# SEC 8-K MONITORING — Contract award press releases
# Companies must file 8-K for material contracts
# Filed within 4 business days — faster than USASpending
# =========================================================

_8k_cache = {}

def fetch_8k_filings():
    """Check recent 8-K filings for contract award announcements"""
    results = []
    tickers_to_check = list(set(KNOWN.values()))  # unique tickers only

    for ticker in tickers_to_check:
        try:
            since = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
            today = datetime.now().strftime("%Y-%m-%d")
            # Search by company name for better SEC coverage
            company_name = TICKER_TO_NAME.get(ticker, ticker)
            encoded_name = urllib.parse.quote(f'"{company_name}"')
            url   = (f"https://efts.sec.gov/LATEST/search-index?q={encoded_name}"
                     f"&dateRange=custom&startdt={since}&enddt={today}&forms=8-K")
            req = urllib.request.Request(url, headers=SEC_HEADERS)
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read())

            for hit in data.get("hits", {}).get("hits", [])[:3]:
                src       = hit.get("_source", {})
                accession = hit.get("_id", "")
                filed     = src.get("file_date", "")
                cache_key = f"8K:{ticker}:{accession}"

                uid_8k = hashlib.sha256(f"8K|{ticker}|{accession}".encode()).hexdigest()
                with DB_LOCK:
                    already = DB.execute("SELECT 1 FROM seen_8k WHERE uid=?", (uid_8k,)).fetchone()
                if already:
                    continue
                # Mark seen immediately to prevent duplicate processing
                with DB_LOCK:
                    DB.execute("INSERT OR IGNORE INTO seen_8k VALUES (?,?,?,?)",
                               (uid_8k, ticker, filed, datetime.now().isoformat()))
                    DB.commit()

                # Fetch the 8-K filing text to check for contract language
                cik = src.get("entity_id","")
                if not cik: continue

                acc = accession.replace("-","").replace(":","")
                if len(acc) == 18:
                    dashed = f"{acc[:10]}-{acc[10:12]}-{acc[12:]}"
                else:
                    continue

                idx_url = (f"https://www.sec.gov/Archives/edgar/data"
                           f"/{cik}/{acc}/{dashed}-index.htm")
                try:
                    req2 = urllib.request.Request(idx_url, headers=SEC_HEADERS)
                    with urllib.request.urlopen(req2, timeout=8) as r2:
                        idx_html = r2.read().decode("utf-8", errors="ignore")
                except:
                    continue

                # Find the main 8-K document — prefer files with "8k" in name
                all_links = re.findall(r'href="([^"]*\.htm[l]?)"', idx_html, re.IGNORECASE)
                # Sort: prefer links with "8k" or "8-k" in filename, exclude index files
                def link_priority(l):
                    ll = l.lower()
                    if "index" in ll: return 3
                    if "8k" in ll or "8-k" in ll: return 0
                    return 1
                all_links.sort(key=link_priority)
                text = ""
                for link in all_links[:5]:
                    if "index" in link.lower(): continue
                    full_url = (link if link.startswith("http")
                                else f"https://www.sec.gov{link}" if link.startswith("/")
                                else f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{link}")
                    try:
                        req3 = urllib.request.Request(full_url, headers=SEC_HEADERS)
                        with urllib.request.urlopen(req3, timeout=8) as r3:
                            text = r3.read().decode("utf-8", errors="ignore")
                        if len(text) > 500:  # got real content
                            break
                    except:
                        continue

                if not text: continue

                # Check for contract-related language
                text_lower = text.lower()
                contract_keywords = [
                    "was awarded", "contract award", "awarded a contract",
                    "government contract", "federal contract", "defense contract",
                    "department of defense", "department of the army",
                    "department of the navy", "air force contract",
                ]
                if not any(kw in text_lower for kw in contract_keywords):
                    continue

                # Extract contract amount — search near contract keywords only
                # This avoids false positives from revenue/backlog/debt figures
                amt = 0
                # Look for patterns like "awarded a $500 million contract" or "$1.2 billion contract"
                contract_amount_patterns = [
                    r'awarded[^$]{0,50}\$([0-9,]+(?:\.[0-9]+)?)\s*(million|billion)',
                    r'contract[^$]{0,30}\$([0-9,]+(?:\.[0-9]+)?)\s*(million|billion)',
                    r'\$([0-9,]+(?:\.[0-9]+)?)\s*(million|billion)[^.]{0,50}contract',
                    r'\$([0-9,]+(?:\.[0-9]+)?)\s*(million|billion)[^.]{0,50}award',
                ]
                for pat in contract_amount_patterns:
                    for m in re.finditer(pat, text_lower):
                        try:
                            v = float(m.group(1).replace(",",""))
                            mult = 1_000_000_000 if m.group(2) == "billion" else 1_000_000
                            v *= mult
                            if v > amt:
                                amt = v
                        except:
                            continue
                    if amt >= MIN_AWARD_USD:
                        break

                if amt < MIN_AWARD_USD: continue

                uid = hashlib.sha256(f"8K|{ticker}|{accession}".encode()).hexdigest()
                company_name = src.get("display_names", [ticker])[0]

                results.append({
                    "uid":        uid,
                    "recipient":  company_name,
                    "amount":     amt,
                    "amount_usd": amt,
                    "agency":     "See filing",
                    "desc":       f"8-K contract award filing",
                    "awarded":    filed,
                    "expires":    "",
                    "country":    "USA",
                    "source":     "SEC 8-K Filing",
                    "ticker":     ticker,  # already known
                })
                log.info(f"8-K: ${ticker} contract award {fmt_usd(amt)} filed {filed}")

            time.sleep(0.2)
        except Exception as e:
            log.debug(f"8-K check failed {ticker}: {e}")

    log.info(f"8-K: {len(results)} contract filings found")
    return results

# =========================================================
# MAIN CHECK
# =========================================================

def check():
    log.info("─" * 55)
    log.info(f"Check — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")

    all_awards = []
    for label, fn in [("DoD", fetch_dod_awards), ("USA", fetch_us_awards)]:
        try:
            awards = fn()
            all_awards.extend(awards)
        except Exception as e:
            log.error(f"{label} failed: {e}")

    log.info(f"Total fetched: {len(all_awards)}")
    new = 0

    for award in all_awards:
        uid = award.get("uid") or hashlib.sha256(
            f"{award['country']}|{award['recipient']}|{award['amount']}|{award.get('awarded','')}".encode()
        ).hexdigest()

        if already_seen(uid):
            continue

        ticker = award.get("ticker") or find_ticker(award["recipient"])
        if not ticker:
            mark_seen(uid, award["recipient"], award.get("amount_usd",0),
                      award.get("agency",""), award["country"], "", 0)
            continue

        price, cap = get_stock_info(ticker)
        years      = get_years(award.get("awarded",""), award.get("expires",""))
        score, rating = score_deal(award.get("amount_usd",0), cap, years)
        cap_str = fmt_usd(cap) if cap else "NO CAP"

        log.info(f"NEW [{award['country']}] {award['recipient']} | "
                 f"{fmt_usd(award.get('amount_usd',0))} | ${ticker} | cap={cap_str} | {score}/100 {rating}")

        if score >= MIN_DEAL_SCORE:
            try:
                send_contract_alert(award, ticker, score, rating, price, cap)
                new += 1
            except Exception as e:
                log.error(f"Push failed: {e}")
        else:
            log.info(f"  Below threshold: ${ticker} {fmt_usd(award.get('amount_usd',0))} cap={fmt_usd(cap) if cap else 'NONE'} score={score}")

        mark_seen(uid, award["recipient"], award.get("amount_usd",0),
                  award.get("agency",""), award["country"], ticker, score)

    log.info(f"Done — {new} contract alerts sent")
    check_insiders()

def check_8k():
    try:
        awards = fetch_8k_filings()
        for award in awards:
            uid = award.get("uid")
            if not uid or already_seen(uid): continue
            ticker = award.get("ticker") or find_ticker(award["recipient"])
            if not ticker: continue
            price, cap = get_stock_info(ticker)
            years = get_years(award.get("awarded",""), award.get("expires",""))
            score, rating = score_deal(award.get("amount_usd",0), cap, years)
            if score >= MIN_DEAL_SCORE:
                try:
                    send_contract_alert(award, ticker, score, rating, price, cap)
                except Exception as e:
                    log.error(f"8-K push failed: {e}")
            mark_seen(uid, award["recipient"], award.get("amount_usd",0),
                      award.get("agency",""), award["country"], ticker, score)
    except Exception as e:
        log.error(f"8-K check failed: {e}")

# =========================================================
# MAIN LOOP
# =========================================================

def run_bot():
    try:
        ntfy("Contract Bot Live",
             "Monitoring DoD (globalsecurity) + USASpending + SEC insider buys",
             tags="white_check_mark")
    except:
        pass

    last_cleanup = datetime.now()
    while True:
        try:
            check()
        except Exception as e:
            import traceback
            log.error(f"Check error: {e}\n{traceback.format_exc()}")

        if (datetime.now() - last_cleanup).days >= 7:
            cleanup_old()
            last_cleanup = datetime.now()

        # Run 8-K check every 4th cycle (~hourly)
        if not hasattr(run_bot, "_cycle"):
            run_bot._cycle = 0
        run_bot._cycle += 1
        if run_bot._cycle % 4 == 0:
            try:
                check_8k()
            except Exception as e:
                log.error(f"8-K cycle failed: {e}")

        log.info(f"Sleeping {CHECK_MINUTES}min...")
        time.sleep(CHECK_MINUTES * 60)

# =========================================================
# START
# =========================================================

print("=" * 55)
print("  CONTRACT ALERT BOT")
print(f"  Sources: DoD (globalsecurity) + USASpending")
print(f"  {len(INSIDER_WATCHLIST)} insider tickers | {len(KNOWN)} known companies")
print(f"  Min award: $5M | Min score: {MIN_DEAL_SCORE} | Every {CHECK_MINUTES}min")
print("=" * 55)

threading.Thread(target=run_bot, daemon=True).start()
start_web_server()
