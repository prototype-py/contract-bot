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
MIN_AWARD_USD       = 5_000_000
CHECK_MINUTES       = 30
DATABASE            = "contracts.db"
MIN_DEAL_SCORE      = 20
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
    "Booz Allen":          "BAH",
    "Leidos":              "LDOS",
    "SAIC":                "SAIC",
    "Science Applications":"SAIC",
    "Parsons":             "PSN",
    "Palantir":            "PLTR",
    "Accenture":           "ACN",
    "Raytheon":            "RTX",
    "RTX Corp":            "RTX",
    "Northrop Grumman":    "NOC",
    "Lockheed":            "LMT",
    "L3Harris":            "LHX",
    "General Dynamics":    "GD",
    "Textron":             "TXT",
    "Mercury Systems":     "MRCY",
    "Kratos":              "KTOS",
    "Leonardo DRS":        "DRS",
    "Curtiss-Wright":      "CW",
    "KBR":                 "KBR",
    "Fluor":               "FLR",
    "Jacobs":              "J",
    "Tetra Tech":          "TTEK",
    "AECOM":               "ACM",
    "Maximus":             "MMS",
    "ICF":                 "ICFI",
    "CACI":                "CACI",
    "Heico":               "HEI",
    "BWX Technologies":    "BWXT",
    "Rocket Lab":          "RKLB",
    "VSE Corporation":     "VSEC",
    "IBM":                 "IBM",
    "Honeywell":           "HON",
    "General Electric":    "GE",
    "GE HealthCare":       "GEHC",
    "Boeing":              "BA",
    "Huntington Ingalls":  "HII",
    "Huntington-Ingalls":  "HII",
    "Oracle":              "ORCL",
    "Microsoft":           "MSFT",
    "Amazon":              "AMZN",
    "Alphabet":            "GOOGL",
    "Google":              "GOOGL",
    "Amentum":             "AMTM",
    "Pratt and Whitney":   "RTX",
    "Pratt & Whitney":     "RTX",
    "Collins Aerospace":   "RTX",
    "Sikorsky":            "LMT",
    "Aerojet":             "LHX",
    "Spirit AeroSystems":  "SPR",
    "BAE Systems":         "BA.L",
    "Rolls-Royce":         "RR.L",
    "QinetiQ":             "QQ.L",
    "Babcock":             "BAB.L",
    "Serco":               "SRP.L",
    "CAE":                 "CAE.TO",
    "MDA":                 "MDA.TO",
    "Heroux-Devtek":       "HRX.TO",
    "Calian":              "CGY.TO",
    "Elbit Systems":       "ESLT",
    "CyberArk":            "CYBR",
    "Check Point":         "CHKP",
}

INSIDER_WATCHLIST = [
    "KTOS","MRCY","DRS","PSN","RKLB","VSEC","LDOS","BAH","SAIC",
    "CACI","LMT","NOC","RTX","GD","LHX","HII","KBR","TTEK",
    "ACM","PLTR","HON","GE","GEHC","BA","BWXT","CW","HEI",
    "ICFI","MMS","SPR","FLR","IBM","AMTM",
    "ESLT","CYBR","CHKP",
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
    db.execute("CREATE INDEX IF NOT EXISTS idx_sa_seen ON seen_awards(seen_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_si_seen ON seen_insider(seen_at)")
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
            (uid, recipient, amount_usd, agency, country, ticker, score, datetime.now().isoformat()))
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
        DB.commit()

# =========================================================
# HELPERS
# =========================================================

def fmt_usd(n):
    v = float(n or 0)
    if v >= 1e9: return f"${v/1e9:.2f}B"
    if v >= 1e6: return f"${v/1e6:.2f}M"
    return f"${v/1e3:.0f}K"

def find_ticker(name):
    name_lower = name.lower()
    for company, ticker in KNOWN.items():
        if company.lower() in name_lower:
            return ticker
    return None

_stock_cache = {}

def get_stock_info(ticker):
    if ticker in _stock_cache:
        price, cap, ts = _stock_cache[ticker]
        if (datetime.now() - ts).total_seconds() < 600:
            return price, cap
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        meta  = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice", 0)
        cap   = meta.get("marketCap", 0)
        _stock_cache[ticker] = (price, cap, datetime.now())
        return price, cap
    except:
        return None, None

# =========================================================
# SCORING
# =========================================================

def score_deal(amount_usd, market_cap, years, has_insider):
    score = 0

    if not market_cap or market_cap <= 0:
        score += 20  # unknown cap — moderate base
    else:
        pct = (amount_usd / market_cap) * 100
        if   pct >= 50: score += 60
        elif pct >= 25: score += 50
        elif pct >= 10: score += 35
        elif pct >= 5:  score += 20
        elif pct >= 2:  score += 10
        else:           score += 2

    if   amount_usd >= 500_000_000: score += 20
    elif amount_usd >= 100_000_000: score += 15
    elif amount_usd >= 50_000_000:  score += 10
    elif amount_usd >= 10_000_000:  score += 5

    if   years >= 5: score += 10
    elif years >= 3: score += 7
    elif years >= 2: score += 4
    elif years >= 1: score += 2

    if has_insider: score += 10

    score = min(score, 100)
    if   score >= 70: rating = "STRONG BUY"
    elif score >= 50: rating = "HIGH VALUE"
    elif score >= 30: rating = "NOTABLE"
    elif score >= 15: rating = "WATCH"
    else:             rating = "LOW IMPACT"
    return score, rating

def get_years(awarded, expires):
    try:
        s = datetime.strptime(awarded[:10], "%Y-%m-%d")
        e = datetime.strptime(expires[:10], "%Y-%m-%d")
        return max((e - s).days / 365.25, 0)
    except:
        return 0

# =========================================================
# PUSH
# =========================================================

def ntfy(title, body, priority="default", tags="money_bag", link=None):
    headers = {
        "Title":        title.encode("ascii","ignore").decode("ascii"),
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
    amt     = float(award.get("amount_usd", award.get("amount", 0)))
    agency  = award.get("agency","")[:40]
    country = award.get("country","")
    awarded = award.get("awarded","")
    expires = award.get("expires","")
    name    = award.get("recipient","")

    # Clean company name
    clean = name
    for s in [", INC.",", LLC",", L.P."," INC"," LLC"," CORP",
              " FEDERAL"," FEDERAL SERVICES"," GOVERNMENT SERVICES",
              " INFORMATION TECHNOLOGY, INC."," SYSTEMS CORPORATION"]:
        clean = clean.replace(s,"")
    clean = clean.strip().title()

    cap_str = fmt_usd(cap) if cap else "?"
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
    if   "ceo" in title.lower() or "chief executive" in title.lower():
        priority = "urgent"
    elif "chief" in title.lower() or "president" in title.lower():
        priority = "high"
    else:
        priority = "high"

    vs = ""
    if stock_price and price_paid:
        pct = ((stock_price - price_paid) / price_paid) * 100
        vs  = f" | now {pct:+.1f}%"

    push_title = f"INSIDER BUY - ${ticker} [{role}]"
    body = (
        f"{name} ({title})\n"
        f"{shares:,} shares @ ${price_paid:.2f} = {fmt_usd(amount)}{vs}"
    )
    link = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={ticker}&type=4&dateb=&owner=include&count=10"
    ntfy(push_title, body, priority, "rotating_light", link)
    log.info(f"  INSIDER: ${ticker} {name} {fmt_usd(amount)}")

# =========================================================
# DOD — globalsecurity.org (mirrors war.gov same day)
# =========================================================

# Hardcoded known article IDs — bot updates this at runtime
GLOBALSECURITY_KNOWN = {
    "2026-06-01": 4505747,
    "2026-06-02": 4506825,
    "2026-06-03": 4507573,
    "2026-06-04": 4508268,
    "2026-06-05": 4508978,
    "2026-06-06": 4509712,
    "2026-06-09": 4510650,
}

DOD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "text/html,application/xhtml+xml",
}

def fetch_dod_page(dt):
    used_date = dt.strftime("%Y-%m-%d")
    ym        = dt.strftime("%Y/%m")

    # Try hardcoded ID first — fast path
    if used_date in GLOBALSECURITY_KNOWN:
        article_id  = GLOBALSECURITY_KNOWN[used_date]
        url = f"https://www.globalsecurity.org/military/library/news/{ym}/dod-contracts_{article_id}.htm"
        try:
            req = urllib.request.Request(url, headers=DOD_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                html = r.read().decode("utf-8", errors="ignore")
            if "was awarded" in html.lower():
                log.info(f"DoD: fetched {used_date} (id={article_id})")
                return html, used_date
        except Exception as e:
            log.debug(f"DoD known ID failed {used_date}: {e}")

    # Estimate and scan — only if no known ID
    known_dates = sorted(GLOBALSECURITY_KNOWN.keys())
    if known_dates:
        last_date = datetime.strptime(known_dates[-1], "%Y-%m-%d")
        last_id   = GLOBALSECURITY_KNOWN[known_dates[-1]]
        days_diff = (dt - last_date).days
        estimated = int(last_id + days_diff * 800)
    else:
        estimated = 4510000

    log.debug(f"DoD: scanning for {used_date} near ID {estimated}")
    for delta in range(0, 3000, 100):
        for article_id in [estimated + delta, estimated - delta]:
            if article_id < 4000000: continue
            url = f"https://www.globalsecurity.org/military/library/news/{ym}/dod-contracts_{article_id}.htm"
            try:
                req = urllib.request.Request(url, headers=DOD_HEADERS)
                with urllib.request.urlopen(req, timeout=4) as r:
                    html = r.read().decode("utf-8", errors="ignore")
                if "was awarded" in html.lower() and used_date.replace("-","") in html:
                    GLOBALSECURITY_KNOWN[used_date] = article_id
                    log.info(f"DoD: found {used_date} at id={article_id}")
                    return html, used_date
            except:
                continue
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
    for m in pattern.finditer(html):
        company = m.group(1).strip().rstrip(",*").strip()
        if len(company) < 3 or company[0].islower():
            continue
        try:
            amount = float(m.group(2).replace(",",""))
            if amount < 1000: amount *= 1_000_000
        except:
            continue
        if amount < MIN_AWARD_USD: continue
        uid = hashlib.sha256(f"DOD|{company}|{amount:.0f}|{used_date}".encode()).hexdigest()
        if uid in seen: continue
        seen.add(uid)
        end  = min(len(html), m.end() + 300)
        desc = re.sub(r'<[^>]+>', '', html[m.end():end]).strip()[:150]
        results.append({
            "uid": uid, "recipient": company, "amount": amount,
            "amount_usd": amount, "agency": "Dept of Defense",
            "desc": desc, "awarded": used_date, "expires": "",
            "country": "USA", "source": "war.gov/globalsecurity.org",
        })
    return results

def fetch_dod_awards():
    results = []
    today   = datetime.now()
    for dt in [today, today - timedelta(days=1)]:
        if dt.weekday() >= 5:  # skip weekends
            continue
        html, used_date = fetch_dod_page(dt)
        if html:
            parsed = parse_dod_html(html, used_date)
            log.info(f"DoD: {len(parsed)} contracts for {used_date}")
            results.extend(parsed)
        else:
            log.info(f"DoD: no page yet for {used_date}")
    return results

# =========================================================
# UK — Contracts Finder (real-time API)
# =========================================================

def fetch_uk_awards():
    try:
        since = (datetime.now() - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%S")
        now   = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        url   = (f"https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"
                 f"?publishedFrom={since}&publishedTo={now}&stages=award&limit=100")
        req = urllib.request.Request(url, headers={"User-Agent":"ContractBot/1.0","Accept":"application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        results = []
        for release in data.get("releases", []):
            for award in release.get("awards", []):
                amt_gbp = float((award.get("value") or {}).get("amount", 0) or 0)
                amt_usd = amt_gbp * 1.27  # approximate GBP->USD
                if amt_usd < MIN_AWARD_USD: continue
                suppliers = award.get("suppliers", [{}])
                name = suppliers[0].get("name","Unknown") if suppliers else "Unknown"
                uid  = hashlib.sha256(f"UK|{name}|{amt_gbp:.0f}".encode()).hexdigest()
                results.append({
                    "uid": uid, "recipient": name,
                    "amount": amt_gbp, "amount_usd": amt_usd,
                    "agency": release.get("buyer",{}).get("name",""),
                    "desc": (release.get("tender",{}).get("description") or "")[:150],
                    "awarded": (award.get("date") or "")[:10],
                    "expires": ((award.get("contractPeriod") or {}).get("endDate") or "")[:10],
                    "country": "UK",
                    "id": release.get("ocid",""),
                    "source": "Contracts Finder (UK)",
                })
        log.info(f"UK: {len(results)} contracts")
        return results
    except Exception as e:
        log.warning(f"UK fetch failed: {e}")
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
        for hit in data.get("hits",{}).get("hits",[]):
            src = hit.get("_source",{})
            out.append({
                "accession": hit.get("_id",""),
                "filed":     src.get("file_date",""),
                "filer":     src.get("display_names",["Unknown"])[0],
                "cik":       src.get("entity_id",""),
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
        idx_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{dashed}-index.htm"
        req = urllib.request.Request(idx_url, headers=SEC_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode("utf-8", errors="ignore")
        for link in re.findall(r'href="([^"]*\.xml)"', html, re.IGNORECASE):
            if "xsl" in link.lower() or "stylesheet" in link.lower():
                continue
            if link.startswith("http"): return link
            if link.startswith("/"): return f"https://www.sec.gov{link}"
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
        if any(t in tl for t in ["chief executive","ceo"]): role = "CEO"
        elif any(t in tl for t in ["chief","president","cfo","coo"]): role = "C-Suite"
        else: role = "Director"

        signals = []
        for block in re.findall(r'<nonDerivativeTransaction>(.*?)</nonDerivativeTransaction>',
                                xml, re.DOTALL | re.IGNORECASE):
            code = re.search(r'<transactionCode>(.*?)</transactionCode>', block, re.IGNORECASE)
            if not code or code.group(1).strip() != "P": continue

            own = re.search(r'<directOrIndirectOwnership>.*?<value>(.*?)</value>', block, re.DOTALL | re.IGNORECASE)
            if own and own.group(1).strip() == "I": continue

            def val(tag_name):
                m = re.search(rf'<{tag_name}>.*?<value>(.*?)</value>', block, re.DOTALL | re.IGNORECASE)
                if m:
                    try: return float(m.group(1).strip().replace(",",""))
                    except: pass
                return 0.0

            shares    = val("transactionShares")
            price_per = val("transactionPricePerShare")
            total     = shares * price_per
            if total < MIN_INSIDER_BUY_USD: continue

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
                    signals = parse_form4(xml_url, ticker, filing["filer"], filing["filed"]) if xml_url else []
                    _insider_cache[key] = signals
                    time.sleep(0.3)

                for s in signals:
                    if already_seen_insider(s["uid"]): continue
                    price, _ = get_stock_info(ticker)
                    log.info(f"INSIDER ★ ${ticker} {s['filer']} ({s['role']}) {fmt_usd(s['amount'])}")
                    try:
                        send_insider_alert(ticker, s["filer"], s["title"], s["role"],
                                           s["shares"], s["price"], s["amount"], price)
                        sent += 1
                    except Exception as e:
                        log.error(f"Insider push failed: {e}")
                    mark_seen_insider(s["uid"], ticker, s["filer"], s["title"], s["amount"])
        except Exception as e:
            log.debug(f"Insider check failed {ticker}: {e}")
        time.sleep(0.3)
    log.info(f"Insider check done — {sent} sent")

# =========================================================
# MAIN CHECK
# =========================================================

def check():
    log.info("─" * 55)
    log.info(f"Check — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")

    all_awards = []
    for label, fn in [("DoD", fetch_dod_awards), ("UK", fetch_uk_awards)]:
        try:
            awards = fn()
            all_awards.extend(awards)
        except Exception as e:
            log.error(f"{label} failed: {e}")

    log.info(f"Total fetched: {len(all_awards)}")
    new = 0

    for award in all_awards:
        uid = award.get("uid") or hashlib.sha256(
            f"{award['country']}|{award['recipient']}|{award['amount']}|{award['awarded']}".encode()
        ).hexdigest()

        if already_seen(uid): continue

        ticker = find_ticker(award["recipient"])
        if not ticker:
            mark_seen(uid, award["recipient"], award["amount_usd"],
                      award.get("agency",""), award["country"], "", 0)
            continue

        price, cap = get_stock_info(ticker)
        years = get_years(award.get("awarded",""), award.get("expires",""))
        score, rating = score_deal(award["amount_usd"], cap, years, False)

        log.info(f"NEW [{award['country']}] {award['recipient']} | {fmt_usd(award['amount_usd'])} | ${ticker} | {score}/100 {rating}")

        if score >= MIN_DEAL_SCORE:
            try:
                send_contract_alert(award, ticker, score, rating, price, cap)
                new += 1
            except Exception as e:
                log.error(f"Push failed: {e}")

        mark_seen(uid, award["recipient"], award["amount_usd"],
                  award.get("agency",""), award["country"], ticker, score)

    log.info(f"Done — {new} contract alerts sent")
    check_insiders()

# =========================================================
# MAIN LOOP
# =========================================================

def run_bot():
    # Startup notification
    try:
        ntfy("Contract Bot Live", "Monitoring DoD + UK + SEC insider buys", tags="white_check_mark")
    except: pass

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

        log.info(f"Sleeping {CHECK_MINUTES}min...")
        time.sleep(CHECK_MINUTES * 60)

# =========================================================
# START
# =========================================================

print("=" * 55)
print("  CONTRACT ALERT BOT")
print(f"  DoD (globalsecurity) + UK Contracts Finder")
print(f"  {len(INSIDER_WATCHLIST)} insider tickers | {len(KNOWN)} known companies")
print(f"  Min award: $5M | Min score: {MIN_DEAL_SCORE} | Every {CHECK_MINUTES}min")
print("=" * 55)

threading.Thread(target=run_bot, daemon=True).start()
start_web_server()
