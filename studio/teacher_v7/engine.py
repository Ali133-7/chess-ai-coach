"""Build a *verified* snapshot of the user's completed game for a language model.
Only server-produced legal lines and arrows may become board actions.
"""
from __future__ import annotations
import json
import chess
from ..coach_teacher import move_facts, position_observations, evaluation_ar


def verified_scenarios(row, max_scenarios=3, max_plies=9):
    board = chess.Board(row['fen_before'])
    try:
        raw = json.loads(row['lines_json'] or '[]')
    except (ValueError, TypeError):
        raw = []
    results, first_moves = [], set()
    for index, item in enumerate(raw[:8]):
        if not isinstance(item, dict):
            continue
        pv = item.get('pv_uci') or []
        if not isinstance(pv, list) or not pv or not isinstance(pv[0], str) or pv[0] in first_moves:
            continue
        current = board.copy()
        moves, fens, sans, steps = [], [current.fen()], [], []
        for entry in pv[:max_plies]:
            try:
                move = chess.Move.from_uci(entry)
            except (ValueError, TypeError):
                break
            if move not in current.legal_moves:
                break
            facts = move_facts(current, move)
            moves.append(move.uci())
            sans.append(facts['san'])
            steps.append(facts)
            current.push(move)
            fens.append(current.fen())
        if not moves:
            continue
        first_moves.add(moves[0])
        score = item.get('eval')
        if not isinstance(score, int):
            score = None
        results.append({
            'id': 'line-' + str(index), 'label': 'خيار المحرك ' + str(len(results)+1),
            'moves': moves, 'san': sans, 'fens': fens, 'steps': steps,
            'evaluation_cp_white': score, 'evaluation_ar': evaluation_ar(score),
            'depth': item.get('depth') if isinstance(item.get('depth'), int) else None,
            'arrow': {'from':moves[0][:2], 'to':moves[0][2:4], 'color':'green'},
        })
        if len(results) >= max_scenarios:
            break
    return results


def verified_context(row):
    board = chess.Board(row['fen_before'])
    actual = chess.Move.from_uci(row['uci'])
    if actual not in board.legal_moves:
        raise ValueError('Saved game move is not legal from this position')
    scenarios = verified_scenarios(row)
    facts = move_facts(board, actual)
    observations = position_observations(board)
    # The context sent to the LLM contains no email, username, game URL or other user's games.
    return {
        'fen': board.fen(), 'turn': 'white' if board.turn else 'black',
        'actual_move': facts, 'grade': row['grade'],
        'loss_cp': row['loss_cp'], 'best_san': row['best_san'],
        'position_observations': observations,
        'scenarios': [
            {'id':s['id'], 'moves_san':s['san'], 'evaluation_ar':s['evaluation_ar'],
             'steps': [{'summary':step['summary'], 'benefits':step['benefits'],
                        'risks':step['risks']} for step in s['steps'][:5]]}
            for s in scenarios
        ],
    }, scenarios


def approved_board_actions(scenarios, scenario_ids):
    # The model never supplies a free-form from/to that reaches the board.
    allowed = {s['id']:s for s in scenarios}
    return [{'type':'arrow', **allowed[sid]['arrow'], 'scenario_id':sid}
            for sid in scenario_ids if sid in allowed][:3]
