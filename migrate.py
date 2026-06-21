#!/usr/bin/env python3
"""기존 'reports' 컬렉션 → 정규화된 'games' 컬렉션으로 마이그레이션."""

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from league_client_api import _init_firebase, _clean_keys, _report_to_normalized
from firebase_admin import firestore

OLD_COLLECTION = "reports"
NEW_COLLECTION = "games"


def migrate():
    _init_firebase()
    db = firestore.client()

    old_docs = list(db.collection(OLD_COLLECTION).stream())
    print(f"[마이그레이션] {OLD_COLLECTION} 문서 수: {len(old_docs)}")

    ok, skip, fail = 0, 0, 0

    for doc in old_docs:
        game_id_str = doc.id
        data = doc.to_dict()

        new_ref = db.collection(NEW_COLLECTION).document(game_id_str)

        try:
            game_id = int(game_id_str)
        except ValueError:
            print(f"  FAIL  {game_id_str} (gameId 파싱 불가)")
            fail += 1
            continue

        # aborted 게임 처리
        if data.get("status") == "aborted":
            game_doc = {
                "gameId": game_id,
                "status": "aborted",
                "desertionCount": data.get("desertionCount", 1),
            }
            new_ref.set(game_doc)

            teams = data.get("teams")
            if teams and isinstance(teams, dict):
                players_ref = new_ref.collection("players")
                for team_id, player_list in teams.items():
                    for i, p in enumerate(player_list):
                        doc_id = f"{team_id}_{i}"
                        players_ref.document(doc_id).set(_clean_keys({
                            "gameId": game_id,
                            "teamId": int(team_id),
                            **p,
                        }))

            print(f"  OK    {game_id_str} (aborted)")
            ok += 1
            continue

        # 일반 완료 게임: overview/stats/runes 구조 필요
        if not data.get("overview") or not data.get("stats"):
            print(f"  FAIL  {game_id_str} (overview/stats 없음)")
            fail += 1
            continue

        try:
            game_doc, players = _report_to_normalized(data, game_id)
            new_ref.set(_clean_keys(game_doc))

            players_ref = new_ref.collection("players")
            for p in players:
                pid = p.get("participantId")
                if pid is not None:
                    players_ref.document(str(pid)).set(_clean_keys(p))

            print(f"  OK    {game_id_str} (players: {len(players)})")
            ok += 1
        except Exception as e:
            print(f"  FAIL  {game_id_str} ({e})")
            fail += 1

    print(f"\n완료 — OK: {ok}, SKIP: {skip}, FAIL: {fail}")


if __name__ == "__main__":
    migrate()
