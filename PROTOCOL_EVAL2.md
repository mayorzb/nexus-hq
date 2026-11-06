# Paper evaluation eval-2: frozen protocol

Frozen on 6 Nov 2026, before the first eval-2 scan. It is PAPER ONLY. Its SHA-256 is pinned in `nexus_v15.PROTOCOL_SHA256`, and a test fails if one byte of this file changes. Any change means a new protocol (eval-3) and a new evaluation period.

## 0. What does not change
- The selection rules and thresholds, including the 3-hour age rule (MIN_AGE_H = 3.0), stay as they are throughout eval-2.
- No outcome observed in eval-2 changes a rule during eval-2.

## 1. Who gets an outcome (entry eligibility)
- Only rows written by code version 1.5.3 or later with `protocol = eval-2` count. Earlier records are baseline only.
- Each unique token gets one outcome: its FIRST liquid sighting. That means known liquidity of at least $15,000 and a pinned pool, recorded with the pool address, the quote token and the sighting price (`px0`). Paper candidates also get one.
- Groups are decided at the sighting and never revised afterwards:
  - **Young:** the token is less than 3 hours old, and its only failed rule of its own is the age rule. A market-regime abstain is not a rule of the token's own.
  - **Mature:** the token is at least 3 hours old, and it failed no rule of its own.
  - **Other:** everything else. These tokens are kept in the records but not compared.

## 2. The 60-minute outcome
- **Entry:** the HIGH of the first 1-minute GeckoTerminal candle that starts at or after the sighting plus 2 minutes. If there is no trade within 5 minutes of that point, there is no entry, and the horizon stays pending or unknown under the rules below.
- **No valid entry:** this check runs before the entry fill. Suppose any candle from 2 minutes before the sighting up to the entry closes at 10% or less of `px0`, or the entry candle's high is at or below 10% of `px0`. Then the status is `no_valid_entry`, with the exit reason `collapse_before_entry`.
  - Such an outcome is NOT scored as a return.
  - It is counted separately for each group.
  - The check is skipped, and the skip is logged as `ref_mismatch`, when no candle in the 15 minutes before entry trades within 3x of `px0`.
- **Exit:** whichever of these comes first inside the 60-minute window:
  - take-profit at +40%;
  - stop at -25%, filled at the candle LOW;
  - rug, a fall of 90% or more, scored -100%;
  - otherwise, the close of the last candle in the window. That candle must trade within 16 minutes of the window end. If no candle does, the outcome is pending.
- **Unreliable prints:** price-1 rules flag these. They are not scored.
- **Costs:** net = gross minus `rt_cost_pct`. That is the modelled fees plus the price impact of a $50 trade at the recorded liquidity, plus a 1.0% buffer. The worst possible result is -100%.
- **Due time:** each horizon is due at the sighting time plus 2 minutes, plus the horizon, plus 10 minutes. For 60 minutes that is t0 + 72 minutes. Nothing is labelled before it is due. The first scan after the due time attempts the label.
- **Settlement:** a thin window becomes final as `unknown` (thin trading) once both of these hold:
  - the window ended more than 30 minutes ago;
  - a trade has been seen after the window ended, or 4 hours have passed.

  After 72 hours with no data, the status is `unknown`. Unknown outcomes are never counted as losses.

## 3. Traceability (saved for every outcome)
- **Sighting:** pool, quote token symbol and address, sighting time, `px0`, liquidity, age, regime, decision, reasons, rules version and protocol.
- **Label row:** due time, number of attempts, status, entry and exit prices, gross, net and cost, the candle file it was computed from, and a note.
- **`label_attempts.csv`:** one append-only row per attempt and horizon, including failed lookups. Each row holds the time, outcome, detail, number of candles and candle file.
- **`candles/<UTC time>.jsonl.gz`:** the raw candles behind every attempt. These files are written once.

## 4. Matching (fixed)
- **Same scan:** pairs are formed only inside one scan, so both tokens share the same time and the same market regime.
- **Liquidity:** a mature token is eligible when its liquidity is between 0.5x and 2x the young token's.
- **Order:** young tokens are paired in order of liquidity, highest first, with ties broken by sighting_id.
- **Choice of comparator:** each young token takes the eligible mature token with the smallest |log(liquidity ratio)|. Ties go to the comparator with fewer uses, then to sighting_id.
- **Reuse cap:** a mature token is used at most 2 times. Every reuse is listed in the report.
- **Unmatched:** a young token with no eligible mature token, or with all of them used twice, is counted as unmatched.
- **Complete pair:** both 60-minute outcomes are `labelled`. A pair whose young token has `no_valid_entry` is counted separately and not scored.

## 5. Statistics (unit = scan)
- **Primary effect:** the scan-level mean difference. For each scan, take the mean over its complete pairs of (young net minus mature net). Then average those scan means across scans.
  - Its 95% interval comes from resampling scans: 2,000 bootstrap draws, seed 7.
- **Reported with it:**
  - the share of complete pairs in which the young token did worse, with counts;
  - the share of scans with a negative scan mean, with counts;
  - the median pair difference;
  - the big-loss rate (net of -20% or worse) for each group;
  - the no-valid-entry rate for each group.
- **Data drops:** all are reported for each group, with counts. These are:
  - pending;
  - unknown;
  - unreliable;
  - no valid entry.

## 6. Review point and sample
- **Review milestone:** at least 50 complete pairs AND at least 20 scans that contribute a complete pair. Nothing is decided before that point.
- **Shortfall:** if 40 eval-2 scans pass without reaching the milestone, the report states the shortfall in pairs and in scans, and collection continues.

## 7. How the owner will read the result at the milestone
These are guides, not automatic decisions.
- **"The rule helps avoid losses" requires all of the following:**
  - a scan-level mean of -10 points or worse, with the 95% interval excluding 0;
  - young tokens worse in at least 66% of complete pairs;
  - the direction holds when any single scan is dropped;
  - the direction holds in each regime that has at least 10 pairs.
- **"No evidence the rule helps" requires all of the following.** Young tokens worse in 55% or fewer of pairs does NOT, on its own, retire the rule.
  - young tokens worse in 55% or fewer of pairs;
  - a scan-level mean above -5 points, with a 95% interval that includes 0;
  - a young no-valid-entry rate no more than 2 points above the mature rate.
- **Anything else:** inconclusive. The rule stays, and collection continues.
