# BTC 5m — Polymarket paper research

Read-only observation of Polymarket BTC 5-minute markets with an exploratory
paper-trading simulator and a small HTTP dashboard.

## Research limitations

- **No wallets, signing keys or live order submission.**
- Two independent entry rules (cheap-side 20–40¢ and leader 45–70¢), not a
  calibrated probability/Chainlink settlement model.
- Paper fills assume the observed best ask and available top-of-book quantity.
  No latency/slippage model; fee estimates are provisional.
- The two simulations may take opposite sides in one market; they **must not**
  be interpreted as a combined strategy or combined portfolio.
- Market resolution is taken from finalized market outcome data.

## Run locally

```sh
PAPER_DB=./paper.sqlite3 python3 paper_btc5m.py run --interval 15
# second terminal
PAPER_DB=./paper.sqlite3 python3 dashboard.py
# http://localhost:8080
```

Requires only Python 3.13 standard library. SQLite database persists snapshots,
settlements and paper trials.

## Fly.io

Configured for exactly one `shared-cpu-1x` Machine with **256 MiB RAM** and a
1 GiB encrypted volume at `/data`. Intentionally **no public web service**:
Fly workload OIDC is not browser login. To view dashboard after Fly login:

```sh
fly proxy 8080:8080 -a sphr2k-btc5m-paper
# http://localhost:8080
```

To expose the dashboard online, configure a separate authenticated edge
(e.g. Cloudflare Access); do not add a public HTTP service without it.

No auto-stop: collector must stay running through each market interval.
