#!/usr/bin/env python3
"""Lobby manager — auto-accept invitations, switch to spectator, save EOG reports."""

import time
from typing import Optional, Callable
import urllib3
import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class LobbyManager:
    """Poll for invitations, accept them, switch to spectator, and save EOG game data."""

    def __init__(self, token: str, port: int):
        self.token = token
        self.port = port
        self.base_url = f"https://127.0.0.1:{port}"
        self._is_running = False
        self._eog_saved_ids: set[int] = set()  # 이번 세션에 저장한 game_id

    def _req(self, method: str, path: str, **kwargs) -> requests.Response:
        import base64
        auth = base64.b64encode(f"riot:{self.token}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}
        return requests.request(
            method,
            f"{self.base_url}{path}",
            headers=headers,
            verify=False,
            timeout=5,
            **kwargs,
        )

    # ── 초대 ──────────────────────────────────────────────────────────────────

    def get_pending_invitations(self) -> list[dict]:
        try:
            resp = self._req("GET", "/lol-lobby/v2/received-invitations")
            if resp.status_code != 200:
                return []
            return [inv for inv in resp.json() if inv.get("state") == "Pending"]
        except Exception:
            return []

    def accept_invitation(self, invitation_id: str) -> bool:
        try:
            resp = self._req("POST", f"/lol-lobby/v2/received-invitations/{invitation_id}/accept")
            return resp.status_code in (200, 204)
        except Exception:
            return False

    # ── 관전자 전환 ───────────────────────────────────────────────────────────

    def switch_to_spectator(self, log_fn=None) -> bool:
        _log = log_fn or print
        lobby = self.get_current_lobby()
        if not lobby:
            return False

        local = lobby.get("localMember") or {}
        if local.get("isSpectator", False):
            return True

        puuid = local.get("puuid", "")
        spectator_values = ["Spectator", "spectator", "SPECTATOR", "0", "observer", "Observer"]
        endpoints: list[tuple] = [
            *[("POST", f"/lol-lobby/v2/lobby/team/{t}", None) for t in spectator_values],
            ("PUT", "/lol-lobby/v2/lobby/memberData", {"isSpectator": True}),
        ]
        if puuid:
            endpoints.append(("PUT", "/lol-lobby/v2/lobby/memberData", {"puuid": puuid, "isSpectator": True}))

        for method, path, body in endpoints:
            try:
                resp = self._req(method, path, json=body)
                if resp.status_code in (200, 204):
                    _log(f"[Lobby] 관전자 전환 성공: {method} {path}")
                    return True
            except Exception:
                pass
        return False

    # ── 로비 / 게임플로우 ─────────────────────────────────────────────────────

    def get_current_lobby(self) -> Optional[dict]:
        try:
            resp = self._req("GET", "/lol-lobby/v2/lobby")
            return resp.json() if resp.status_code == 200 else None
        except Exception:
            return None

    def get_gameflow_phase(self) -> Optional[str]:
        try:
            resp = self._req("GET", "/lol-gameflow/v1/gameflow-phase")
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    def get_active_game_id(self) -> Optional[int]:
        """InProgress 중 게임 ID 조회."""
        try:
            resp = self._req("GET", "/lol-gameflow/v1/session")
            if resp.status_code == 200:
                data = resp.json()
                game_data = data.get("gameData") or {}
                gid = game_data.get("gameId")
                if gid:
                    return int(gid)
        except Exception:
            pass
        return None

    def get_session_teams(self) -> Optional[dict]:
        """InProgress 중 팀 구성 정보 조회 (소환사명, 챔피언, 포지션)."""
        try:
            resp = self._req("GET", "/lol-gameflow/v1/session")
            if resp.status_code == 200:
                game_data = resp.json().get("gameData") or {}

                def _lookup_name(puuid: str) -> str:
                    if not puuid:
                        return ""
                    try:
                        r = self._req("GET", f"/lol-summoner/v2/summoners/puuid/{puuid}")
                        if r.status_code == 200:
                            d = r.json()
                            return d.get("gameName") or d.get("displayName") or d.get("summonerName") or ""
                    except Exception:
                        pass
                    return ""

                def _extract(p: dict) -> dict:
                    puuid = p.get("puuid", "")
                    summoner = (p.get("gameName") or p.get("riotIdGameName")
                                or p.get("summonerName") or p.get("displayName") or "")
                    if not summoner:
                        summoner = _lookup_name(puuid)
                    return {
                        "summoner": summoner,
                        "puuid": puuid,
                        "championId": p.get("championId"),
                        "position": p.get("selectedPosition") or p.get("detectedTeamPosition") or "",
                    }

                return {
                    "100": [_extract(p) for p in (game_data.get("teamOne") or [])],
                    "200": [_extract(p) for p in (game_data.get("teamTwo") or [])],
                }
        except Exception:
            pass
        return None

    # ── EOG 처리 ──────────────────────────────────────────────────────────────

    def _get_eog_data(self) -> Optional[dict]:
        """EOG stats block 전체 반환."""
        try:
            resp = self._req("GET", "/lol-end-of-game/v1/eog-stats-block")
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    def _press_continue(self, log_fn) -> bool:
        """EOG 계속 버튼 누르기."""
        try:
            resp = self._req("POST", "/lol-lobby/v2/play-again")
            log_fn(f"[Lobby] EOG 계속 → {resp.status_code}")
            return resp.status_code in (200, 204)
        except Exception:
            return False

    def _save_aborted_game(self, game_id: int, log_fn, teams: Optional[dict] = None) -> None:
        """조기 종료(탈주) 게임 — gameId + 팀 구성 + desertionCount Firebase에 저장."""
        from league_client_api import game_exists_in_firebase, save_aborted_game_to_firebase

        self._eog_saved_ids.add(game_id)

        if game_exists_in_firebase(game_id):
            log_fn(f"[Lobby] Game {game_id} 이미 DB에 존재 — 스킵")
            return

        try:
            save_aborted_game_to_firebase(game_id, teams=teams)
            log_fn(f"[저장] Game {game_id} 탈주 기록 저장됨 (desertionCount=1)")
            self._trigger_discord_aborted(game_id, log_fn)
        except Exception as e:
            log_fn(f"[Lobby] 탈주 기록 저장 오류: {e}")

    def _trigger_discord_aborted(self, game_id: int, log_fn) -> None:
        try:
            from league_client_api import trigger_discord_aborted_notification
            trigger_discord_aborted_notification(game_id)
            log_fn(f"[Discord] 탈주 트리거 전송 (game_id={game_id})")
        except Exception as e:
            log_fn(f"[Discord] 탈주 트리거 실패: {e}")

    def _try_save_game(self, game_id: int, eog_data: Optional[dict], log_fn) -> None:
        """게임 데이터 Firebase 저장 공통 로직."""
        from league_client_api import (
            game_exists_in_firebase, report_game_by_id, save_eog_to_firebase,
        )
        _MIN_GAME_DURATION = 0

        self._eog_saved_ids.add(game_id)

        if game_exists_in_firebase(game_id):
            log_fn(f"[Lobby] Game {game_id} 이미 DB에 존재 — 스킵")
            return

        # 1순위: LCU 직접 조회
        try:
            report_game_by_id(
                game_id=game_id,
                token=self.token,
                port=self.port,
                auto_detect=False,
                save_to_db=True,
                min_duration=_MIN_GAME_DURATION,
            )
            log_fn(f"[저장] Game {game_id} 저장됨")
            self._trigger_discord(game_id, log_fn)
            return
        except ValueError as e:
            log_fn(f"[Lobby] 스킵: {e}")
            return
        except Exception as e:
            log_fn(f"[Lobby] LCU 직접 조회 실패 ({e}){' — EOG로 저장' if eog_data else ''}")

        # 2순위: EOG stats block
        if eog_data:
            try:
                save_eog_to_firebase(eog_data, min_duration=_MIN_GAME_DURATION)
                log_fn(f"[저장] Game {game_id} EOG 데이터로 저장됨")
                self._trigger_discord(game_id, log_fn)
            except ValueError as e:
                log_fn(f"[Lobby] 스킵: {e}")
            except Exception as e:
                log_fn(f"[Lobby] EOG 저장 오류: {e}")

    def _trigger_discord(self, game_id: int, log_fn) -> None:
        try:
            from league_client_api import trigger_discord_notification
            trigger_discord_notification(game_id)
            log_fn(f"[Discord] 트리거 전송 (game_id={game_id})")
        except Exception as e:
            log_fn(f"[Discord] 트리거 실패: {e}")

    def handle_eog(self, log_fn) -> bool:
        """EndOfGame 페이즈 처리."""
        phase = self.get_gameflow_phase()
        if phase != "EndOfGame":
            return False

        log_fn("[Lobby] EOG 감지")

        eog_data = self._get_eog_data()
        game_id = int(eog_data["gameId"]) if eog_data and eog_data.get("gameId") else None

        if not game_id:
            log_fn("[Lobby] EOG gameId 없음")
            self._press_continue(log_fn)
            return True

        if game_id not in self._eog_saved_ids:
            self._try_save_game(game_id, eog_data=eog_data, log_fn=log_fn)
        else:
            log_fn(f"[Lobby] game_id={game_id} 이미 처리됨")

        self._press_continue(log_fn)
        return True

    # ── 메인 루프 ─────────────────────────────────────────────────────────────

    def start(
        self,
        poll_interval: float = 2.0,
        log_fn: Optional[Callable[[str], None]] = None,
        on_game_completed: Optional[Callable[[int], None]] = None,  # 하위 호환용, 미사용
    ):
        """초대 감시 + EOG 처리 루프 (블로킹). Ctrl+C로 종료."""
        self._is_running = True
        _log = log_fn or print
        _log("[Lobby] 감시 시작 (초대 + EOG)")

        accepted_ids: set[str] = set()
        prev_phase: Optional[str] = None
        in_progress_game_id: Optional[int] = None
        in_progress_teams: Optional[dict] = None

        while self._is_running:
            try:
                phase = self.get_gameflow_phase()

                # InProgress 진입 시 game_id + 팀 구성 미리 캡처
                if phase == "InProgress" and not in_progress_game_id:
                    in_progress_game_id = self.get_active_game_id()
                    in_progress_teams = self.get_session_teams()
                    if in_progress_game_id:
                        _log(f"[Lobby] 게임 진행 중 감지 (game_id={in_progress_game_id})")

                # InProgress → EndOfGame 아닌 상태 전환: 전원 퇴장 케이스
                if (prev_phase == "InProgress"
                        and phase not in ("InProgress", "EndOfGame")
                        and phase is not None
                        and in_progress_game_id
                        and in_progress_game_id not in self._eog_saved_ids):
                    _log(f"[Lobby] 게임 조기 종료 감지 (game_id={in_progress_game_id}) — 탈주 기록 저장")
                    self._save_aborted_game(in_progress_game_id, log_fn=_log, teams=in_progress_teams)

                if phase != "InProgress":
                    in_progress_game_id = None
                    in_progress_teams = None

                prev_phase = phase

                # EOG 처리
                self.handle_eog(log_fn=_log)

                # 초대 처리
                for inv in self.get_pending_invitations():
                    inv_id = inv.get("invitationId")
                    if not inv_id or inv_id in accepted_ids:
                        continue

                    _log(f"[Lobby] 초대 감지 → 수락 중...")
                    if self.accept_invitation(inv_id):
                        accepted_ids.add(inv_id)
                        _log("[Lobby] 수락 완료 — 관전자 전환 시도 중...")
                        time.sleep(2)
                        if self.switch_to_spectator(log_fn=_log):
                            _log("[Lobby] 관전자 전환 완료")
                        else:
                            _log("[Lobby] 관전자 전환 실패 — 수동으로 전환해주세요")
                    else:
                        _log(f"[Lobby] 수락 실패: {inv_id}")

                time.sleep(poll_interval)

            except KeyboardInterrupt:
                break
            except Exception as e:
                _log(f"[Lobby] 오류: {e}")
                time.sleep(poll_interval)

    def stop(self):
        self._is_running = False
