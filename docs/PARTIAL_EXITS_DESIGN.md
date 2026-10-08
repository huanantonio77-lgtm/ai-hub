# PARTIAL EXITS + TRAILING STOP — s210 Design

## Проблема

Сейчас `_probe` возвращает один reason → одна сделка → весь объём выходит.
При target +50% мы теряем весь остаток роста (BGFRT s209 v2c +77.5% — вышли целиком на +50%).

## Параметры

| Параметр | Значение | Обоснование |
|---|---|---|
| PARTIAL_1_PCT | 0.50 | выйти половину |
| PARTIAL_1_LEVEL | +0.50 | при +50% (как s209 target) |
| PARTIAL_2_PCT | 0.30 | выйти треть остатка |
| PARTIAL_2_LEVEL | +1.00 | при +100% (post-mortem: >15% pump >100%) |
| TRAIL_PCT | 0.15 | trailing −15% от peak |
| TRAIL_ACTIVATE | +0.30 | trailing активен после +30% |
| STOP | −0.30 | hard stop на остаток |
| HOLD_S | 2400 | 40 мин |

## Изменения в pos

- size_remaining: 1.0 → 0.7 → 0.4
- size_original: 1.0
- peak_chg: max(chg) с момента entry
- partial_1_done / partial_2_done: bool
- realized_pnl_sol: sum partial exits

## Логика _probe

1. peak_chg = max(peak_chg, chg)
2. chg >= +0.50 AND !partial_1_done → exit 50%, reason=partial_1
3. chg >= +1.00 AND !partial_2_done → exit 30%, reason=partial_2
4. peak_chg >= +0.30 AND (peak_chg - chg) >= 0.15 → exit rest, reason=trail
5. chg <= −0.30 → exit rest, reason=stop
6. age >= 2400 → exit rest, reason=time

## Contract _probe

Было: (mint, pos, px, chg, age, reason)
Стало: (mint, pos, px, chg, age, reason, exit_pct)

tracker: если exit_pct < 1.0 → не удалять из OPEN, вычесть size_remaining.

## Research hints (deep_dive exits)

- ATR scaling with randomized entry points
- MinMax Drawdown Control framework
- Entry-Exit Cross-Validation
- Cross-correlation of entry and exit rules

## Из s209 post-mortem

- 3/20 mint pump >+100% за 5-60 мин
- 15% pump >100%, 20% dump <-10%, 65% flat
- Теоретический RR: +5.75% за сделку при ловле правильным сигналом
