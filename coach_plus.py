"""Chess AI Coach Pro: review, study plans, adaptive puzzles and isolated practice.

Only games with a conclusive final PGN result in the public Chess.com archive
are eligible for review and puzzle generation. Never analyze active human games.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import io
import os
import json
import logging
import re
import secrets
import threading
import time
from typing import Any
from urllib.parse import unquote

import chess
import chess.engine
import chess.pgn
from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

import main as core
import move_quality as grades

log = logging.getLogger("chess_coach.pro")
MAX_PGN_PLIES = 600
MAX_ACTIVE_SESSIONS = 20
SESSION_TTL_SECONDS = 6 * 3600
_training_lock = threading.RLock()
_sessions: dict[str, dict[str, Any]] = {}


def init_plus_db() -> None:
    with core.db_connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS puzzle_progress (
            game_id TEXT NOT NULL,
            ply INTEGER NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            solves INTEGER NOT NULL DEFAULT 0,
            streak INTEGER NOT NULL DEFAULT 0,
            next_due_at TEXT NOT NULL,
            last_attempt_at TEXT,
            PRIMARY KEY (game_id,ply),
            FOREIGN KEY (game_id) REFERENCES games(id)
        )""")


def completed_game(pgn: str) -> chess.pgn.Game:
    if len(pgn) > 300_000:
        raise HTTPException(status_code=422, detail="PGN too large")
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None or game.headers.get("Result") not in {"1-0", "0-1", "1/2-1/2"}:
        raise HTTPException(status_code=422, detail="Only completed games can be reviewed")
    if game.errors:
        raise HTTPException(status_code=422, detail="PGN has parse errors")
    return game


def get_row(gid: str):
    if not re.fullmatch(r"[a-f0-9]{20}", gid):
        raise HTTPException(status_code=404, detail="Unknown game")
    with core.db_connect() as db:
        row = db.execute("SELECT * FROM games WHERE id=?", (gid,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown game")
    return row


def analysis_for(row) -> dict:
    if not row["analysis_json"]:
        return {}
    try:
        return json.loads(row["analysis_json"])
    except json.JSONDecodeError:
        return {}


def player_won(game: chess.pgn.Game) -> str:
    result = game.headers.get("Result", "*")
    if result == "1/2-1/2":
        return "draw"
    if result not in {"1-0", "0-1"}:
        return "unknown"
    player_color = "white" if game.headers.get("White", "").casefold() == core.USERNAME else "black"
    winner = "white" if result == "1-0" else "black"
    return "win" if winner == player_color else "loss"


def opening_name(game: chess.pgn.Game) -> str:
    if game.headers.get("Opening"):
        return game.headers["Opening"]
    url = game.headers.get("ECOUrl", "")
    if "/openings/" in url:
        slug = url.split("/openings/")[-1].split("?")[0].replace("-", " ")
        return unquote(slug)[:110]
    return game.headers.get("ECO", "غير مصنف")


def phase(board: chess.Board, ply: int) -> str:
    if ply <= 20:
        return "opening"
    major = sum(1 for p in board.piece_map().values() if p.piece_type in (chess.QUEEN, chess.ROOK))
    non_pawns = sum(1 for p in board.piece_map().values() if p.piece_type not in (chess.PAWN, chess.KING))
    return "endgame" if (non_pawns <= 5 or (major <= 1 and ply > 35)) else "middlegame"


def classify_concept(board: chess.Board, move: chess.Move | None) -> tuple[str, str]:
    if move is None or move not in board.legal_moves:
        return ("حساب التهديدات", "قبل النقلة افحص تهديدات الخصم والقطع غير المحمية.")
    piece = board.piece_at(move.from_square)
    if board.is_castling(move):
        return ("سلامة الملك", "التبييت يبعد الملك عن المركز ويساعد القلعتين على الاتصال.")
    if move.promotion:
        return ("ترقية بيدق", "ترقية البيدق تمنحك قوة إضافية وقد تحسم نهاية المباراة.")
    if board.gives_check(move):
        return ("نقلة إجبارية", "الكش يفرض على الخصم الرد؛ افحص سلسلة الكشات قبل النقلات الهادئة.")
    if board.is_capture(move):
        return ("تكتيك وأسر", "احسب القطعة المأخوذة ورد الخصم ثم قيّم تبادل القطع.")
    if piece and piece.piece_type == chess.PAWN and chess.square_file(move.to_square) in (3, 4):
        return ("السيطرة على المركز", "بيدق المركز يساعد على تقييد قطع الخصم وفتح الخطوط لقطعك.")
    if piece and piece.piece_type == chess.KING:
        return ("نشاط الملك", "في نهاية المباراة يصبح الملك قطعة هجومية مهمة لدعم البيادق.")
    return ("تحسين القطع", "ابحث عن مربعات نشيطة، واحسب التهديدات قبل تثبيت خطتك.")


def match_lesson(analysis: dict, ply: int, color: str) -> dict | None:
    for entry in analysis.get("all_player_moves", []):
        expected = 2 * int(entry.get("move_number", 0)) - (1 if color == "white" else 0)
        if expected == ply and entry.get("color") == color:
            return entry
    return None


def review_data(row) -> dict:
    game = completed_game(row["pgn"])
    analysis = analysis_for(row)
    board = game.board()
    plies = [{"ply": 0, "san": "", "uci": "", "fen": board.fen(), "played_by": "", "move_number": 0,
              "phase": "opening", "quality": None, "lesson": None, "legal_moves": [m.uci() for m in board.legal_moves]}]
    full_by_ply = {x["ply"]: x for x in analysis.get("all_moves", []) if "ply" in x}
    for i, move in enumerate(game.mainline_moves(), 1):
        if i > MAX_PGN_PLIES:
            break
        if move not in board.legal_moves:
            raise HTTPException(status_code=422, detail="Illegal PGN move")
        san = board.san(move)
        color = "white" if board.turn == chess.WHITE else "black"
        lesson = full_by_ply.get(i) or match_lesson(analysis, i, color)
        legal_before = [x.uci() for x in board.legal_moves]
        concept, concept_tip = classify_concept(board, move)
        if lesson:
            lesson = {**lesson, "concept": concept, "concept_tip": concept_tip}
        board.push(move)
        plies.append({"ply": i, "san": san, "uci": move.uci(), "fen": board.fen(),
                      "played_by": color, "move_number": (i + 1) // 2,
                      "phase": phase(board, i), "quality": lesson.get("quality") if lesson else None,
                      "quality_code": grades.normalize(lesson.get("quality_code") or lesson.get("quality")) if lesson else None,
                      "legal_moves": [x.uci() for x in board.legal_moves],
                      "legal_moves_before": legal_before, "lesson": lesson})
    return {"id": row["id"], "url": row["url"], "white": row["white"], "black": row["black"],
            "player_color": "white" if game.headers.get("White", "").casefold() == core.USERNAME else "black",
            "result": player_won(game), "pgn_result": game.headers.get("Result"),
            "opening": opening_name(game), "eco": game.headers.get("ECO", ""),
            "time_control": game.headers.get("TimeControl", ""),
            "finished_at": row["finished_at"], "total_plies": len(plies) - 1,
            "analysis_ready": bool(analysis), "errors": analysis.get("errors", 0),
            "moves_reviewed": analysis.get("moves_reviewed", 0), "plies": plies,
            "accuracy_estimate": analysis.get("accuracy_estimate"),
            "average_centipawn_loss": analysis.get("average_centipawn_loss"),
            "evaluation_graph": analysis.get("evaluation_graph", []),
            "quality_counts": analysis.get("quality_counts", {}),
            "phases": analysis.get("phases", {}),
            "players_comparison": analysis.get("players_comparison", {}),
            "time_management": analysis.get("time_management", {}),
            "note": "تعليم ومراجعة بعد انتهاء المباراة فقط. تقييمات Stockfish تقريبية وتختلف حسب زمن التحليل."}


def compact_review(row) -> dict:
    game = completed_game(row["pgn"])
    a = analysis_for(row)
    all_lessons = a.get("all_player_moves", [])
    by_quality = Counter(x.get("quality", "") for x in all_lessons)
    return {"id": row["id"], "url": row["url"], "finished_at": row["finished_at"],
            "white": row["white"], "black": row["black"], "result": player_won(game),
            "opening": opening_name(game), "eco": game.headers.get("ECO", ""),
            "analyzed": bool(a), "errors": a.get("errors", 0),
            "reviewed": a.get("moves_reviewed", 0), "qualities": dict(by_quality)}


def all_games(limit: int = 100) -> list:
    with core.db_connect() as db:
        return db.execute("SELECT * FROM games ORDER BY finished_at DESC LIMIT ?", (limit,)).fetchall()


def exercise_id(gid: str, ply: int) -> str:
    return f"{gid}.{ply}"


def make_puzzles(rows, include_answers: bool = False) -> list[dict]:
    puzzles: list[dict] = []
    progress = {}
    with core.db_connect() as db:
        progress = {(r["game_id"], r["ply"]): dict(r) for r in db.execute("SELECT * FROM puzzle_progress").fetchall()}
    for row in rows:
        a = analysis_for(row)
        color = "white" if row["white"].casefold() == core.USERNAME else "black"
        for move in a.get("all_player_moves", []):
            if grades.normalize(move.get('quality_code') or move.get('quality')) not in grades.ERROR_CODES:
                continue
            n = move.get("move_number")
            if not isinstance(n, int):
                continue
            ply = 2*n-(1 if color == "white" else 0)
            fen = move.get("fen_before", "")
            try:
                board = chess.Board(fen)
                best = board.parse_san(move.get("best", ""))
                played = board.parse_san(move.get("played", ""))
            except (ValueError, AssertionError, TypeError):
                continue
            if board.turn != (color == "white") or best == played:
                continue
            concept, tip = classify_concept(board, best)
            p = progress.get((row["id"], ply), {})
            item = {"id": exercise_id(row["id"], ply), "game_id": row["id"], "ply": ply,
                    "move_number": n, "fen": fen, "color": color, "quality": move.get("quality"), "quality_code": grades.normalize(move.get("quality_code") or move.get("quality")),
                    "difficulty": "تحدٍّ" if move.get("quality") == "هفوة كبيرة" else "تدريب",
                    "concept": concept, "hint": tip, "legal_moves": [m.uci() for m in board.legal_moves], "next_due_at": p.get("next_due_at"),
                    "attempts": p.get("attempts", 0), "solves": p.get("solves", 0), "streak": p.get("streak", 0)}
            if include_answers:
                item.update({"best_san": move.get("best"), "best_uci": best.uci(),
                             "played_san": move.get("played"), "explanation_ar": move.get("explanation_ar", ""),
                             "best_line": move.get("best_line", []),
                             "top_lines": move.get("top_lines", []),"coaching":move.get("coaching",{}),"scenarios":move.get("scenarios",[])})
            puzzles.append(item)
    now = datetime.now(timezone.utc).isoformat()
    puzzles.sort(key=lambda p: (bool(p["next_due_at"] and p["next_due_at"] > now),
                                p["solves"] > 0, p["attempts"], -p["ply"]))
    return puzzles


def insight_data() -> dict:
    rows = all_games(150)
    recs = []
    lessons = []
    for r in rows:
        try:
            rec = compact_review(r)
        except HTTPException:
            continue
        recs.append(rec)
        a = analysis_for(r)
        for x in a.get("all_player_moves", []):
            if grades.normalize(x.get('quality_code') or x.get('quality')) in grades.ERROR_CODES:
                lessons.append({**x, "game_id": r["id"]})
    c = Counter(x["result"] for x in recs)
    opening = defaultdict(lambda: {"games": 0, "wins": 0, "losses": 0, "draws": 0})
    for r in recs:
        key = r["opening"]
        opening[key]["games"] += 1
        if r["result"] in ("win", "loss", "draw"):
            opening[key]["wins" if r["result"] == "win" else "losses" if r["result"] == "loss" else "draws"] += 1
    quality_count = Counter(x.get("quality", "") for x in lessons)
    by_phase = Counter()
    by_move = Counter()
    for x in lessons:
        n = x.get("move_number", 1)
        ph = "الافتتاح" if n <= 10 else "وسط اللعب" if n <= 25 else "النهايات"
        by_phase[ph] += 1
        by_move[str(n)] += 1
    themes = []
    for phase_name, number in by_phase.most_common(3):
        tip = {"الافتتاح": "طوّر القطع بسرعة، أمّن الملك، ولا تُحرّك نفس القطعة بلا ضرورة.",
               "وسط اللعب": "قبل كل نقلة ابحث عن الكش والأسر والتهديد، ثم ضع خطة.",
               "النهايات": "نشّط الملك، راقب البيادق المارّة، واحسب سباق الترقية."}[phase_name]
        themes.append({"phase": phase_name, "errors": number, "tip": tip})
    p = make_puzzles(rows)
    due = sum(1 for x in p if not x["next_due_at"] or x["next_due_at"] <= datetime.now(timezone.utc).isoformat())
    return {"username": core.USERNAME, "games": len(recs), "analyzed": sum(r["analyzed"] for r in recs),
            "wins": c["win"], "losses": c["loss"], "draws": c["draw"],
            "total_reviewed_moves": sum(r["reviewed"] for r in recs),
            "mistakes": sum(r["errors"] for r in recs), "mistake_categories": dict(quality_count),
            "recent": recs[:14], "openings": sorted(({"name": k, **v} for k, v in opening.items()), key=lambda x: -x["games"])[:12],
            "weak_phases": themes, "puzzles_available": len(p), "puzzles_due": due,
            "notice": "هذه إحصاءات تعليمية تقريبية وليست دقة Chess.com الرسمية. التحليل للمباريات المكتملة حصراً."}


class PuzzleAttempt(BaseModel):
    uci: str = Field(min_length=4, max_length=5, pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$")


class NewTraining(BaseModel):
    color: str = Field(default="white", pattern=r"^(white|black)$")
    strength: int = Field(default=20, ge=0, le=20)


class TrainingMove(BaseModel):
    uci: str = Field(min_length=4, max_length=5, pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$")


def engine_strength(engine, strength: int):
    if "Skill Level" in engine.options:
        engine.configure({"Skill Level": strength})
    if "UCI_LimitStrength" in engine.options:
        engine.configure({"UCI_LimitStrength": False})
    if "Threads" in engine.options:
        engine.configure({"Threads": 1})
    if "Hash" in engine.options:
        engine.configure({"Hash": 32})


def training_snapshot(session: dict) -> dict:
    board: chess.Board = session["board"]
    return {"session_id": session["sid"], "fen": board.fen(),
            "color": session["color"], "strength": session["strength"],
            "turn": "white" if board.turn else "black", "ended": board.is_game_over(claim_draw=True),
            "result": board.result(claim_draw=True) if board.is_game_over(claim_draw=True) else None,
            "legal_moves": [x.uci() for x in board.legal_moves] if not board.is_game_over(claim_draw=True) else [],
            "history": session["history"][:], "hints_used": session["hints_used"]}


def robot_reply(session: dict) -> dict | None:
    board: chess.Board = session["board"]
    if board.is_game_over(claim_draw=True):
        return None
    with chess.engine.SimpleEngine.popen_uci(core.STOCKFISH_PATH) as engine:
        engine_strength(engine, session["strength"])
        # Skill 20 has an independent, stronger search budget. Do not confuse
        # the quick feedback budget with opponent strength.
        thinking = max(.3, min(20.0, float(os.getenv('TRAINING_ENGINE_SECONDS','4.0')))) if session["strength"] >= 18 else (1.2 if session["strength"] >= 12 else .45)
        result = engine.play(board, chess.engine.Limit(time=thinking))
        move = result.move
    if move is None or move not in board.legal_moves:
        return None
    san = board.san(move)
    turn = "white" if board.turn else "black"
    feedback=calculate_feedback(board,move)
    board.push(move)
    item = {"uci": move.uci(), "san": san, "color": turn, "who": "engine", "fen": board.fen(),
            "quality_code": feedback.get('quality_code'), "quality_label": feedback.get('label')}
    session["history"].append(item)
    return item


def get_session(sid: str) -> dict:
    with _training_lock:
        s = _sessions.get(sid)
        if not s or time.time() - s["updated"] > SESSION_TTL_SECONDS:
            _sessions.pop(sid, None)
            raise HTTPException(status_code=404, detail="Training session expired or not found")
        s["updated"] = time.time()
        return s


def calculate_feedback(board: chess.Board, move: chess.Move) -> dict:
    """Small bounded approximate score; only local, independent training positions."""
    try:
        with chess.engine.SimpleEngine.popen_uci(core.STOCKFISH_PATH) as engine:
            engine_strength(engine, 14)
            limit = chess.engine.Limit(time=max(.10, min(.30, core.ANALYSIS_TIME_SECONDS)))
            info = engine.analyse(board, limit)
            pv = info.get("pv", [])
            best = board.san(pv[0]) if pv else board.san(move)
            before = core.score_from_perspective(info, board.turn)
            b = board.copy()
            b.push(move)
            after = engine.analyse(b, limit)
            loss = max(0, min(3000, before - core.score_from_perspective(after, board.turn)))
        code=grades.classify(loss, bool(pv and move==pv[0]), 0)
        import coach_brain as brain
        narrative=brain.explain(board,move,pv[0] if pv else move,code,loss,
                 [{'uci':pv[0].uci(),'pv_uci':[m.uci() for m in pv[:10]]}] if pv else [])
        return {"label": grades.label(code), "quality_code": code, "loss_cp": loss, "best_san": best,
                "message": narrative['text'] + " التقييم تقريبي لأن زمن التدريب قصير."}
    except (OSError, chess.engine.EngineError, chess.engine.EngineTerminatedError) as exc:
        log.warning("Training evaluation unavailable: %s", exc)
        return {"label": "غير مُقيّمة", "quality_code": None, "loss_cp": None, "best_san": None, "message": "تعذر تقييم النقلة؛ لن نعرض درجة تخمينية."}


def install(app):
    @app.get("/")
    def homepage():
        from fastapi.responses import FileResponse
        return FileResponse(str(Path(__file__).parent / "web" / "index.html"), headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'"})

    from fastapi.staticfiles import StaticFiles
    app.mount("/assets", StaticFiles(directory=str(Path(__file__).parent / "web"), check_dir=True), name="assets")

    @app.get("/api/pro/dashboard", dependencies=[Depends(core.auth)])
    def dashboard():
        return insight_data()

    @app.get("/api/pro/games", dependencies=[Depends(core.auth)])
    def games(limit: int = Query(default=50, ge=1, le=150), page: int = Query(default=1, ge=1, le=50)):
        with core.db_connect() as db:
            total = db.execute("SELECT COUNT(*) AS n FROM games").fetchone()["n"]
            rows = db.execute("SELECT * FROM games ORDER BY finished_at DESC LIMIT ? OFFSET ?", (limit, (page-1)*limit)).fetchall()
        out = []
        for r in rows:
            try:
                out.append(compact_review(r))
            except HTTPException:
                continue
        return {"games": out, "total": total, "page": page, "limit": limit}

    @app.get("/api/pro/review/{gid}", dependencies=[Depends(core.auth)])
    def review(gid: str):
        return review_data(get_row(gid))

    @app.get("/api/pro/puzzles", dependencies=[Depends(core.auth)])
    def puzzles(limit: int = Query(default=50, ge=1, le=150)):
        items = make_puzzles(all_games(150))
        return {"puzzles": items[:limit], "total": len(items),
                "notice": "التمارين مستخرجة فقط من مباريات Chess.com التي انتهت بالفعل."}

    @app.post("/api/pro/puzzles/{gid}/{ply}/attempt", dependencies=[Depends(core.auth)])
    def solve(gid: str, ply: int, request: PuzzleAttempt):
        if not (1 <= ply <= MAX_PGN_PLIES):
            raise HTTPException(status_code=404, detail="Puzzle not found")
        row = get_row(gid)
        selected = next((x for x in make_puzzles([row], True) if x["ply"] == ply), None)
        if selected is None:
            raise HTTPException(status_code=404, detail="Puzzle not found")
        board = chess.Board(selected["fen"])
        try:
            move = chess.Move.from_uci(request.uci)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid UCI move") from exc
        if move not in board.legal_moves:
            raise HTTPException(status_code=422, detail="Illegal move for this puzzle")
        correct = move.uci() == selected["best_uci"]
        # The puzzle outcome is separate from objective quality. A non-solution may
        # still be a good chess move, so ask the engine rather than marking it 'missed'.
        move_grade = {'quality_code':'excellent','label':'ممتازة'} if correct else calculate_feedback(board, move)
        with core.db_connect() as db:
            old = db.execute("SELECT * FROM puzzle_progress WHERE game_id=? AND ply=?", (gid, ply)).fetchone()
            streak = (old["streak"] + 1 if old else 1) if correct else 0
            delay_days = min(30, 2**max(0, streak-1)) if correct else 0
            due = (datetime.now(timezone.utc) + timedelta(days=delay_days)).isoformat()
            db.execute("""INSERT INTO puzzle_progress(game_id,ply,attempts,solves,streak,next_due_at,last_attempt_at)
                    VALUES(?,?,1,?,?,?,?)
                    ON CONFLICT(game_id,ply) DO UPDATE SET
                    attempts=attempts+1, solves=solves+excluded.solves, streak=excluded.streak,
                    next_due_at=excluded.next_due_at,last_attempt_at=excluded.last_attempt_at""",
                    (gid, ply, 1 if correct else 0, streak, due, datetime.now(timezone.utc).isoformat()))
            state = 'resolved' if streak >= 3 else 'practicing'
            db.execute('''INSERT INTO issue_journal(game_id,ply,status,notes,updated_at) VALUES (?,?,?,?,?)
              ON CONFLICT(game_id,ply) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at''',
              (gid, ply, state, '', datetime.now(timezone.utc).isoformat()))
        played_san = board.san(move)
        board.push(move)
        return {"correct": correct, "played_san": played_san, "played_uci": move.uci(),
                "after_fen": board.fen(), "best_san": selected["best_san"],
                "best_uci": selected["best_uci"], "concept": selected["concept"],
                "quality_code": move_grade.get('quality_code'),
                "quality_note": 'تصنيف تعليمي تقريبي لنقلة التدريب، وليس تقييم Chess.com الرسمي.',
                "success_explanation_ar": f'أحسنت! اختيارك {played_san} طابق الحل الأقوى المحفوظ. '
                    + (selected.get('coaching',{}).get('best_reason') or selected['hint'])
                    + ' راقب رد الخصم في السيناريوهات المعروضة ولا تفترض أنه سيختار رداً واحداً.',
                "mistake_explanation_ar": f'لعبت {played_san} بدلاً من {selected["best_san"]}. '
                    + (selected.get('coaching',{}).get('best_reason') or selected['hint'])
                    + f' هذا لا يعني أن {played_san} خطأ فادح بالضرورة؛ درجته مستقلة عن صحة التحدي.',
                "best_line": selected.get("best_line", []),
                "scenarios": [{"first":ln.get('first') or ln.get('san'), "moves":ln.get('moves') or ln.get('line', [])[:12],
                    "pv_uci":ln.get('pv_uci',[]),"white_cp":ln.get('cp_white'),
                    "summary":ln.get('summary','')} for ln in (selected.get('scenarios') or selected.get('top_lines', []))[:3]],
                "next_due_at": due, "streak": streak}

    @app.get('/api/pro/puzzles/{gid}/{ply}/hint', dependencies=[Depends(core.auth)])
    def puzzle_visual_hint(gid:str,ply:int):
        row=get_row(gid)
        selected=next((x for x in make_puzzles([row],True) if x['ply']==ply),None)
        if not selected:raise HTTPException(status_code=404,detail='Puzzle not found')
        return {'best_uci':selected['best_uci'],'best_san':selected['best_san'],
                'concept':selected['concept'],'explanation_ar':selected['hint'],
                'best_line':selected.get('best_line',[])}

    @app.post('/api/pro/puzzles/{gid}/{ply}/continue', dependencies=[Depends(core.auth)])
    def continue_puzzle(gid:str,ply:int,request:TrainingMove):
        row=get_row(gid)
        selected=next((x for x in make_puzzles([row],True) if x['ply']==ply),None)
        if not selected:raise HTTPException(status_code=404,detail='Puzzle not found')
        board=chess.Board(selected['fen'])
        move=chess.Move.from_uci(request.uci)
        if move not in board.legal_moves:
            raise HTTPException(status_code=422,detail='Illegal puzzle continuation')
        san=board.san(move)
        initial_grade={'quality_code':'excellent'} if move.uci()==selected['best_uci'] else calculate_feedback(board,move)
        board.push(move)
        with _training_lock:
            for sid,old in list(_sessions.items()):
                if time.time()-old['updated']>SESSION_TTL_SECONDS:_sessions.pop(sid,None)
            while len(_sessions)>=MAX_ACTIVE_SESSIONS:_sessions.pop(next(iter(_sessions)))
            sid=secrets.token_urlsafe(18)
            session={'sid':sid,'board':board,'color':selected['color'],'strength':8,
                     'history':[{'uci':move.uci(),'san':san,'color':selected['color'],'who':'you',
                                 'fen':board.fen(),'quality_code':initial_grade.get('quality_code')}],
                     'hints_used':0,'updated':time.time()}
            # Only a private practice position from a completed archived Chess.com game.
            _sessions[sid]=session
            if not board.is_game_over(claim_draw=True):robot_reply(session)
            return training_snapshot(session)

    @app.post("/api/pro/games/{gid}/reanalyze", dependencies=[Depends(core.auth)])
    async def reanalyze(gid: str):
        row = get_row(gid)
        # Reanalysis only from archived, completed PGN, never active games.
        completed_game(row["pgn"])
        async with core.coach.lock:
            try:
                analysis = await __import__("asyncio").to_thread(core.analyze_pgn_sync, row["pgn"], core.USERNAME)
            except Exception as exc:
                log.exception("Reanalysis failed for %s", gid)
                raise HTTPException(status_code=503, detail="Reanalysis failed; check server logs") from exc
            with core.db_connect() as db:
                db.execute("UPDATE games SET analysis_json=?,analysis_error=NULL WHERE id=?",
                           (json.dumps(analysis, ensure_ascii=False), gid))
        return {"ok": True, "game_id": gid, "moves_reviewed": analysis["moves_reviewed"], "errors": analysis["errors"]}

    @app.get("/api/pro/plan", dependencies=[Depends(core.auth)])
    def study_plan():
        d = insight_data()
        p = d["weak_phases"][0]["phase"] if d["weak_phases"] else "وسط اللعب"
        focus = {"الافتتاح": "سلامة الملك وتطوير القطع", "وسط اللعب": "التكتيكات وفحص التهديدات", "النهايات": "البيادق المارّة ونشاط الملك"}.get(p, "التكتيكات")
        return {"focus": focus, "based_on": d["games"],
                "days": [
                    {"day": "السبت", "title": "مراجعة أخطاءك", "minutes": 20, "action": "اختر مباراة وافحص أخطاءك قبل فتح اقتراح المحرك"},
                    {"day": "الأحد", "title": "تمارين من مبارياتك", "minutes": 20, "action": "حل 5 إلى 10 تمارين وراجع التي أخطأت فيها"},
                    {"day": "الاثنين", "title": focus, "minutes": 25, "action": "حل مواقف مرتبطة بأكثر مرحلة تكرر فيها الخطأ"},
                    {"day": "الثلاثاء", "title": "مباراة تدريبية", "minutes": 20, "action": "العب ضد محرك التدريب واطلب تلميحاً عند التعثر"},
                    {"day": "الأربعاء", "title": "درس افتتاح", "minutes": 15, "action": "راجع افتتاحاً تكرر في مبارياتك وطبّق مبادئه"},
                    {"day": "الخميس", "title": "التفكير بالنقلة", "minutes": 20, "action": "تدرّب على فحص الكش والأسر والتهديدات قبل كل نقلة"},
                    {"day": "الجمعة", "title": "قياس التقدم", "minutes": 15, "action": "راجع نتائج الأسبوع وأعد التمارين المستحقة"},
                ], "note": "برنامج تعليمي تلقائي يتكيف مع أخطاء الأرشيف، وليس مدرباً بشرياً معتمداً."}

    @app.post("/api/pro/training", dependencies=[Depends(core.auth)])
    def new_training(request: NewTraining):
        with _training_lock:
            for sid, session in list(_sessions.items()):
                if time.time()-session["updated"] > SESSION_TTL_SECONDS:
                    _sessions.pop(sid, None)
            while len(_sessions) >= MAX_ACTIVE_SESSIONS:
                _sessions.pop(next(iter(_sessions)))
            sid = secrets.token_urlsafe(18)
            session = {"sid": sid, "board": chess.Board(), "color": request.color,
                       "strength": request.strength, "history": [], "hints_used": 0,
                       "updated": time.time()}
            _sessions[sid] = session
            if request.color == "black":
                robot_reply(session)
            return training_snapshot(session)

    @app.get("/api/pro/training/{sid}", dependencies=[Depends(core.auth)])
    def training_state(sid: str):
        with _training_lock:
            return training_snapshot(get_session(sid))

    @app.get("/api/pro/training/{sid}/hint", dependencies=[Depends(core.auth)])
    def hint(sid: str):
        with _training_lock:
            session = get_session(sid)
            board = session["board"]
            if board.is_game_over(claim_draw=True):
                raise HTTPException(status_code=409, detail="Training is over")
            if (board.turn == chess.WHITE) != (session["color"] == "white"):
                raise HTTPException(status_code=409, detail="It is the engine's turn")
            with chess.engine.SimpleEngine.popen_uci(core.STOCKFISH_PATH) as engine:
                engine_strength(engine, 20)
                info = engine.analyse(board, chess.engine.Limit(time=max(.2, core.ANALYSIS_TIME_SECONDS)))
            pv = info.get("pv", [])
            if not pv:
                raise HTTPException(status_code=503, detail="No hint available")
            move = pv[0]
            concept, tip = classify_concept(board, move)
            session["hints_used"] += 1
            return {"best_uci": move.uci(), "best_san": board.san(move), "concept": concept,
                    "explanation_ar": tip, "line": core.pv_to_san(board, pv, 5),
                    "note": "تلميحات للتدريب المحلي المستقل فقط، وليست للمباريات الجارية ضد البشر."}

    @app.post("/api/pro/training/{sid}/move", dependencies=[Depends(core.auth)])
    def training_play(sid: str, request: TrainingMove):
        with _training_lock:
            session = get_session(sid)
            board = session["board"]
            if board.is_game_over(claim_draw=True):
                raise HTTPException(status_code=409, detail="Training has ended")
            if (board.turn == chess.WHITE) != (session["color"] == "white"):
                raise HTTPException(status_code=409, detail="It is the engine's turn")
            move = chess.Move.from_uci(request.uci)
            if move not in board.legal_moves:
                raise HTTPException(status_code=422, detail="Illegal move")
            feedback = calculate_feedback(board, move)
            san = board.san(move)
            color = session["color"]
            board.push(move)
            session["history"].append({"uci": move.uci(), "san": san, "color": color,
                                       "who": "you", "fen": board.fen(),
                                       "quality_code": feedback.get('quality_code'), "quality_label": feedback.get('label')})
            reply = robot_reply(session)
            return {**training_snapshot(session), "your_move_san": san,
                    "engine_move_san": reply["san"] if reply else None, "feedback": feedback}
