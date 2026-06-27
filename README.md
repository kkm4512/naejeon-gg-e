# najeon-gg-e

롤(League of Legends) 커스텀 게임 전적을 **자동으로** 감지하고 Firebase에 저장하는 도구입니다.

**이전 방식**: 플레이어가 게임 후 Game ID를 수동으로 입력  
**새로운 방식**: 빈깡통 계정이 참관하고 게임 종료를 자동으로 감지 → Firebase에 자동 저장

---

## 핵심 동작 원리

1. **빈깡통 계정 미리 로그인**
   - 롤 클라이언트에 `nayoun440` 계정으로 로그인해둠

2. **플레이어들이 내전 진행**
   - 빈깡통 계정으로 팀 초대
   - 빈깡통 계정이 방 입장 → 관전자 입장

3. **프로그램이 자동 감시**
   - LCU API로 게임 상태 폴링 (2초 간격)
   - 게임 종료 감지

4. **자동 저장**
   - Game ID 자동 추출
   - Firebase Firestore에 자동 저장

---

## 프로젝트 구조

```
lol-custom-exe/
├── gui.py                 # Tkinter GUI (감시 시작/중지, 실시간 로그)
├── game_watcher.py        # LCU API 폴링 + 게임 상태 감지
├── auto_reporter.py       # 게임 종료 시 자동 저장
├── league_client_api.py   # LCU API 연동 + Firebase 저장 (핵심 로직)
├── .env                   # 환경 변수 (⚠️ 커밋 금지)
├── serviceAccountKey.json # Firebase 서비스 계정 키 (⚠️ 커밋 금지)
└── docs/
    └── PLAN.md            # 아키텍처 기획서
```

---

## 설치

```powershell
# 가상환경 생성 (선택)
python -m venv .venv
.venv\Scripts\activate

# 패키지 설치
pip install -r requirements.txt
```

---

## 환경 변수 설정

`.env` 파일 (이미 설정됨, 확인만 하면 됨):

```env
# Firebase 설정 (기존)
FIREBASE_PROJECT_ID=...
FIREBASE_PRIVATE_KEY_ID=...
FIREBASE_PRIVATE_KEY=...
...

# 빈깡통 계정 (신규)
BOT_ACCOUNT_NAME=nayoun440
BOT_ACCOUNT_PASSWORD=!@Skdud340
```

⚠️ **주의**: `.env`는 `.gitignore`에 등록되어 커밋되지 않습니다.

---

## 사용법

### GUI (권장)

```powershell
python gui.py
```

1. **감시 시작** 버튼 클릭
   - 롤 클라이언트 감지
   - LCU API 연결
   - 게임 폴링 시작

2. **게임 진행**
   - 빈깡통 계정이 참관 중
   - 자동으로 상태 감시

3. **게임 종료**
   - 게임 ID 자동 감지
   - Firebase 자동 저장
   - 로그에 "완료" 표시

4. **감시 중지** 버튼 클릭 (선택)

### CLI (수동 저장, 기존 방식)

```powershell
# 현재 소환사 정보 조회
python league_client_api.py

# 특정 gameId로 리포트 생성 및 DB 저장 (수동)
python league_client_api.py --game-id 7966001746

# 최근 커스텀 게임 목록 출력
python league_client_api.py --matches
```

---

## DB 저장 구조 (Firestore)

**컬렉션**: `reports`  
**문서 ID**: `{gameId}` (문자열)

```json
{
  "overview": {
    "gameId": 7966001746,
    "gameMode": "CLASSIC",
    "gameType": "CUSTOM_GAME",
    "mapId": 11,
    "gameDuration": 1823,
    ...
  },
  "stats": [
    {
      "summoner": "소환사이름",
      "championId": 235,
      "teamId": 100,
      "kills": 5,
      "deaths": 2,
      "assists": 8,
      "goldEarned": 14200,
      "win": true,
      ...
    },
    ...
  ],
  "graphs": { ... },
  "runes": [ ... ]
}
```

---

## 테스트

```powershell
pytest tests/
```

---

## 주의사항

- `.env`와 `serviceAccountKey.json`은 **절대 커밋하지 마세요**
- LCU API 연결은 **Windows + 롤 클라이언트 실행 중** 환경에서만 동작
- 동일한 Game ID는 중복 저장이 방지됩니다 (Firestore 검증)
- 게임 상태 폴링 간격: **2초** (CPU 효율과 감지 성능의 균형)

---

## 아키텍처 변경 기록

기획서는 `docs/PLAN.md`에서 확인하세요.

**주요 변경사항**:
- GameWatcher: LCU API 폴링으로 게임 상태 감지
- AutoReporter: 게임 종료 시 자동 저장
- GUI: 감시 시작/중지 형태로 변경, 실시간 로그 표시

---

## 트러블슈팅

### "롤 클라이언트를 찾을 수 없습니다"
- 롤 클라이언트를 실행하고 로그인하세요
- 롤 클라이언트를 재시작하세요

### 게임이 Firebase에 저장되지 않음
- `.env` 파일의 Firebase 설정 확인
- `serviceAccountKey.json` 존재 여부 확인
- 로그에서 오류 메시지 확인

### 게임 종료 후 저장되지 않음
- GUI의 "감시 중" 상태 확인
- 네트워크 연결 확인
- 로그 텍스트박스에서 오류 메시지 확인

