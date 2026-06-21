#!/usr/bin/env python3
"""Firebase에 저장된 게임 문서를 로컬 JSON 파일로 내보내기."""

import sys
import json
import os

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from league_client_api import _init_firebase, _FIREBASE_COLLECTION
from firebase_admin import firestore

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "games")


def main():
    _init_firebase()
    db = firestore.client()

    docs = list(db.collection(_FIREBASE_COLLECTION).stream())
    print(f"Firebase 문서 {len(docs)}개 발견")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for doc in docs:
        data = doc.to_dict()
        path = os.path.join(OUTPUT_DIR, f"{doc.id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  저장: games/{doc.id}.json")

    print(f"\n완료 — games/ 폴더에 {len(docs)}개 파일 저장됨")


if __name__ == "__main__":
    main()
