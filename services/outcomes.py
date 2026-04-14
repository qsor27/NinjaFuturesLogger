from models.browsing import Outcome
from models.position import Position


def classify_outcome(position: Position) -> Outcome:
    """Winner/Loser/Scratch/Open per doc 15's canonical definitions.

    - Open positions (no `dollars_pnl`) classify as "open".
    - Winner: dollars_pnl > commission (gross P&L beats costs).
    - Loser:  dollars_pnl < -commission.
    - Scratch: |dollars_pnl| <= commission.
    """
    if position.dollars_pnl is None:
        return "open"
    pnl = position.dollars_pnl
    commission = position.commission
    if pnl > commission:
        return "winner"
    if pnl < -commission:
        return "loser"
    return "scratch"
