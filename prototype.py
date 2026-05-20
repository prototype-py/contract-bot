import json
import urllib.request
from datetime import datetime, timedelta

# YOUR SETTINGS
NTFY_TOPIC     = "my-contract-test"
SEND_REAL_PUSH = True
MIN_AWARD      = 5_000_000
BUSINESS_TYPES = []
LOOKBACK_DAYS  = 7
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
    start = end - timedelta(days=LOOKBACK_DAYS)
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
                 "User-Agent": "ContractBotPrototype/1.0"},
        method="POST",
    )
    print("Fetching from USASpending.gov...")
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    total = data.get("page_metadata", {}).get("total", 0)
    print(f"Connected - {total:,} total contracts found\n")
    return data.get("results", [])

def send_push(award, ticker, score, price, cap):
    recipient = award.get("Recipient Name", "Unknown")
    amount    = fmt(award.get("Award Amount"))
    agency    = award.get("Awarding Agency", "")
    award_id  = award.get("Award ID", "")
    amt_val   = float(award.get("Award Amount") or 0)
    priority  = "urgent" if amt_val >= 50_000_000 else "high"
    title     = f"${ticker} - {recipient}" if ticker else recipient
    parts     = [amount, agency]
    if price:  parts.append(f"Stock ${price:.2f}")
    if cap:    parts.append(f"MCap {cap}")
    if score:  parts.append(f"Score {score}")
    body = " | ".join(parts)
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

def run():
    print("=" * 60)
    print("  CONTRACT ALERT BOT - PUBLICLY TRADED COMPANIES")
    print("=" * 60)
    print(f"  Min award  : {fmt(MIN_AWARD)}")
    print(f"  Lookback   : {LOOKBACK_DAYS} days")
    print(f"  Watching   : {len(KNOWN_PUBLIC)} companies")
    print(f"  Real push  : {'YES - ' + NTFY_TOPIC if SEND_REAL_PUSH else 'NO (dry run)'}")
    print("=" * 60)
    print()

    try:
        awards = fetch_awards()
    except Exception as e:
        print(f"ERROR: {e}")
        return

    hits = []
    for award in awards:
        ticker, company = find_ticker(award.get("Recipient Name", ""))
        if company:
            score = keyword_score(award)
            hits.append((award, ticker, company, score))

    hits.sort(key=lambda x: (
        0 if x[1] else 1,
        -x[3],
        -float(x[0].get("Award Amount") or 0)
    ))

    print(f"Scanned  : {len(awards)} contracts")
    print(f"Matched  : {len(hits)} from known public companies")
    print(f"Traded   : {sum(1 for h in hits if h[1])} with tickers\n")

    if not hits:
        print("No matches found. Try increasing LOOKBACK_DAYS to 30 or 60.")
        return

    print("=" * 60)
    print("INVESTMENT LEADS:")
    print("=" * 60)

    for i, (award, ticker, company, score) in enumerate(hits, 1):
        amt  = float(award.get("Award Amount") or 0)
        city = award.get("Place of Performance City Name", "")
        st   = award.get("Place of Performance State Code", "")
        loc  = ", ".join(filter(None, [city, st])) or "N/A"
        desc = (award.get("Description") or "")[:150]

        price, cap = None, None
        if ticker:
            price, cap = get_stock_price(ticker)

        flag    = f"${ticker}" if ticker else "PRIVATE"
        urgency = "URGENT" if amt >= 50_000_000 else "ALERT"

        print(f"\n[{i}] {urgency} | {flag}")
        print(f"  Company : {award.get('Recipient Name','Unknown')}")
        if ticker:
            line = f"  Stock   : ${ticker}"
            if price: line += f"  |  Price: ${price:.2f}"
            if cap:   line += f"  |  Mkt Cap: {cap}"
            print(line)
        print(f"  Award   : {fmt(amt)}")
        print(f"  Agency  : {award.get('Awarding Agency','')}")
        print(f"  Location: {loc}")
        print(f"  Score   : {score}")
        print(f"  Desc    : {desc}")
        print(f"  Link    : https://usaspending.gov/award/{award.get('Award ID','')}")

        if SEND_REAL_PUSH and i <= 10:
            try:
                send_push(award, ticker, score, price, cap)
                print(f"  PUSHED to ntfy.sh/{NTFY_TOPIC}")
            except Exception as e:
                print(f"  Push failed: {e}")

    print("\n" + "=" * 60)
    traded = sum(1 for h in hits if h[1])
    print(f"Done - {traded} publicly traded | {len(hits)-traded} private matched")
    print("=" * 60)

run()