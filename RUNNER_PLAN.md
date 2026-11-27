# Nexus Runner Track 0.1 — what it does, how picks and results work

**PAPER ONLY. No wallet, no keys, no trades.** Nothing here is proven profitable yet.

## Why this exists (from the 27 Nov review of `data_v15`)
1. v1.5 CANDIDATEs lose on 99% of 5-minute checks and about 80% at 4 hours. The coins barely move (about 0% gross) and each trade costs about 2.2%.
2. 7 of the 8 clean 500%+ runners were blocked by the 3-hour age rule.
3. All 9 coins that went from under $50k to $500k market cap were rejected. 7 of them had $5–15k liquidity, under the $15k floor.
4. Those 9 took 1 hour to 11 days to get there. v1.5 only measures 4 hours.
5. The +80% take-profit sold HODL at +80%; it went on to +680%.

## What is new (files)
| File | What it is |
|---|---|
| `nexus_runner.py` | The Runner Track scanner (new). |
| `test_nexus_runner.py` | 38 offline tests (new). |
| `scripts/runner_session.sh` | Runs 34 scans, 10 minutes apart, and saves after each (new). |
| `.github/workflows/nexus-runner.yml` | GitHub workflow (new). |
| `RUNNER_PLAN.md` | This document. |
| `runner-data` branch | Where results are saved. Kept separate so `main` is never written to. |

**Not changed:** `nexus_v15.py`, `concept_scorer_v1_4.py`, the v1.5 workflow, all `data_v15` files and all scripts the v1.5 scanner uses. The 98 existing tests still pass.

## How a coin becomes a PICK (every 10 minutes)
1. **Find coins:** DEX Screener new profiles and boosts, plus GeckoTerminal new pools (pages 1–3). Then full DEX Screener data is fetched for each.
2. **Early-coin filter:** Solana only. Market cap $10k–$100k. Liquidity at least $5k. **No age rule.**
3. **One entry per coin:** the first scan where it passes step 2. It is never re-entered later.
4. **Quick rejects:** a $50 buy would move the price more than 5%; or 20+ buys and 0 sells in the last hour (honeypot hint).
5. **Safety checks (from v1.4.2).** Up to 10 coins per scan; coins with the most 5-minute buys go first.
   - Mint authority and freeze authority revoked
   - No Token-2022 traps (freeze, hooks, big transfer fees)
   - Top-10 real wallets own 35% or less (pools and burns excluded)
   - Jupiter sell test: selling $50 loses 15% or less
   - RugCheck: no danger flags, not rugged, no creator rug history, fewer than 4 insiders
   - Trade patterns: no single wallet driving the volume, no bot round-tripping, no same-size trade fingerprint
   - **One change for early coins:** "far below its 48h peak" is recorded as a fact, not a reject. A dip can be a good entry.
6. **Decision:**
   - **PICK** only if every check passed.
   - **REJECT** if any check failed.
   - **UNVERIFIED** if anything needed was unknown (an API down, holders unreadable, no sell quote, RugCheck missing). Unknown is never a pick.
   - **NOT_CHECKED** if the 10-check budget ran out. These coins are still followed, as a comparison group.

## Facts recorded at entry (so we can learn what separates runners from rugs)
- **Size and age:** market cap, liquidity, liquidity ÷ market cap, age in minutes
- **Price moves:** 5m, 1h, 6h and 24h; entry type = **dip** (1h at −20% or lower), **chase** (1h at +100% or higher) or **neutral**
- **Flow:** buys and sells over 5m and 1h, buy share
- **Volume:** 5m, 1h and 6h; **volume speed** (last 5 minutes compared with the hourly pace)
- **Holders:** total holders, **holders per minute** of age, top-10 wallet %, dev wallet %, dev still in top holders, insiders
- **Safety facts:** RugCheck score and flag counts, LP locked %, sell-test loss, drawdown from the 48h peak, trade count, distinct wallets, top wallet share, bot share
- **Other:** boosts, socials, website, has a DEX Screener profile, which DEX, which feed

## How results are measured (the fixed paper exit)
The exit is calculated from GeckoTerminal 5-minute candles of the same pool recorded at entry, for **every** coin, not only picks.
1. **Entry:** 2 minutes after the signal, at the **high** of that 5-minute candle (pessimistic). No trade within 10 minutes = no entry. That counts as unknown, not a loss.
2. **Stop:** −40%.
3. **At 2×:** sell half (+100% on that half).
4. **Rest:** trails 40% below the highest price reached, and never below the entry price.
5. **Time limit:** 7 days, then sell the rest at the last price.
6. **Pessimistic rules:**
   - The stop is checked before the target in every candle.
   - A gap below the stop sells at the candle's open.
   - A rug candle (below 10% of entry) sells at its low.
   - A dead pool (under $500 liquidity) at the end makes the rest worth −100%.
7. **Bad data is never a win:** bad price prints (giant wicks, 10× jumps that fall straight back) are marked UNRELIABLE and left out of results. Missing data is UNKNOWN, never counted as a win or a loss.
8. **Costs:** modelled fees and price impact for a $50 trade (v1.4.2 formula) plus a 1% buffer. About 6% round trip at $5k liquidity, so early coins are expensive.
9. **When results are written:** an early look at **24h** and the final result at **7 days**. Each is written once and never rewritten. Failed fetches are retried for 72 hours, then marked unknown.
10. **Also recorded:** peak multiple, minutes to 2×, 5× and 10×, highest market cap reached, and the peak after our exit (to see what the exit rule gave up).

## Telegram
- **RUNNER PICK** with the key facts and the plan (at most 3 per scan, plus a count of the rest)
- Live **2×, 5× and 10×** milestones for open picks; **stop** and **trail stop** notices
- **Daily report** after 08:00 UTC
- A failure alert if a run breaks

## How we judge it (step 7: nobody can promise the outcome)
1. `report.md` (on `runner-data`) compares picks with all early coins and with rejected coins: average return after costs, win %, and 2×/5×/10× hit rates.
2. It also groups results by each entry fact (dip/chase, buy share, volume speed, age, market cap, holders per minute, top-10 %). Groups under 30 coins are hidden.
3. **The verdict stays "TOO EARLY" until 300 finished 7-day picks.**
4. Then: find the rules on the earlier weeks and test them on the later weeks. A positive average after costs on the later weeks = a candidate edge. Only after that comes a small real-money test, and only if you approve it.
5. **Rules are frozen.** Changing any rule = a new version and a fresh count.

## Known limits
- Feeds show a sample of new coins, not every coin on Solana. Pump.fun coins are only seen after they reach a DEX pool.
- At 10 safety checks per scan, a very busy scan leaves some coins NOT_CHECKED. `scans.csv` counts them, so the budget can be raised if needed.
- Live milestone alerts use price snapshots; the official result always comes from candles.
- GitHub Actions can be late or skip runs. The hourly schedule keeps one session queued to reduce gaps.

## To approve and start
1. Read the code on the `runner-track` branch (pull request).
2. Merge the pull request into `main`. Scheduled runs only start from `main`.
3. Actions → **Nexus Runner Track (paper)** → **Run workflow** to start now (it sends a Telegram test first).
4. **To stop:** Actions → Nexus Runner Track → **⋯** → **Disable workflow**.
