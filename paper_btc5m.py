from __future__ import annotations
import argparse, json, math, sqlite3, time, urllib.request, urllib.error, statistics, os
from datetime import datetime, timezone
from pathlib import Path

DB = Path(os.environ.get("PAPER_DB", str(Path(__file__).with_name("paper.sqlite3"))))
GAMMA = "https://gamma-api.polymarket.com/markets/slug/"
CLOB = "https://clob.polymarket.com/book?token_id="
HEADERS = {"User-Agent": "btc5m-paper-research/0.1", "Accept": "application/json"}

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=12) as response:
        return json.load(response)

def setup(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS markets (
      slug TEXT PRIMARY KEY, start_ts INTEGER, end_ts INTEGER,
      up_token TEXT, down_token TEXT, twap_config TEXT, created_ts INTEGER
    );
    CREATE TABLE IF NOT EXISTS snapshots (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts INTEGER NOT NULL, slug TEXT NOT NULL, seconds_left REAL NOT NULL,
      up_indicative REAL, down_indicative REAL,
      up_best_ask REAL, down_best_ask REAL, up_best_bid REAL, down_best_bid REAL,
      up_ask_qty REAL, down_ask_qty REAL,
      book_status TEXT NOT NULL, error TEXT,
      UNIQUE(ts,slug)
    );
    CREATE TABLE IF NOT EXISTS settlements (slug TEXT PRIMARY KEY, winner TEXT, checked_ts INTEGER);
    CREATE TABLE IF NOT EXISTS events (
      ts INTEGER, level TEXT, message TEXT
    );
    CREATE TABLE IF NOT EXISTS orders (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, slug TEXT, side TEXT,
      strategy TEXT, quantity REAL, price REAL, fee REAL, status TEXT, reason TEXT
    );
    """)
    conn.execute("""CREATE TABLE IF NOT EXISTS trials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT NOT NULL,
        strategy TEXT NOT NULL,
        side TEXT NOT NULL,
        ts INTEGER NOT NULL,
        ask REAL NOT NULL,
        qty REAL NOT NULL,
        gross_usd REAL NOT NULL,
        fee_usd REAL NOT NULL,
        spread REAL NOT NULL,
        settled_pnl REAL,
        UNIQUE(slug,strategy)
    )""")
    conn.commit()

def log(conn, level, message):
    now=int(time.time())
    conn.execute("INSERT INTO events VALUES (?,?,?)",(now,level,message[:500]))
    conn.commit()
    print(datetime.now(timezone.utc).isoformat(timespec="seconds"), level, message,flush=True)

def best(book):
    asks=[(float(x["price"]),float(x["size"])) for x in book.get("asks",[]) if float(x["size"])>0]
    bids=[(float(x["price"]),float(x["size"])) for x in book.get("bids",[]) if float(x["size"])>0]
    a=min(asks,default=(None,None)); b=max(bids,default=(None,None))
    return a[0],a[1],b[0]

def paper_trial(conn, slug, ts, left, quotes):
    # Transparent, exploratory top-of-book fills. Does not model latency or book movement.
    # Only one entry per market/strategy; no hindsight and no executable wallet.
    if not (105 <= left <= 135): return
    options=[]
    for name, quote in zip(("Up","Down"),quotes):
        ask,qty,bid=quote
        if ask is None or bid is None or qty is None or not (0<ask<1): continue
        spread=ask-bid
        if spread<0 or spread>0.05 or qty < 2/ask: continue
        options.append((name,ask,qty,spread))
    if len(options)!=2: return
    cheap=min(options,key=lambda x:x[1])
    leader=max(options,key=lambda x:x[1])
    variants=[
        ("cheap_side_20_40",cheap, 0.20 <= cheap[1] <= 0.40),
        ("leader_45_70",leader, 0.45 <= leader[1] <= 0.70)
    ]
    for strategy,(side,ask,available,spread),eligible in variants:
        if not eligible: continue
        shares=2.0/ask
        if shares>available: continue
        # Provisional trading fee formula; check against actual CLOB fee endpoint
        # before interpreting profitability. Excludes funding/rebates.
        fee=0.07*ask*(1-ask)*shares
        conn.execute("""INSERT OR IGNORE INTO trials
             (slug,strategy,side,ts,ask,qty,gross_usd,fee_usd,spread)
             VALUES (?,?,?,?,?,?,?,?,?)""",
             (slug,strategy,side,ts,ask,shares,2.0,fee,spread))
    conn.commit()

def sample(conn):
    now=int(time.time()); start=now//300*300
    slug=f"btc-updown-5m-{start}"
    m=fetch(GAMMA+slug)
    tokens=json.loads(m["clobTokenIds"]); prices=json.loads(m["outcomePrices"])
    if len(tokens)!=2 or json.loads(m["outcomes"])!=["Up","Down"]:
        raise ValueError("unexpected market token/outcome mapping")
    conf=m.get("cryptoMarketConfig",{})
    if conf.get("twapEnabled") is not True:
        raise ValueError("unexpected non-TWAP market")
    conn.execute("INSERT OR IGNORE INTO markets VALUES (?,?,?,?,?,?,?)",
       (slug,start,start+300,tokens[0],tokens[1],json.dumps(conf),now))
    quotes=[]; errors=[]
    for token in tokens:
        try:
            quotes.append(best(fetch(CLOB+token)))
        except Exception as exc:
            quotes.append((None,None,None))
            errors.append(type(exc).__name__+":"+str(exc)[:90])
    status="ok" if not errors else "unavailable"
    vals=(now,slug,start+300-now,float(prices[0]),float(prices[1]),
          quotes[0][0],quotes[1][0],quotes[0][2],quotes[1][2],
          quotes[0][1],quotes[1][1],status,"; ".join(errors) or None)
    conn.execute("""INSERT OR IGNORE INTO snapshots
    (ts,slug,seconds_left,up_indicative,down_indicative,up_best_ask,down_best_ask,
     up_best_bid,down_best_bid,up_ask_qty,down_ask_qty,book_status,error)
     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",vals)
    conn.commit()
    paper_trial(conn,slug,now,start+300-now,quotes)
    # Fail-closed: until an independently calibrated probability model and settlement
    # reference stream are available, no paper orders are generated.
    return slug,status,quotes

def resolve(conn):
    now=int(time.time())
    todo=conn.execute("""SELECT m.slug FROM markets m LEFT JOIN settlements s ON m.slug=s.slug
       WHERE s.slug IS NULL AND m.end_ts<? ORDER BY m.end_ts DESC LIMIT 12""",(now-60,)).fetchall()
    for (slug,) in todo:
        try:
            m=fetch(GAMMA+slug)
            if not m.get("closed"): continue
            outcomes=json.loads(m["outcomes"])
            prices=[float(x) for x in json.loads(m["outcomePrices"])]
            if len(prices)!=2 or max(prices)<0.999 or min(prices)>0.001:
                continue
            winner=outcomes[prices.index(max(prices))]
            conn.execute("INSERT OR IGNORE INTO settlements VALUES (?,?,?)",(slug,winner,now))
            conn.commit()
            conn.execute("""UPDATE trials
                SET settled_pnl=CASE WHEN side=? THEN qty-gross_usd-fee_usd
                ELSE -gross_usd-fee_usd END WHERE slug=? AND settled_pnl IS NULL""",
                (winner,slug))
            conn.commit()
            log(conn,"INFO",f"Settlement {slug} => {winner}")
        except Exception as exc:
            log(conn,"WARN","Settlement lookup failed "+str(exc)[:150])

def report(conn):
    print("BTC5M PAPER COLLECTOR STATUS (no live orders)")
    for sql in [
      "SELECT COUNT(DISTINCT slug),COUNT(*),MIN(ts),MAX(ts) FROM snapshots",
      "SELECT book_status,COUNT(*) FROM snapshots GROUP BY book_status",
      "SELECT COUNT(*) FROM orders",
      "SELECT winner,COUNT(*) FROM settlements GROUP BY winner",
      "SELECT substr(error,1,100), COUNT(*) FROM snapshots WHERE error IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 3"
    ]:
        print(sql, conn.execute(sql).fetchall())
    rows=conn.execute("SELECT ts,slug,seconds_left,up_indicative,down_indicative,up_best_ask,down_best_ask,book_status FROM snapshots ORDER BY ts DESC LIMIT 5").fetchall()
    for r in rows: print(tuple(r))
    print("Exploratory hypothetical top-of-book fills (NOT real execution or proven edge):")
    for row in conn.execute("""SELECT strategy,COUNT(*),SUM(CASE WHEN settled_pnl IS NOT NULL THEN 1 ELSE 0 END),
        ROUND(SUM(settled_pnl),4),ROUND(AVG(settled_pnl),4)
        FROM trials GROUP BY strategy"""): print(tuple(row))
    print("Paper PnL includes provisional fees. Latency/slippage omitted; zero trades is valid.")
    
def main():
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=["once","run","report"],nargs="?",default="once")
    p.add_argument("--interval",type=int,default=15)
    args=p.parse_args()
    with sqlite3.connect(DB) as conn:
        setup(conn)
        if args.mode=="report": report(conn); return
        if args.mode=="once":
            try: print(sample(conn))
            except Exception as e: log(conn,"ERROR",repr(e))
            resolve(conn)
            report(conn)
            return
        log(conn,"INFO","Collector started. Read-only; no wallet, no trading.")
        while True:
            try:
                resolve(conn)
                slug,status,quotes=sample(conn)
                print(slug,status,quotes,flush=True)
            except Exception as e:
                log(conn,"ERROR",repr(e))
            time.sleep(max(args.interval,5))
if __name__=="__main__": main()
