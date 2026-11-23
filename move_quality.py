"""Independent, transparent educational move-quality labels. Not Chess.com classifications."""
from __future__ import annotations
from math import exp
import chess

CATEGORIES = {
    'brilliant': ('مدهشة', '‼'),
    'excellent': ('ممتازة', '!'),
    'good': ('جيدة', '✓'),
    'weak': ('ضعيفة', '⁈'),
    'missed': ('ضياع فرصة', '○'),
    'mistake': ('خطأ', '?'),
    'blunder': ('خطأ فادح', '??'),
}
LEGACY = {'best':'excellent', 'inaccuracy':'weak', 'هفوة كبيرة':'blunder',
          'الأفضل':'excellent', 'عدم دقة':'weak','جيدة':'good', 'ممتازة':'excellent',
          'خطأ':'mistake','غير دقيقة':'weak','نقلة قانونية':None}
ERROR_CODES = frozenset(('weak','missed','mistake','blunder'))

def normalize(code: str | None) -> str | None:
    if not code: return None
    if code in CATEGORIES: return code
    return LEGACY.get(code)

def label(code: str | None) -> str | None:
    result=normalize(code)
    return CATEGORIES[result][0] if result else None

def classify(loss: float, best: bool, chance_drop: float = 0, *, missed: bool = False,
             brilliant: bool = False) -> str:
    """Approximate thresholds, with priority for missed chances and sacrifices."""
    if best and brilliant and loss <= 20: return 'brilliant'
    if best and loss <= 25: return 'excellent'
    if loss <= 55: return 'good'
    if missed and loss >= 140: return 'missed'
    if loss <= 130 and chance_drop < 12: return 'weak'
    if loss <= 270 and chance_drop < 27: return 'mistake'
    return 'blunder'

def clear_missed_chance(before_cp: int, after_cp: int, loss: float) -> bool:
    """A large collapse from a clear practical winning chance; not every suboptimal move."""
    return before_cp >= 250 and after_cp <= 50 and loss >= 200

def candidate_sacrifice(board: chess.Board, move: chess.Move, best_line: list[str],
                        before_cp: int, after_cp: int) -> bool:
    """Strict candidate: best quiet non-pawn offer, taken in PV, position still tenable.

    This does not mean it is officially a 'Brilliant' Chess.com move.
    """
    if move not in board.legal_moves or board.is_capture(move) or len(best_line)<3:
        return False
    piece=board.piece_at(move.from_square)
    if not piece or piece.piece_type not in (chess.KNIGHT,chess.BISHOP,chess.ROOK,chess.QUEEN):
        return False
    if before_cp < -100 or before_cp > 450 or after_cp < -100:
        return False
    trial=board.copy();trial.push(move)
    try:
        response=trial.parse_san(best_line[1])
        return trial.is_capture(response) and response.to_square==move.to_square
    except (ValueError,chess.IllegalMoveError,chess.AmbiguousMoveError):
        return False
