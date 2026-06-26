#!/usr/bin/env python3
"""League of Legends custom game helper — LCU API integration + Firebase reporting."""

import os
import re
import subprocess
from typing import Optional

import requests
import urllib3
from dotenv import load_dotenv

load_dotenv()


# ── Firebase ──────────────────────────────────────────────────────────────────

import firebase_admin
from firebase_admin import credentials, firestore

_firebase_initialized = False
_FIREBASE_COLLECTION = os.getenv("FIREBASE_COLLECTION", "games")


def _init_firebase() -> None:
    """Firebase Admin SDK 초기화 (최초 1회만 실행).

    환경 변수(FIREBASE_PROJECT_ID 등)가 설정되어 있으면 dict로 직접 초기화.
    없으면 FIREBASE_CREDENTIALS_PATH 경로의 JSON 파일로 폴백.
    """
    global _firebase_initialized
    if _firebase_initialized:
        return

    project_id = os.getenv("FIREBASE_PROJECT_ID")
    client_email = os.getenv("FIREBASE_CLIENT_EMAIL")
    private_key = os.getenv("FIREBASE_PRIVATE_KEY", "").replace("\\n", "\n")

    if not (project_id and client_email and private_key):
        raise EnvironmentError(
            ".env 파일에 FIREBASE_PROJECT_ID, FIREBASE_CLIENT_EMAIL, FIREBASE_PRIVATE_KEY가 설정되어 있어야 합니다."
        )

    cred_dict = {
        "type": "service_account",
        "project_id": project_id,
        "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID", ""),
        "private_key": private_key,
        "client_email": client_email,
        "client_id": os.getenv("FIREBASE_CLIENT_ID", ""),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_X509_CERT_URL", ""),
        "universe_domain": "googleapis.com",
    }
    cred = credentials.Certificate(cred_dict)

    firebase_admin.initialize_app(cred)
    _firebase_initialized = True


def game_exists_in_firebase(game_id: int, collection: str = "") -> bool:
    """Firestore에 해당 gameId 문서가 이미 존재하는지 확인."""
    _init_firebase()
    db = firestore.client()
    col = collection or _FIREBASE_COLLECTION
    return db.collection(col).document(str(game_id)).get().exists


def _clean_keys(obj):
    if isinstance(obj, dict):
        return {str(k): _clean_keys(v) for k, v in obj.items() if k is not None and k != ""}
    if isinstance(obj, list):
        return [_clean_keys(v) for v in obj]
    return obj


def _report_to_normalized(report: dict, game_id: int) -> tuple[dict, list[dict]]:
    """report (overview/stats/runes) → (game_doc, players) 정규화 분리."""
    overview = report.get("overview") or {}
    stats = report.get("stats") or []
    runes_by_pid = {r.get("participantId"): r for r in (report.get("runes") or [])}

    winning_team = next((s.get("teamId") for s in stats if s.get("win")), None)
    win_summoners = [s.get("summoner", "") for s in stats if s.get("win")]
    lose_summoners = [s.get("summoner", "") for s in stats if not s.get("win")]

    game_doc = {
        "gameId": game_id,
        "status": "completed",
        "gameMode": overview.get("gameMode"),
        "gameType": overview.get("gameType"),
        "mapId": overview.get("mapId"),
        "queueId": overview.get("queueId"),
        "gameCreationDate": overview.get("gameCreationDate"),
        "gameDuration": overview.get("gameDuration"),
        "winningTeam": winning_team,
        "winTeamSummoners": win_summoners,
        "loseTeamSummoners": lose_summoners,
        "summoners": win_summoners + lose_summoners,
        "teams": overview.get("teams"),
        "teamBans": overview.get("teamBans"),
    }

    players = []
    for s in stats:
        pid = s.get("participantId")
        rune = runes_by_pid.get(pid) or {}
        players.append({
            "gameId": game_id,
            "participantId": pid,
            "summoner": s.get("summoner", ""),
            "puuid": s.get("puuid", ""),
            "summonerId": s.get("summonerId"),
            "teamId": s.get("teamId"),
            "championId": s.get("championId"),
            "championName": s.get("championName", ""),
            "position": s.get("position", ""),
            "kills": s.get("kills", 0),
            "deaths": s.get("deaths", 0),
            "assists": s.get("assists", 0),
            "goldEarned": s.get("goldEarned", 0),
            "totalDamageDealtToChampions": s.get("totalDamageDealtToChampions", 0),
            "totalDamageDealt": s.get("totalDamageDealt", 0),
            "minionsKilled": s.get("minionsKilled", 0),
            "visionScore": s.get("visionScore", 0),
            "win": s.get("win", False),
            "items": s.get("items", []),
            "spell1Id": s.get("spell1Id"),
            "spell2Id": s.get("spell2Id"),
            "level": s.get("level", 0),
            "botPlayer": s.get("botPlayer", False),
            "perk0": rune.get("perk0"),
            "perk1": rune.get("perk1"),
            "perk2": rune.get("perk2"),
            "perk3": rune.get("perk3"),
            "perk4": rune.get("perk4"),
            "perk5": rune.get("perk5"),
            "perkPrimaryStyle": rune.get("perkPrimaryStyle"),
            "perkSubStyle": rune.get("perkSubStyle"),
        })

    return game_doc, players


def save_report_to_firebase(
    report: dict,
    game_id: Optional[int] = None,
    collection: str = "",
) -> None:
    """Firestore에 정규화된 구조로 저장. games/{gameId} + games/{gameId}/players/{pid}"""
    _init_firebase()
    db = firestore.client()
    col = collection or _FIREBASE_COLLECTION
    gid = game_id or (report.get("overview") or {}).get("gameId")
    if not gid:
        raise ValueError("game_id not provided and not present in report['overview']['gameId']")
    gid = int(gid)

    game_ref = db.collection(col).document(str(gid))
    if game_ref.get().exists:
        raise RuntimeError("이미 등록된 전적내용입니다!")

    game_doc, players = _report_to_normalized(report, gid)
    game_ref.set(_clean_keys(game_doc))

    players_ref = game_ref.collection("players")
    for p in players:
        pid = p.get("participantId")
        if pid is not None:
            players_ref.document(str(pid)).set(_clean_keys(p))


def generate_report_from_eog(eog_data: dict) -> dict:
    """EOG stats block → generate_match_report와 동일한 overview/stats/graphs/runes 형태 변환.

    선수 데이터는 eog_data["teams"][n]["players"] 안에 있음.
    stats 필드명은 match history와 다름: CHAMPIONS_KILLED→kills, NUM_DEATHS→deaths 등
    """
    teams_raw = eog_data.get("teams") or []

    # teams[n].players 에서 전체 선수 추출
    all_players = []
    for team in teams_raw:
        for player in team.get("players") or []:
            all_players.append(player)

    overview = {
        "gameId": eog_data.get("gameId"),
        "gameMode": eog_data.get("gameMode"),
        "gameType": eog_data.get("gameType"),
        "mapId": eog_data.get("mapId"),
        "gameCreationDate": eog_data.get("gameCreationDate"),
        "gameDuration": eog_data.get("gameLength"),
        "queueId": eog_data.get("queueId"),
        "teams": teams_raw,
        "teamBans": {
            t.get("teamId"): list(t.get("bans", []))
            for t in teams_raw
        },
    }
    tb = overview.get("teamBans", {})
    if not any(tb.values()):
        overview["banSummary"] = "No bans recorded"
    else:
        overview["banSummary"] = {tid: bans for tid, bans in tb.items() if bans}

    stats = []
    for i, p in enumerate(all_players):
        s = p.get("stats") or {}
        # riotIdGameName 우선, summonerName 폴백
        name = p.get("riotIdGameName") or p.get("summonerName") or p.get("championName", "")
        stats.append({
            "participantId": i + 1,
            "summoner": name,
            "puuid": p.get("puuid", ""),
            "summonerId": p.get("summonerId"),
            "championId": p.get("championId"),
            "championName": p.get("championName", ""),
            "teamId": p.get("teamId"),
            "position": p.get("detectedTeamPosition") or p.get("selectedPosition", ""),
            "kills": s.get("CHAMPIONS_KILLED", 0),
            "deaths": s.get("NUM_DEATHS", 0),
            "assists": s.get("ASSISTS", 0),
            "goldEarned": s.get("GOLD_EARNED", 0),
            "totalDamageDealtToChampions": s.get("TOTAL_DAMAGE_DEALT_TO_CHAMPIONS", 0),
            "totalDamageDealt": s.get("TOTAL_DAMAGE_DEALT", 0),
            "minionsKilled": s.get("MINIONS_KILLED", 0),
            "visionScore": s.get("VISION_SCORE", 0),
            "win": bool(s.get("WIN", 0)),
            "items": p.get("items") or [],
            "spell1Id": p.get("spell1Id"),
            "spell2Id": p.get("spell2Id"),
            "level": p.get("level") or s.get("LEVEL", 0),
            "botPlayer": p.get("botPlayer", False),
        })

    graphs = {
        "kills_per_player":   [{"summoner": s["summoner"], "kills":   s["kills"]}   for s in stats],
        "deaths_per_player":  [{"summoner": s["summoner"], "deaths":  s["deaths"]}  for s in stats],
        "assists_per_player": [{"summoner": s["summoner"], "assists": s["assists"]} for s in stats],
        "gold_per_player":    [{"summoner": s["summoner"], "gold":    s["goldEarned"]} for s in stats],
    }

    runes = []
    for p in all_players:
        s = p.get("stats") or {}
        name = p.get("riotIdGameName") or p.get("summonerName") or p.get("championName", "")
        runes.append({
            "summoner": name,
            "perk0": s.get("PERK0"),
            "perk1": s.get("PERK1"),
            "perk2": s.get("PERK2"),
            "perk3": s.get("PERK3"),
            "perk4": s.get("PERK4"),
            "perk5": s.get("PERK5"),
            "perkPrimaryStyle": s.get("PERK_PRIMARY_STYLE"),
            "perkSubStyle": s.get("PERK_SUB_STYLE"),
        })

    return {"overview": overview, "stats": stats, "graphs": graphs, "runes": runes}


def trigger_discord_notification(game_id: int) -> None:
    """게임 저장 후 Discord 봇 자동 포스팅 트리거 (game_triggers 컬렉션에 문서 추가)."""
    _init_firebase()
    db = firestore.client()
    db.collection("game_triggers").document(str(game_id)).set({
        "gameId": game_id,
        "processed": False,
    })


def trigger_discord_aborted_notification(game_id: int) -> None:
    """탈주 게임 Discord 봇 자동 포스팅 트리거."""
    _init_firebase()
    db = firestore.client()
    db.collection("game_triggers").document(str(game_id)).set({
        "gameId": game_id,
        "processed": False,
        "type": "aborted",
    })


def save_aborted_game_to_firebase(game_id: int, teams: Optional[dict] = None) -> bool:
    """조기 종료(탈주) 게임을 Firebase에 저장.

    games/{gameId} = {status: aborted, desertionCount: 1, ...}
    games/{gameId}/players/{teamId}_{i} = {summoner, championId, position, teamId, puuid}

    Returns:
        True: 신규 저장 / False: 이미 존재
    """
    _init_firebase()
    db = firestore.client()
    game_ref = db.collection(_FIREBASE_COLLECTION).document(str(game_id))
    if game_ref.get().exists:
        return False

    game_ref.set({
        "gameId": game_id,
        "status": "aborted",
        "desertionCount": 1,
    })

    if teams:
        players_ref = game_ref.collection("players")
        for team_id, player_list in teams.items():
            for i, p in enumerate(player_list):
                doc_id = f"{team_id}_{i}"
                players_ref.document(doc_id).set(_clean_keys({
                    "gameId": game_id,
                    "teamId": int(team_id),
                    **p,
                }))

    return True


def save_eog_to_firebase(eog_data: dict, min_duration: int = 0) -> bool:
    """EOG stats block → 정규화 구조로 Firebase에 저장.

    Returns:
        True: 신규 저장 / False: 이미 존재
    Raises:
        ValueError: gameId 없음 또는 gameDuration 부족
    """
    game_id = eog_data.get("gameId")
    if not game_id:
        raise ValueError("EOG 데이터에 gameId가 없습니다")

    duration = eog_data.get("gameLength", 0)
    if min_duration > 0 and duration < min_duration:
        raise ValueError(f"gameDuration {duration}s < {min_duration}s — 스킵")

    report = generate_report_from_eog(eog_data)

    _init_firebase()
    db = firestore.client()
    game_ref = db.collection(_FIREBASE_COLLECTION).document(str(game_id))
    if game_ref.get().exists:
        return False

    game_doc, players = _report_to_normalized(report, int(game_id))
    game_ref.set(_clean_keys(game_doc))

    players_ref = game_ref.collection("players")
    for p in players:
        pid = p.get("participantId")
        if pid is not None:
            players_ref.document(str(pid)).set(_clean_keys(p))

    return True


# ── LCU 프로세스 헬퍼 ─────────────────────────────────────────────────────────

def get_process_commandlines() -> list[str]:
    """실행 중인 LeagueClientUx.exe 프로세스의 commandline 목록 반환 (Windows)."""
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-CimInstance Win32_Process -Filter \"Name='LeagueClientUx.exe'\" | Select-Object -ExpandProperty CommandLine",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return []
    out = proc.stdout.strip()
    if not out:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def parse_token(cmdline: str) -> Optional[str]:
    """commandline에서 remoting-auth-token 추출."""
    m = re.search(r"remoting-auth-token(?:=|\s+)\"?(?P<token>[^\"\s]+)\"?", cmdline)
    return m.group("token") if m else None


def parse_port(cmdline: str) -> Optional[int]:
    """commandline에서 포트 번호 추출."""
    for pat in [
        r"--app-port(?:=|\s+)(?P<port>\d+)",
        r"--remoting-port(?:=|\s+)(?P<port>\d+)",
        r"--port(?:=|\s+)(?P<port>\d+)",
    ]:
        m = re.search(pat, cmdline)
        if m:
            return int(m.group("port"))
    m = re.search(r"\b(?P<p>\d{4,5})\b", cmdline)
    return int(m.group("p")) if m else None


def _auto_detect_token_port() -> tuple[Optional[str], Optional[int]]:
    """실행 중인 롤 클라이언트에서 token/port 자동 감지."""
    for c in get_process_commandlines():
        t = parse_token(c)
        p = parse_port(c)
        if t and p:
            return t, p
    return None, None


# ── LCU API 호출 ──────────────────────────────────────────────────────────────

def get_match_history(
    token: str, port: int, begIndex: int = 0, endIndex: int = 20, timeout: float = 5.0
) -> dict:
    """로컬 클라이언트 매치 히스토리 조회."""
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    url = (
        f"https://127.0.0.1:{port}/lol-match-history/v1/products/lol/current-summoner/matches"
        f"?begIndex={begIndex}&endIndex={endIndex}"
    )
    resp = requests.get(url, auth=("riot", token), verify=False, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def get_custom_games(token: str, port: int, limit: int = 20) -> list[dict]:
    """최근 매치에서 CUSTOM_GAME만 필터링해 반환."""
    mh = get_match_history(token, port, begIndex=0, endIndex=max(20, limit))
    matches = extract_matches(mh) or []
    return filter_custom_games(matches)[:limit]


def scan_match_history_for_game(
    token: str,
    port: int,
    game_id: int,
    max_matches: int = 2000,
    batch_size: int = 200,
    timeout: float = 5.0,
) -> Optional[dict]:
    """매치 히스토리를 페이지 단위로 스캔해 특정 game_id를 찾음."""
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    batch_size = max(1, batch_size)
    for beg in range(0, max_matches, batch_size):
        try:
            mh = get_match_history(token, port, begIndex=beg, endIndex=beg + batch_size, timeout=timeout)
        except Exception:
            continue
        for m in (extract_matches(mh) or []):
            try:
                if m.get("gameId") == game_id:
                    return m
            except Exception:
                continue
    return None


def get_game_details(token: str, port: int, game_id: int, timeout: float = 5.0) -> dict:
    """여러 LCU 엔드포인트를 시도해 게임 상세 정보를 가져옴. 실패 시 매치 히스토리 스캔."""
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    endpoints = [
        f"https://127.0.0.1:{port}/lol-match-history/v1/games/{game_id}",
        f"https://127.0.0.1:{port}/lol-match-history/v1/matches/{game_id}",
        f"https://127.0.0.1:{port}/lol-match-history/v1/games/{game_id}?includeTimeline=true",
        f"https://127.0.0.1:{port}/lol-match-history/v1/games/{game_id}/timeline",
        f"https://127.0.0.1:{port}/lol-spectator/v1/games/{game_id}",
    ]
    last_exc = None
    for url in endpoints:
        try:
            resp = requests.get(url, auth=("riot", token), verify=False, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and ("participants" in data or "participantIdentities" in data):
                    return data
                if isinstance(data, dict):
                    return data
        except Exception as e:
            last_exc = e
    scanned = scan_match_history_for_game(token, port, game_id, timeout=timeout)
    if scanned:
        return scanned
    if last_exc:
        raise RuntimeError(f"Failed to fetch game details for {game_id}: {last_exc}")
    raise RuntimeError(f"Could not find game details for gameId {game_id}")


# ── 매치 데이터 처리 ──────────────────────────────────────────────────────────

def extract_matches(mh: object) -> Optional[list]:
    """다양한 응답 형태에서 매치 목록을 추출."""
    if isinstance(mh, list):
        return mh
    if not isinstance(mh, dict):
        return None
    if "matches" in mh and isinstance(mh["matches"], list):
        return mh["matches"]
    for k in ("games", "data", "matchList", "entries"):
        if k in mh and isinstance(mh[k], list):
            return mh[k]

    def find_list_of_dicts(o: object) -> Optional[list]:
        if isinstance(o, list) and o and isinstance(o[0], dict):
            return o
        if isinstance(o, dict):
            for v in o.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    return v
        return None

    for v in mh.values():
        found = find_list_of_dicts(v)
        if found is not None:
            return found
    return None


def filter_custom_games(match_list: list[dict]) -> list[dict]:
    """CUSTOM_GAME만 필터링."""
    return [m for m in match_list if m.get("gameType") == "CUSTOM_GAME"]


def generate_match_report(match: dict) -> dict:
    """단일 매치 dict에서 overview / stats / graphs / runes 리포트 생성."""
    id_to_name: dict = {}
    for pi in match.get("participantIdentities", []):
        pid = pi.get("participantId")
        player = pi.get("player") or {}
        name = player.get("gameName") or player.get("summonerName") or player.get("matchHistoryUri") or ""
        id_to_name[pid] = name

    overview = {
        "gameId": match.get("gameId"),
        "gameMode": match.get("gameMode"),
        "gameType": match.get("gameType"),
        "mapId": match.get("mapId"),
        "gameCreationDate": match.get("gameCreationDate"),
        "gameDuration": match.get("gameDuration"),
        "queueId": match.get("queueId"),
        "teams": match.get("teams"),
        "teamBans": {
            t.get("teamId"): list(t.get("bans", []))
            for t in (match.get("teams") or [])
        },
    }
    tb = overview.get("teamBans", {})
    if not any(tb.values()):
        overview["banSummary"] = "No bans recorded"
    else:
        overview["banSummary"] = {tid: bans for tid, bans in tb.items() if bans}

    participants_by_id = {p.get("participantId"): p for p in match.get("participants", [])}
    stats = []
    for pi in match.get("participantIdentities", []):
        pid = pi.get("participantId")
        p = participants_by_id.get(pid, {})
        st = p.get("stats", {})
        stats.append(
            {
                "participantId": pid,
                "summoner": id_to_name.get(pid, ""),
                "championId": p.get("championId"),
                "teamId": p.get("teamId"),
                "kills": st.get("kills", 0),
                "deaths": st.get("deaths", 0),
                "assists": st.get("assists", 0),
                "goldEarned": st.get("goldEarned", 0),
                "totalDamageDealtToChampions": st.get("totalDamageDealtToChampions", 0),
                "win": st.get("win", False),
            }
        )

    graphs = {
        "kills_per_player": [{"summoner": s["summoner"], "kills": s["kills"]} for s in stats],
        "deaths_per_player": [{"summoner": s["summoner"], "deaths": s["deaths"]} for s in stats],
        "assists_per_player": [{"summoner": s["summoner"], "assists": s["assists"]} for s in stats],
        "gold_per_player": [{"summoner": s["summoner"], "gold": s["goldEarned"]} for s in stats],
    }

    runes = []
    for p in match.get("participants", []):
        pid = p.get("participantId")
        st = p.get("stats", {})
        rune_info = {
            k: st.get(k)
            for k in ("perk0", "perk1", "perk2", "perk3", "perk4", "perk5", "perkPrimaryStyle", "perkSubStyle")
        }
        rune_info.update({"participantId": pid, "summoner": id_to_name.get(pid, "")})
        runes.append(rune_info)

    return {"overview": overview, "stats": stats, "graphs": graphs, "runes": runes}


def report_game_by_id(
    game_id: int,
    token: Optional[str] = None,
    port: Optional[int] = None,
    auto_detect: bool = True,
    save_to_db: bool = True,
    min_duration: int = 0,
) -> None:
    """게임 상세 정보를 가져와 리포트를 생성하고 Firebase에 저장."""
    if auto_detect and (not token or not port):
        token, port = _auto_detect_token_port()

    if not token or not port:
        raise ValueError(
            "token/port가 없습니다. 직접 제공하거나 롤 클라이언트가 실행 중인지 확인하세요."
        )

    detailed = get_game_details(token, port, game_id)

    full_match: Optional[dict] = None
    if isinstance(detailed, dict) and ("participants" in detailed or "participantIdentities" in detailed):
        full_match = detailed
    else:
        extracted = extract_matches(detailed)
        if isinstance(extracted, list) and extracted:
            full_match = extracted[0]

    if full_match is None:
        raise RuntimeError("제공된 gameId의 매치 상세 정보를 찾을 수 없습니다.")

    report = generate_match_report(full_match)

    if min_duration > 0:
        duration = (report.get("overview") or {}).get("gameDuration") or 0
        if duration < min_duration:
            raise ValueError(f"gameDuration {duration}s < {min_duration}s")

    if save_to_db:
        save_report_to_firebase(report, game_id)
