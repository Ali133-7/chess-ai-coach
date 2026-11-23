"""Chess AI Coach: completed-game monitoring and Arabic post-game analysis.

Chess.com PubAPI does NOT provide a real-time move feed for live human games.
Do not use engine assistance during an ongoing Chess.com game against a person.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import io
import json
import logging
import os
import secrets
from pathlib import Path
import sqlite3
from typing import Any

import chess
import chess.engine
import chess.pgn
import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

log = logging.getLogger("chess_coach")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

USERNAME = os.getenv("CHESS_USERNAME", "").strip().lower()
API_KEY = os.getenv("CHESS_API_KEY", "").strip()
STOCKFISH_PATH = os.getenv("STOCKFISH_PATH", "/usr/games/stockfish")
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "/data/chess_coach.sqlite3"))
POLL_SECONDS = max(120, int(os.getenv("POLL_SECONDS", "180")))
MAX_NEW_PER_POLL = max(1, min(10, int(os.getenv("MAX_NEW_PER_POLL", "3"))))
ANALYSIS_TIME_SECONDS = max(0.05, float(os.getenv("ANALYSIS_TIME_SECONDS", "0.12")))


class ManagedConnection(sqlite3.Connection):
    """A transaction context must also release its SQLite file handle."""
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def db_connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE_PATH, timeout=30, factory=ManagedConnection)
    db.row_factory = sqlite3.Row
    return db


def init_db() -> None:
    with db_connect() as db:
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                username TEXT NOT NULL,
                pgn TEXT NOT NULL,
                finished_at INTEGER NOT NULL,
                white TEXT NOT NULL,
                black TEXT NOT NULL,
                result TEXT NOT NULL,
                analysis_json TEXT,
                analysis_error TEXT,
                inserted_at TEXT NOT NULL
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS ix_games_finished ON games(finished_at DESC)")


def auth(x_api_key: str | None = Header(default=None)) -> None:
    if not API_KEY or not x_api_key or not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="Missing or incorrect X-API-Key")


def month_pairs(now: datetime) -> list[tuple[int, int]]:
    current = (now.year, now.month)
    previous = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
    return [current, previous]


def game_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]


def score_from_perspective(info: dict[str, Any], color: chess.Color) -> int:
    # Bound mate scores so a transition to or from mate is not reported as
    # ~100,000 centipawns. These are coaching heuristics, not true CP values.
    score = info["score"].pov(color)
    if score.is_mate():
        mate = score.mate()
        if mate is None:
            return 0
        return (1500 - min(abs(mate), 50) * 5) * (1 if mate > 0 else -1)
    return max(-1500, min(1500, score.score() or 0))


def pv_to_san(board: chess.Board, pv: list[chess.Move], limit: int = 5) -> list[str]:
    temp = board.copy()
    result = []
    for move in pv[:limit]:
        if move not in temp.legal_moves:
            break
        result.append(temp.san(move))
        temp.push(move)
    return result


def explain_move(played: str, best: str, loss: int, quality: str, line: list[str]) -> str:
    if played == best:
        return "اختيار ممتاز: هذه النقلة هي الأولى في تحليل المحرك لهذا الوضع."
    variation = "، ثم " + " ".join(line[1:4]) if len(line) > 1 else ""
    if quality == "هفوة كبيرة":
        return f"هذه النقلة أضعفت موقفك بشكل كبير. جرّب {best}{variation}، وقارن سلامة الملك والقطع."
    if quality == "خطأ":
        return f"هناك بديل أقوى هو {best}{variation}. قبل اللعب افحص التهديدات والأسرات المتاحة."
    if quality == "عدم دقة":
        return f"النقلة مقبولة لكن {best} أفضل حسب المحرك. قارن نشاط القطع والسيطرة على المركز."
    return f"نقلة جيدة إجمالاً؛ يقترح المحرك {best} كأفضل خيار في هذا الوضع."


def analyze_pgn_sync(pgn_text: str, username: str) -> dict[str, Any]:
    """Only call for a completed game retrieved from Chess.com's public archive."""
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise ValueError("Unable to parse PGN")
    result = game.headers.get("Result", "*")
    if result not in {"1-0", "0-1", "1/2-1/2"}:
        raise ValueError("Game is not complete; analysis refused")
    white = game.headers.get("White", "")
    black = game.headers.get("Black", "")
    if username.casefold() == white.casefold():
        player_color = chess.WHITE
    elif username.casefold() == black.casefold():
        player_color = chess.BLACK
    else:
        raise ValueError("Player does not match PGN")

    board = game.board()
    lessons: list[dict[str, Any]] = []
    with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
        for ply, move in enumerate(game.mainline_moves(), start=1):
            if move not in board.legal_moves:
                raise ValueError("PGN contains an illegal move")
            if board.turn != player_color:
                board.push(move)
                continue
            fen_before = board.fen()
            played_san = board.san(move)
            before = engine.analyse(board, chess.engine.Limit(time=ANALYSIS_TIME_SECONDS))
            best_pv = before.get("pv", [])
            best = board.san(best_pv[0]) if best_pv else played_san
            best_line = pv_to_san(board, best_pv)
            score_before = score_from_perspective(before, player_color)
            board.push(move)
            after = engine.analyse(board, chess.engine.Limit(time=ANALYSIS_TIME_SECONDS))
            score_after = score_from_perspective(after, player_color)
            loss = max(0, min(3000, score_before - score_after))
            # Centipawn loss here is approximate, based on shallow engine searches.
            quality = ("هفوة كبيرة" if loss >= 300 else "خطأ" if loss >= 150
                       else "عدم دقة" if loss >= 60 else "جيدة")
            lessons.append({
                "move_number": (ply + 1) // 2,
                "color": "white" if player_color == chess.WHITE else "black",
                "played": played_san,
                "best": best,
                "loss_cp": loss,
                "quality": quality,
                "best_line": best_line,
                "fen_before": fen_before,
                "explanation_ar": explain_move(played_san, best, loss, quality, best_line),
            })
    errors = [x for x in lessons if x["quality"] != "جيدة"]
    return {
        "player": username,
        "white": white,
        "black": black,
        "result": result,
        "note": "تحليل تعليمي تقريبي بعد انتهاء المباراة؛ قد تختلف التقييمات مع زيادة زمن المحرك.",
        "moves_reviewed": len(lessons),
        "errors": len(errors),
        "priority_lessons": sorted(errors, key=lambda x: x["loss_cp"], reverse=True)[:8],
        "all_player_moves": lessons,
    }


class Coach:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.stop = asyncio.Event()
        self.task: asyncio.Task | None = None
        self.last_checked: str | None = None
        self.last_error: str | None = None
        self.imported_last_sync = 0

    async def fetch_completed_games(self) -> list[dict[str, Any]]:
        if not USERNAME:
            raise ValueError("Set CHESS_USERNAME")
        games: list[dict[str, Any]] = []
        headers = {"User-Agent": "ChessAICoach/0.1 (personal post-game analysis)", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
            for year, month in month_pairs(datetime.now(timezone.utc)):
                url = f"https://api.chess.com/pub/player/{USERNAME}/games/{year}/{month:02d}"
                response = await client.get(url)
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                payload = response.json()
                for item in payload.get("games", []):
                    # The archive includes completed games. We also validate PGN result.
                    if item.get("end_time") and item.get("pgn") and item.get("url"):
                        games.append(item)
        games.sort(key=lambda x: x["end_time"], reverse=True)
        return games

    async def sync(self) -> dict[str, Any]:
        async with self.lock:
            self.imported_last_sync = 0
            try:
                games = await self.fetch_completed_games()
                # Scan a bounded recent window, then analyze only a few new games.
                # This allows catching up when several games finish between polls.
                for game in games[:100]:
                    if self.imported_last_sync >= MAX_NEW_PER_POLL:
                        break
                    gid = game_id(game["url"])
                    with db_connect() as db:
                        exists = db.execute("SELECT id FROM games WHERE id = ?", (gid,)).fetchone()
                    if exists:
                        continue
                    pgn = game["pgn"]
                    with db_connect() as db:
                        db.execute("""
                            INSERT OR IGNORE INTO games
                            (id,url,username,pgn,finished_at,white,black,result,inserted_at)
                            VALUES (?,?,?,?,?,?,?,?,?)
                        """, (
                            gid, game["url"], USERNAME, pgn, int(game["end_time"]),
                            str(game.get("white", {}).get("username", "")),
                            str(game.get("black", {}).get("username", "")),
                            str(game.get("white", {}).get("result", "")) + " / " +
                            str(game.get("black", {}).get("result", "")),
                            datetime.now(timezone.utc).isoformat(),
                        ))
                    # Keep API polling responsive. Heavy analysis is handled by the
                    # separate restart-safe deep-worker container, never in a web request.
                    self.imported_last_sync += 1
                self.last_error = None
            except Exception as exc:
                self.last_error = str(exc)
                log.exception("Chess.com sync failed")
            self.last_checked = datetime.now(timezone.utc).isoformat()
            return {"checked_at": self.last_checked, "new_games_analyzed": 0, "new_games_imported": self.imported_last_sync,
                    "error": self.last_error}

    async def loop(self) -> None:
        while not self.stop.is_set():
            await self.sync()
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=POLL_SECONDS)
            except asyncio.TimeoutError:
                pass


coach = Coach()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not USERNAME or len(API_KEY) < 32 or API_KEY.startswith("REPLACE_WITH_"):
        raise RuntimeError("Set CHESS_USERNAME and a strong, randomly generated CHESS_API_KEY in .env")
    init_db()
    from coach_plus import init_plus_db
    init_plus_db()
    from coach_advanced import init_issue_db
    init_issue_db()
    coach.task = asyncio.create_task(coach.loop())
    yield
    coach.stop.set()
    if coach.task is not None:
        await coach.task


app = FastAPI(title="Chess AI Coach", description="Completed-game coaching; no live-game assistance", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "post-game-only"}


@app.get("/api/status", dependencies=[Depends(auth)])
def status() -> dict[str, Any]:
    with db_connect() as db:
        count = db.execute("SELECT COUNT(*) AS n FROM games").fetchone()["n"]
    return {"username": USERNAME, "poll_seconds": POLL_SECONDS, "stored_games": count,
            "checked_at": coach.last_checked, "last_error": coach.last_error}


@app.post("/api/sync", dependencies=[Depends(auth)])
async def sync_now() -> dict[str, Any]:
    return await coach.sync()


@app.get("/api/games", dependencies=[Depends(auth)])
def list_games(limit: int = Query(default=10, ge=1, le=100)) -> dict[str, Any]:
    with db_connect() as db:
        rows = db.execute("""SELECT id,url,finished_at,white,black,result,
                          analysis_json IS NOT NULL AS analyzed,analysis_error
                          FROM games ORDER BY finished_at DESC LIMIT ?""", (limit,)).fetchall()
    return {"games": [dict(row) for row in rows]}


@app.get("/api/games/{gid}", dependencies=[Depends(auth)])
def get_game(gid: str) -> dict[str, Any]:
    with db_connect() as db:
        row = db.execute("SELECT * FROM games WHERE id = ?", (gid,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown game")
    data = dict(row)
    data["analysis"] = json.loads(data.pop("analysis_json")) if data["analysis_json"] else None
    return data


# INDEPENDENT TRAINING BOARD (not connected to any ongoing Chess.com match).
# Sessions are in RAM and reset on service restart. Each session starts from a
# fresh initial board and the user plays White against local Stockfish.
training_boards: dict[str, chess.Board] = {}


class TrainingMove(BaseModel):
    uci: str = Field(min_length=4, max_length=5, pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$")


def training_board(session_id: str) -> chess.Board:
    board = training_boards.get(session_id)
    if board is None:
        raise HTTPException(status_code=404, detail="Unknown training session")
    return board


def training_snapshot(board: chess.Board) -> dict[str, Any]:
    return {"fen": board.fen(), "turn": "white" if board.turn == chess.WHITE else "black",
            "is_game_over": board.is_game_over(claim_draw=True),
            "result": board.result(claim_draw=True) if board.is_game_over(claim_draw=True) else None,
            "moves_uci": [m.uci() for m in board.move_stack]}


@app.post("/api/training/start", dependencies=[Depends(auth)])
def training_start() -> dict[str, Any]:
    # Cap memory usage for a small personal service.
    if len(training_boards) >= 30:
        training_boards.pop(next(iter(training_boards)))
    sid = secrets.token_urlsafe(16)
    board = chess.Board()
    training_boards[sid] = board
    return {"session_id": sid, "mode": "isolated-training-vs-stockfish", **training_snapshot(board)}


@app.get("/api/training/{session_id}/hint", dependencies=[Depends(auth)])
def training_hint(session_id: str) -> dict[str, Any]:
    board = training_board(session_id)
    if board.is_game_over(claim_draw=True):
        raise HTTPException(status_code=409, detail="Training game is over")
    if board.turn != chess.WHITE:
        raise HTTPException(status_code=409, detail="Wait for computer turn")
    with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
        info = engine.analyse(board, chess.engine.Limit(time=max(0.25, ANALYSIS_TIME_SECONDS)))
    pv = info.get("pv", [])
    if not pv:
        raise HTTPException(status_code=503, detail="Stockfish did not return a variation")
    best = pv[0]
    san = board.san(best)
    if board.is_castling(best):
        reason = "التبييت يساعدك على حماية الملك وربط القلعتين."
    elif board.gives_check(best):
        reason = "هذه النقلة تعطي كش وتجبر الخصم على مواجهة تهديد الملك."
    elif board.is_capture(best):
        reason = "هذه النقلة تأخذ قطعة أو بيدقاً؛ افحص أيضاً الرد الممكن للخصم."
    else:
        reason = "هذا أفضل خيار بحسب تحليل Stockfish الحالي. قارن نشاط القطع وسلامة الملك."
    return {"best_uci": best.uci(), "best_san": san,
            "best_line_san": pv_to_san(board, pv), "explanation_ar": reason,
            "note": "للتدريب المستقل فقط؛ ليس للاستخدام أثناء مباراة ضد شخص على Chess.com."}


@app.post("/api/training/{session_id}/move", dependencies=[Depends(auth)])
def training_move(session_id: str, request: TrainingMove) -> dict[str, Any]:
    board = training_board(session_id)
    if board.is_game_over(claim_draw=True):
        raise HTTPException(status_code=409, detail="Training game is over")
    if board.turn != chess.WHITE:
        raise HTTPException(status_code=409, detail="It is not White's turn")
    try:
        move = chess.Move.from_uci(request.uci)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad UCI move") from exc
    if move not in board.legal_moves:
        raise HTTPException(status_code=400, detail="Illegal move")
    your_san = board.san(move)
    board.push(move)
    opponent_san = None
    if not board.is_game_over(claim_draw=True):
        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
            reply = engine.play(board, chess.engine.Limit(time=max(0.15, ANALYSIS_TIME_SECONDS))).move
        if reply is not None and reply in board.legal_moves:
            opponent_san = board.san(reply)
            board.push(reply)
    return {"your_move_san": your_san, "stockfish_move_san": opponent_san,
            **training_snapshot(board)}


# Additional post-game coaching, progress tracking and web UI. Existing API
# endpoints remain intact for older clients and the existing SQLite database.
from coach_plus import install as install_pro
install_pro(app)

# V3: additional review metrics and persistent coaching journal.
import coach_advanced as advanced
analyze_pgn_sync = advanced.analyze_pgn_advanced
advanced.install(app)

import coach_v5 as v5
v5.install(app)
