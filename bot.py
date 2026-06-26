"""
bot.py — self-contained Ch12 (Davey NQ-720 Monday) PAPER forward-test bot for GitHub Actions.
Faithful to the cross-model-verified engine: 720-min session bars (17:00/05:00 buckets), entry on the
first Monday-close bar (buy next open), MARK-TO-CLOSE exit (+150 / -250 pts, no intrabar). PAPER ONLY.
Webhook from env TRADERSPOST_WEBHOOK (GitHub Secret). State in mon720_live_state.json (committed by the workflow).
"""
import os, sys, json, urllib.request
from datetime import datetime, timedelta

TGT_PTS = 150.0; STOP_PTS = 250.0
TICKER = "MNQ"; QTY = 1; STALE_SECS = 3600
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(HERE, "mon720_live_state.json")


def build_session_bars(rows, bndA=5, bndB=17):
    sess = {}
    for ts, o, h, l, c in rows:
        t = ts.time()
        if t >= datetime.strptime("%02d:00" % bndB, "%H:%M").time():
            key = (ts.date() + timedelta(days=1), 'A')
        elif t < datetime.strptime("%02d:00" % bndA, "%H:%M").time():
            key = (ts.date(), 'A')
        else:
            key = (ts.date(), 'B')
        s = sess.get(key)
        if s is None:
            sess[key] = dict(first=ts, last=ts, open=o, high=h, low=l, close=c)
        else:
            if ts < s['first']: s['first'] = ts; s['open'] = o
            if ts > s['last']:  s['last'] = ts;  s['close'] = c
            s['high'] = max(s['high'], h); s['low'] = min(s['low'], l)
    okey = lambda k: (k[0], 0 if k[1] == 'A' else 1)
    return [dict(date=k[0], bucket=k[1], dow=k[0].weekday(), open=sess[k]['open'],
                 close=sess[k]['close'], last_ts=sess[k]['last']) for k in sorted(sess, key=okey)]


def load_webhook():
    url = os.environ.get("TRADERSPOST_WEBHOOK", "").strip()
    if not url.startswith("http"):
        raise SystemExit("Set TRADERSPOST_WEBHOOK (the TradersPost PAPER webhook) as a repo Secret.")
    return url


def post(url, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode()[:200]


def load_state():
    return json.load(open(STATE_PATH)) if os.path.exists(STATE_PATH) else {"pos": 0, "entry": None, "last_bar": None}


def save_state(s):
    json.dump(s, open(STATE_PATH, "w"))


def feed_rows():
    import yfinance as yf
    df = yf.download("NQ=F", period="5d", interval="15m", progress=False, auto_adjust=False)
    rows = [(ts.to_pydatetime().replace(tzinfo=None), float(r["Open"]), float(r["High"]),
             float(r["Low"]), float(r["Close"])) for ts, r in df.iterrows()]
    return rows, (rows[-1][0] if rows else None)


def step():
    url = load_webhook(); s = load_state()
    rows, last_ts = feed_rows()
    if not rows:
        print("[mon720] no data"); return
    if (datetime.utcnow() - last_ts).total_seconds() > STALE_SECS:
        print("[mon720] feed STALE -> no action"); return
    bars = build_session_bars(rows)
    if len(bars) < 2:
        return
    completed = bars[:-1]
    keys = ["%s_%s" % (b['date'], b['bucket']) for b in completed]
    start = keys.index(s["last_bar"]) + 1 if s.get("last_bar") in keys else len(completed) - 1
    for i in range(max(start, 0), len(completed)):
        bar = completed[i]
        nxt_open = completed[i + 1]['open'] if i + 1 < len(completed) else bars[-1]['open']
        if s["pos"] > 0:
            op = bar['close'] - s["entry"]
            if op >= TGT_PTS or op <= -STOP_PTS:
                print("[mon720] EXIT %s op=%.1f -> %s" % (keys[i], op, post(url, {"ticker": TICKER, "action": "exit"})))
                s["pos"] = 0; s["entry"] = None
        if s["pos"] == 0 and bar['dow'] == 0:
            print("[mon720] BUY ~%.2f (Mon %s) -> %s" % (nxt_open, keys[i],
                  post(url, {"ticker": TICKER, "action": "buy", "orderType": "market", "quantity": QTY})))
            s["pos"] = 1; s["entry"] = nxt_open
        s["last_bar"] = keys[i]; save_state(s)


if __name__ == "__main__":
    step()
