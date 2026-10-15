# Otchet validatsii (v2, obnovleno 2026-10-15)
# Kishirilitsa vremenno latinicei: konsole Windows bez UTF-8 lomala proverku.

## Teplo / dinamika
# Statika Q=U*A*dT: tochnost +-15-30% (tablichnyi U).
# Dinamika 2 uzla (vozduh+pochva) + podshagi Eilera: stabilno, T_in v granitsah.
# Kalibrovka (U,N): beta=(X'X+lI)^-1 X'y. cond>30 = kollinearnost, nuzhen veter.
# Pochva: C=125 kVt*ch/K na 0.15 ga (sloi 0.2 m). Daet ~15 m3 gaza na 1 gradus.
# Provereno: simulate_no_heat(-5C, 12 ch): T_in -0.6 -> -1.8, T_soil 15.4 -> 9.9. OK.

## Toplivo
# Gaz: 4.18 tg/kVt*ch. Ugol horoshii: 6.31. Ugol pyl s peskom + zabityi kotel: 20.35.
# Vyvod: plohoi ugol v 3.4 raza dorozhe gaza za teplo (keis Shymkent-2023).
# Boiler_check: 382/400 OK; 500/400 NE TYANET -> ostatochnyi risk.

## Optimizator
# Demo -3C: P1 3001 kVt*ch/17504 tg, P2 econight 2652/15470, P3 ekran 1651/11504.
# Best=P3, saving 7002 tg/nochi. Reshenie EV: 17860 > 10504 -> TOPIT.
# Realnost -11C (13-15.03.2024): P1 5174/21638, P2 4703/19666, P3 3104/12983.

## Tsena (experimental)
# Shablon 12 strok: status need>=30 rows. R2=-11.8 na staroi sheme (utechka spread).
# Novaya shema v2: tolko lagi t-1 i starshe, 10 priznakov, TimeSeriesSplit,
# bazovye lag/seasonal, kalibrovka Platt. p_dump = INDEKS 0-1, ne veroiatnost.
# Primer: pred 390 vs 410 -> drop 4.9% -> p=0.494, days=8.
# Otkazano: Prophet/LightGBM otdelno (malyi n), ARIMA, PCSE, GreenLight kak zavisimost.
# Dopuschen: GBM depth=2 na ostatkah Ridge kak chlen ansamblya.

## Reshenie
# EV vmesto fiksirovannogo 0.5: heat esli p*Loss > Cost. p* = Cost/Loss adaptivnyi.
# Primer: p*=0.004-0.037 pri Loss 4.5 mln i Cost 10-19 tys. Porog 0.5 ustarel.
