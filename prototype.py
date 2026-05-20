import json
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# YOUR SETTINGS
NTFY_TOPIC     = "my-contract-test"
MIN_AWARD      = 5_000_000
BUSINESS_TYPES = []
CHECK_MINUTES  = 60
LOOKBACK_HOURS = 2
KEYWORDS = {
    "cybersecurity": 5,
    "cyber":         4,
    "cloud":         3,
    "software":      2,
    "ai":            5,
    "machine learning": 5,
    "data":          2,
}

KNOWN_PUBLIC = {
    "Booz Allen":          "BAH",
    "Leidos":              "LDOS",
    "SAIC":                "SAIC",
    "Parsons":             "PSN",
    "Palantir":            "PLTR",
    "Accenture":           "ACN",
    "IBM":                 "IBM",
    "Raytheon":            "RTX",
    "Northrop":            "NOC",
    "Lockheed":            "LMT",
    "L3Harris":            "LHX",
    "General Dynamics":    "GD",
    "Textron":             "TXT",
    "TransDigm":           "TDG",
    "Mercury Systems":     "MRCY",
    "Kratos":              "KTOS",
    "Leonardo DRS":        "DRS",
    "Curtiss-Wright":      "CW",
    "KBR":                 "KBR",
    "Fluor":               "FLR",
    "Jacobs":              "J",
    "Tetra Tech":          "TTEK",
    "AECOM":               "ACM",
    "Tutor Perini":        "TPC",
    "VSE Corporation":     "VSEC",
    "Maximus":             "MMS",
    "ICF":                 "ICFI",
    "CACI":                "CACI",
    "ManTech":             "MANT",
    "Heico":               "HEI",
    "Moog":                "MOG.A",
    "Ducommun":            "DCO",
    "Astronics":           "ATRO",
    "Vectrus":             "VEC",
    "BWX Technologies":    "BWXT",
    "Rocket Lab":          "RKLB",
    "Aerojet":             "AJRD",
    "Spirit AeroSystems":  "SPR",
    "Triumph Group":       "TGI",
    "Kaman":               "KAMN",
    "PAE":                 "PAE",
    "Apogee":              "APOG",
    "DXC":                 "DXC",
    "Humana":              "HUM",
    "Vertex":              "VERX",
}

SEEN_FILE = "seen.json"

def load_seen():
    p = Path(SEEN_FILE)
    return set(json.loads(p.read_text())) if p.exists() else set()

def save_seen(seen):
    Path(SEEN_FILE).write_text(json.dumps(list(seen)[-5000:]))

def fmt(n):
    v = float(n or 0)
    if v >= 1e9: return f"${v/1e9:.2f}B"
    if v >= 1e6: return f"${v/1e6:.2f}M"
    return f"${v/1e3:.0f}K"

def keyword_score(award):
    text = (award.get("Description") or "").lower()
    return sum(w for kw, w in KEYWORDS.items() if kw in text)

def find_ticker(name):
    name_lower = name.lower()
    for company, ticker in KNOWN_PUBLIC.items():
        if company.lower() in name_lower:
            return ticker, company
    return None, None

def get_stock_price(ticker):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        meta  = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice", 0)
        cap   = meta.get("marketCap", 0)
        return price, fmt(cap) if cap else "N/A"
    except:
        return None, None

def fetch_awards():
    end   = datetime.now()
    start = end - timedelta(hours=LOOKBACK_HOURS)
    filters = {
        "award_type_codes": ["A","B","C","D"],
        "time_period": [{"start_date": start.strftime("%Y-%m-%d"),
                         "end_date":   end.strftime("%Y-%m-%d")}],
        "award_amounts": [{"lower_bound": MIN_AWARD}],
    }
    if BUSINESS_TYPES:
        filters["recipient_type_names"] = BUSINESS_TYPES
    payload = json.dumps({
        "filters": filters,
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
    return data.get("results", [])

def send_push(award, ticker, score, price, cap):
    recipient  = award.get("Recipient Name", "Unknown")
    amount     = fmt(award.get("Award Amount"))
    agency     = award.get("Awarding Agency", "")
    award_id   = award.get("Award ID", "")
    amt_val    = float(award.get("Award Amount") or 0)
    desc       = (award.get("Description") or "No description")[:120]
    start_date = award.get("Start Date", "Unknown")
    end_date   = award.get("End Date", "Unknown")
    alerted_at = datetime.now().strftime("%b %d %Y at %I:%M %p")
    priority   = "urgent" if amt_val >= 50_000_000 else "high"

    title = f"${ticker} | {recipient}" if ticker else recipient

    lines = []
    lines.append(f"Contract Value: {amount}")
    lines.append(f"Awarded: {start_date}")
    lines.append(f"Expires: {end_date}")
    lines.append(f"Agency: {agency}")
    if price: lines.append(f"Stock Price: ${price:.2f}")
    if cap:   lines.append(f"Market Cap: {cap}")
    lines.append(f"What: {desc}")
    lines.append(f"Alert sent: {alerted_at}")
    body = "\n".join(lines)

    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=body.encode(),
        headers={
            "Title":    title,
            "Priority": priority,
            "Tags":     "money_bag,chart_with_upwards_trend",
            "Click":    f"https://www.usaspending.gov/award/{award_id}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10):
        pass

def check():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{now}] Checking USASpending.gov...")

    try:
        awards = fetch_awards()
    except Exception as e:
        print(f"  Fetch error: {e}")
        return

    seen = load_seen()
    new_count = 0

    for award in awards:
        award_id = award.get("Award ID", "")
        if not award_id or award_id in seen:
            continue

        ticker, company = find_ticker(award.get("Recipient Name", ""))
        if not company:
            continue

        score = keyword_score(award)
        amt   = float(award.get("Award Amount") or 0)
        print(f"  NEW: {award.get('Recipient Name')} | {fmt(amt)} | ${ticker or 'PRIVATE'}")

        price, cap = None, None
        if ticker:
            price, cap = get_stock_price(ticker)

        try:
            send_push(award, ticker, score, price, cap)
            print(f"  PUSHED to phone")
        except Exception as e:
            print(f"  Push failed: {e}")

        seen.add(award_id)
        new_count += 1

    save_seen(seen)
    print(f"  Done - {new_count} new alerts sent")

# MAIN LOOP
print("=" * 60)
print("  CONTRACT ALERT BOT - RUNNING 24/7")
print(f"  Checking every {CHECK_MINUTES} minutes")
print(f"  Alerting to ntfy.sh/{NTFY_TOPIC}")
print("=" * 60)

check()
while True:
    time.sleep(CHECK_MINUTES * 60)
    check()
