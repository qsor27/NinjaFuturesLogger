from collections.abc import Sequence

from models.execution import Execution


def parse_position_column(value: str | None) -> int | None:
    """Parse NT's Position column into a signed running quantity.

    `-` means flat (0). `5 L` means +5, `3 S` means -3. Returns None for any
    input that can't be interpreted.
    """
    if value is None:
        return None
    s = value.strip()
    if s == "-":
        return 0
    parts = s.split()
    if len(parts) != 2:
        return None
    qty_s, tag = parts
    try:
        qty = int(qty_s)
    except ValueError:
        return None
    if qty < 0:
        return None
    if tag == "L":
        return qty
    if tag == "S":
        return -qty
    return None


def _signed_delta(ex: Execution) -> int:
    return ex.quantity if ex.side == "Buy" else -ex.quantity


def _reorder_tied_group(
    group: list[Execution], running_qty_before: int
) -> tuple[list[Execution], int]:
    """Greedily reorder a same-timestamp group so each fill's signed delta
    lands on its `position_after` value. Falls back to id-ascending order
    for any tail that can't be reconciled (missing or inconsistent
    `position_after`).
    """
    remaining = list(group)
    running = running_qty_before
    ordered: list[Execution] = []

    while remaining:
        found_idx: int | None = None
        for idx, ex in enumerate(remaining):
            target = parse_position_column(ex.position_after)
            if target is not None and running + _signed_delta(ex) == target:
                found_idx = idx
                break

        if found_idx is None:
            remaining.sort(key=lambda e: e.nt_execution_id)
            for ex in remaining:
                running += _signed_delta(ex)
            ordered.extend(remaining)
            return ordered, running

        ex = remaining.pop(found_idx)
        running += _signed_delta(ex)
        ordered.append(ex)

    return ordered, running


def order_executions_for_walk(executions: Sequence[Execution]) -> list[Execution]:
    """Return executions in the order `build_positions` should walk them.

    Primary key is `timestamp`. For same-timestamp groups, the order is
    reconstructed from `position_after` so that each fill's signed delta
    matches NT's authoritative Position column. If reconstruction fails for
    any group, that group falls back to `nt_execution_id` ascending — the
    integrity check will still flag the mismatch.
    """
    by_ts = sorted(executions, key=lambda e: (e.timestamp, e.nt_execution_id))
    ordered: list[Execution] = []
    running = 0
    i = 0
    n = len(by_ts)
    while i < n:
        j = i + 1
        while j < n and by_ts[j].timestamp == by_ts[i].timestamp:
            j += 1
        group = by_ts[i:j]
        if len(group) == 1:
            ordered.append(group[0])
            running += _signed_delta(group[0])
        else:
            reordered, running = _reorder_tied_group(group, running)
            ordered.extend(reordered)
        i = j
    return ordered
