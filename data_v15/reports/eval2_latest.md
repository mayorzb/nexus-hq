# Paper evaluation eval-2 (frozen protocol: PROTOCOL_EVAL2.md)

**Status:** collecting: 6/50 complete pairs, 5/20 scans, 24/40 scans used. No decision before the milestone.

## Token funnel

| stage | count |
|---|---|
| eval-2 scans | 24 |
| sightings | 1462 |
| liquid sightings | 563 |
| first liquid sightings = unique tokens with an outcome row | 129 |
|   young | 93 |
|   mature | 26 |
|   other | 10 |
| young with a comparator (cap 2) | 12 |
| young without a comparator | 81 |
|   pairs: young had no valid entry (counted, not scored) | 0 |
|   pairs: young or mature outcome not yet usable | 6 |
| complete pairs (both 60m outcomes labelled) | 6 |
| scans contributing a complete pair | 5 |

## 60m outcome status by group

- young: labelled 67/93, no_valid_entry 4/93, pending 5/93, unknown 10/93, unreliable 7/93
- mature: labelled 23/26, pending 2/26, unknown 1/26
- no valid entry: young 4/93, mature 0/26

## Effect (after costs; unit = scan)

- Scan-level mean difference (young - mature): -47.08 points, 95% interval (-76.4, -8.77); scans with young worse 4/5
- Pairs with young worse: 5/6 (83.3%); pair mean -38.86, median -44.74
- Big loss (<= -20%): young 4/6, mature 0/6

## Comparator reuse (cap 2)

- 20261106T170022-Gb7gExpw: FI (20261106T170022), Chicxu (20261106T170022)
- 20261106T180021-BNpRagRS: GRUB (20261106T180021), HODL (20261106T180021)
- 20261106T210020-4iTZ574d: Democat (20261106T210020), sexcoin (20261106T210020)
- 20261106T230019-Bmhp8nat: VETO (20261106T230019), STM (20261106T230019)

## Every pair

| scan | regime | young | liq | status | net | mature | liq | status | net | note |
|---|---|---|---|---|---|---|---|---|---|---|
| 20261106T160023 | NEUTRAL | RSHA262599 | 61004.83 | labelled | -32.12 |  |  |  | None | no eligible comparator |
| 20261106T160023 | NEUTRAL | 401kat | 36952.60 | labelled | -30.74 |  |  |  | None | no eligible comparator |
| 20261106T160023 | NEUTRAL | ZCATS | 35057.05 | labelled | 37.23 |  |  |  | None | no eligible comparator |
| 20261106T160023 | NEUTRAL | POKEMON | 24597.75 | labelled | -54.71 |  |  |  | None | no eligible comparator |
| 20261106T160023 | NEUTRAL | ZEC | 16264.48 | labelled | -70.42 |  |  |  | None | no eligible comparator |
| 20261106T160023 | NEUTRAL | POPO | 15783.56 | labelled | -49.86 |  |  |  | None | no eligible comparator |
| 20261106T170022 | NEUTRAL | FI | 108252.67 | labelled | 37.62 | BAGEL | 77787.56 | labelled | -8.24 |  |
| 20261106T170022 | NEUTRAL | Chicxu | 67737.77 | labelled | -49.55 | BAGEL | 77787.56 | labelled | -8.24 |  |
| 20261106T170022 | NEUTRAL | 401kinu | 55921.22 | labelled | 37.44 |  |  |  | None | comparators used twice |
| 20261106T170022 | NEUTRAL | KoriMu | 38953.51 | labelled | -34.46 |  |  |  | None | comparators used twice |
| 20261106T170022 | NEUTRAL | FI | 20448.60 | labelled | -37.7 |  |  |  | None | no eligible comparator |
| 20261106T170022 | NEUTRAL | MEOWCRAT | 18572.94 | labelled | -30.24 |  |  |  | None | no eligible comparator |
| 20261106T170022 | NEUTRAL | X | 15727.41 | unreliable | None |  |  |  | None | no eligible comparator |
| 20261106T180021 | NEUTRAL | GRUB | 36493.56 | unknown | None | OZA | 41158.77 | unknown | None |  |
| 20261106T180021 | NEUTRAL | HODL | 30994.35 | labelled | -29.43 | OZA | 41158.77 | unknown | None |  |
| 20261106T180021 | NEUTRAL | Degen | 26347.54 | unknown | None |  |  |  | None | comparators used twice |
| 20261106T180021 | NEUTRAL | LAURA | 22071.86 | labelled | -29.46 |  |  |  | None | comparators used twice |
| 20261106T180021 | NEUTRAL | TTP | 18216.98 | labelled | -30.83 |  |  |  | None | no eligible comparator |
| 20261106T180021 | NEUTRAL | HABIBI | 17362.89 | labelled | -31.37 |  |  |  | None | no eligible comparator |
| 20261106T180021 | NEUTRAL | CRVL | 16630.30 | labelled | -30.03 |  |  |  | None | no eligible comparator |
| 20261106T180021 | NEUTRAL | HABIBI | 15659.71 | labelled | 36.53 |  |  |  | None | no eligible comparator |
| 20261106T180021 | NEUTRAL | RIPPING | 15286.04 | unknown | None |  |  |  | None | no eligible comparator |
| 20261106T190021 | NEUTRAL | MONEYERO | 27167.66 | labelled | -100.0 |  |  |  | None | no eligible comparator |
| 20261106T190021 | NEUTRAL | MTA6 | 23350.13 | no_valid_entry | None |  |  |  | None | no eligible comparator |
| 20261106T190021 | NEUTRAL | BOYFRIEND | 19005.62 | labelled | 36.75 |  |  |  | None | no eligible comparator |
| 20261106T190021 | NEUTRAL | JOHN | 18275.98 | labelled | -1.74 |  |  |  | None | no eligible comparator |
| 20261106T190021 | NEUTRAL | BORDERLESS | 16712.29 | labelled | -31.1 |  |  |  | None | no eligible comparator |
| 20261106T190021 | NEUTRAL | CHROME | 16035.03 | no_valid_entry | None |  |  |  | None | no eligible comparator |
| 20261106T190021 | NEUTRAL | MONEYERO | 15395.81 | labelled | -100.0 |  |  |  | None | no eligible comparator |
| 20261106T200020 | NEUTRAL | FUSE | 16844.14 | labelled | 36.62 |  |  |  | None | no eligible comparator |
| 20261106T210020 | NEUTRAL | Lukaflm | 109781.17 | unreliable | None |  |  |  | None | no eligible comparator |
| 20261106T210020 | NEUTRAL | FUSE | 74573.32 | labelled | 37.53 |  |  |  | None | no eligible comparator |
| 20261106T210020 | NEUTRAL | Democat | 30628.52 | unreliable | None | fart | 17906.48 | labelled | -3.62 |  |
| 20261106T210020 | NEUTRAL | sexcoin | 17747.93 | unknown | None | fart | 17906.48 | labelled | -3.62 |  |
| 20261106T220019 | NEUTRAL | Leonida | 24905.19 | labelled | -36.04 |  |  |  | None | no eligible comparator |
| 20261106T220019 | NEUTRAL | HEDGE | 19597.96 | no_valid_entry | None |  |  |  | None | no eligible comparator |
| 20261106T220019 | NEUTRAL | LEAPCAT | 16062.01 | labelled | -31.14 |  |  |  | None | no eligible comparator |
| 20261106T230019 | NEUTRAL | PI | 100223.99 | labelled | -2.48 |  |  |  | None | no eligible comparator |
| 20261106T230019 | NEUTRAL | José | 50976.91 | labelled | -28.13 |  |  |  | None | no eligible comparator |
| 20261106T230019 | NEUTRAL | VETO | 29380.68 | unknown | None | TIRED | 21356.31 | labelled | -26.54 |  |
| 20261106T230019 | NEUTRAL | STM | 18822.61 | unreliable | None | TIRED | 21356.31 | labelled | -26.54 |  |
| 20261106T230019 | NEUTRAL | MOOH | 15734.13 | labelled | -3.42 | OIF | 16089.19 | labelled | -3.32 |  |
| 20261107T000019 | NEUTRAL | HODL | 100668.80 | labelled | 37.6 |  |  |  | None | no eligible comparator |
| 20261107T000019 | NEUTRAL | DCAT | 38884.08 | labelled | -31.01 |  |  |  | None | no eligible comparator |
| 20261107T000019 | NEUTRAL | HATCH | 31422.98 | labelled | -41.16 |  |  |  | None | no eligible comparator |
| 20261107T010019 | NEUTRAL | JIM | 36062.26 | labelled | -48.22 | zPEPE | 29401.80 | labelled | -0.04 |  |
| 20261107T020018 | NEUTRAL | Busted | 45649.88 | labelled | -100.0 | MAMESUKE | 82461.72 | labelled | -6.06 |  |
| 20261107T020018 | NEUTRAL | scamsem | 26464.26 | labelled | 37.05 |  |  |  | None | no eligible comparator |
| 20261107T020018 | NEUTRAL | CALL | 18882.16 | labelled | -36.02 |  |  |  | None | no eligible comparator |
| 20261107T020018 | NEUTRAL | LKY | 16429.86 | labelled | -59.02 |  |  |  | None | no eligible comparator |
| 20261107T020018 | NEUTRAL | FINNBAGS | 15702.04 | labelled | -41.96 |  |  |  | None | no eligible comparator |
| 20261107T030017 | NEUTRAL | scamsem | 92926.39 | labelled | -30.83 |  |  |  | None | no eligible comparator |
| 20261107T030017 | NEUTRAL | BTC | 30706.62 | labelled | 11.19 |  |  |  | None | no eligible comparator |
| 20261107T030017 | NEUTRAL | SCAMCHI | 23398.10 | labelled | 36.95 |  |  |  | None | no eligible comparator |
| 20261107T030017 | NEUTRAL | STM | 16306.87 | labelled | -50.76 |  |  |  | None | no eligible comparator |
| 20261107T040017 | NEUTRAL | Alice | 39454.21 | labelled | -40.43 |  |  |  | None | no eligible comparator |
| 20261107T040017 | NEUTRAL | Alice | 15446.31 | unreliable | None |  |  |  | None | no eligible comparator |
| 20261107T050016 | NEUTRAL | T&A | 26731.31 | labelled | -100.0 |  |  |  | None | no eligible comparator |
| 20261107T050016 | NEUTRAL | Twizter | 22256.95 | labelled | 36.91 |  |  |  | None | no eligible comparator |
| 20261107T050016 | NEUTRAL | PALICO | 18732.47 | labelled | -100.0 |  |  |  | None | no eligible comparator |
| 20261107T050016 | NEUTRAL | Capiboo | 18050.93 | labelled | -28.88 |  |  |  | None | no eligible comparator |
| 20261107T060015 | NEUTRAL | SAVE | 28076.81 | unknown | None |  |  |  | None | no eligible comparator |
| 20261107T060015 | NEUTRAL | meme | 27398.84 | labelled | -36.49 |  |  |  | None | no eligible comparator |
| 20261107T060015 | NEUTRAL | SLINGFOLIO | 24479.07 | labelled | -32.3 |  |  |  | None | no eligible comparator |
| 20261107T060015 | NEUTRAL | Hakutaku | 21155.53 | labelled | -28.69 |  |  |  | None | no eligible comparator |
| 20261107T060015 | NEUTRAL | STONKA | 15420.14 | unknown | None |  |  |  | None | no eligible comparator |
| 20261107T070014 | NEUTRAL | ZEC | 44531.30 | unreliable | None |  |  |  | None | no eligible comparator |
| 20261107T070014 | NEUTRAL | BRUH | 30191.64 | labelled | -32.24 |  |  |  | None | no eligible comparator |
| 20261107T070014 | NEUTRAL | Alice | 28325.63 | labelled | 37.1 |  |  |  | None | no eligible comparator |
| 20261107T070014 | NEUTRAL | JOKEST | 25678.82 | unknown | None |  |  |  | None | no eligible comparator |
| 20261107T080013 | NEUTRAL | Alice | 106109.98 | labelled | 37.61 |  |  |  | None | no eligible comparator |
| 20261107T080013 | NEUTRAL | trauma  | 17554.86 | labelled | -30.07 |  |  |  | None | no eligible comparator |
| 20261107T080013 | NEUTRAL | NETWORK | 15849.72 | unreliable | None |  |  |  | None | no eligible comparator |
| 20261107T080013 | NEUTRAL | BaiBai | 15470.78 | unknown | None |  |  |  | None | no eligible comparator |
| 20261107T090012 | NEUTRAL | Pygavel | 110894.17 | labelled | -100.0 | STANK | 107736.49 | labelled | -4.53 |  |
| 20261107T090012 | NEUTRAL | lucky | 36214.97 | labelled | -31.22 |  |  |  | None | no eligible comparator |
| 20261107T090012 | NEUTRAL | MAGA | 18658.35 | unknown | None |  |  |  | None | no eligible comparator |
| 20261107T090012 | NEUTRAL | GEO | 15518.43 | labelled | 36.52 |  |  |  | None | no eligible comparator |
| 20261107T100012 | NEUTRAL | PODS | 44285.70 | labelled | -100.0 |  |  |  | None | no eligible comparator |
| 20261107T110011 | NEUTRAL | Joe | 33643.84 | labelled | -100.0 |  |  |  | None | no eligible comparator |
| 20261107T120010 | NEUTRAL | duge | 26366.99 | labelled | 37.04 |  |  |  | None | no eligible comparator |
| 20261107T120010 | NEUTRAL | CHEWS | 22910.11 | no_valid_entry | None |  |  |  | None | no eligible comparator |
| 20261107T120010 | NEUTRAL | trauma | 22675.52 | labelled | -30.87 |  |  |  | None | no eligible comparator |
| 20261107T120010 | NEUTRAL | meme | 15288.21 | labelled | -37.08 |  |  |  | None | no eligible comparator |
| 20261107T130009 | NEUTRAL | DACITY | 33799.87 | labelled | 37.21 |  |  |  | None | no eligible comparator |
| 20261107T130009 | NEUTRAL | xZEC | 33001.69 | labelled | -4.66 |  |  |  | None | no eligible comparator |
| 20261107T130009 | NEUTRAL | POKEHOOD | 26488.13 | labelled | -68.65 |  |  |  | None | no eligible comparator |
| 20261107T130009 | NEUTRAL | cig | 18166.54 | labelled | -100.0 |  |  |  | None | no eligible comparator |
| 20261107T140008 | NEUTRAL | debtdog | 28636.15 | pending | None |  |  |  | None | no eligible comparator |
| 20261107T140008 | NEUTRAL | sherlock | 17227.13 | pending | None |  |  |  | None | no eligible comparator |
| 20261107T140008 | NEUTRAL | HOPE | 16678.30 | pending | None |  |  |  | None | no eligible comparator |
| 20261107T150008 | NEUTRAL | Intel AI | 39577.78 | pending | None |  |  |  | None | no eligible comparator |
| 20261107T150008 | NEUTRAL | PROPFUN | 17410.35 | pending | None |  |  |  | None | no eligible comparator |
