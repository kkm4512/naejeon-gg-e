#!/usr/bin/env python3
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from league_client_api import _auto_detect_token_port
from lobby_manager import LobbyManager


def main():
    print("롤 클라이언트 감지 중...")
    token, port = _auto_detect_token_port()
    if not token or not port:
        print("롤 클라이언트를 찾을 수 없습니다. 롤을 실행한 뒤 다시 시도하세요.")
        sys.exit(1)

    print(f"연결됨 (port={port})")

    lobby = LobbyManager(token, port)

    print("감시 시작 (종료: Ctrl+C)")
    try:
        lobby.start(poll_interval=2.0)
    except Exception as e:
        print(f"[오류] 비정상 종료: {e}")


if __name__ == "__main__":
    main()
