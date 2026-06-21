#!/usr/bin/env python3
"""Firebase의 특정 게임 문서를 올바른 match report 형식으로 재변환."""

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from league_client_api import (
    _init_firebase,
    _FIREBASE_COLLECTION,
    _clean_keys,
    generate_report_from_eog,
)
from firebase_admin import firestore

GAME_ID = "8267914888"


def main():
    _init_firebase()
    db = firestore.client()
    doc_ref = db.collection(_FIREBASE_COLLECTION).document(GAME_ID)

    doc = doc_ref.get()
    if not doc.exists:
        print(f"문서 {GAME_ID} 없음")
        return

    raw = doc.to_dict()

    # Firebase에 저장된 overview.teams 에서 EOG 원본 구조 복원
    overview = raw.get("overview") or {}
    eog_like = {
        "gameId": overview.get("gameId"),
        "gameMode": overview.get("gameMode"),
        "gameType": overview.get("gameType"),
        "mapId": overview.get("mapId"),
        "gameCreationDate": overview.get("gameCreationDate"),
        "gameLength": overview.get("gameDuration"),
        "queueId": overview.get("queueId"),
        "teams": overview.get("teams") or [],
    }

    report = generate_report_from_eog(eog_like)
    print(f"stats 참가자 수: {len(report['stats'])}")
    for s in report["stats"]:
        print(f"  {s['summoner']} ({s['championName']}) {s['kills']}/{s['deaths']}/{s['assists']} 금:{s['goldEarned']}")

    doc_ref.set(_clean_keys(report))
    print(f"\nFirebase 문서 {GAME_ID} 업데이트 완료")


if __name__ == "__main__":
    main()
