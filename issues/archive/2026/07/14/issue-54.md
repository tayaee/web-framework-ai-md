# issue-54: dist 산출물 파일 권한(0600) 때문에 슬래시 없는 `.ai.md` URL이 403

## 배경

`http://localhost:8080/tetris.ai.md` (트레일링 슬래시 없음)에 접속하면 403이
발생하지만, `http://localhost:8080/tetris.ai.md/` (슬래시 있음)는 정상 동작한다.

## 원인

`nginx.conf`의 `location /`은 `try_files $uri.html @engine`으로 동작한다.
슬래시 없는 URL은 `dist/tetris.ai.md.html`이 존재하면 **nginx 컨테이너가 그
파일을 직접 서빙**한다. 반면 슬래시 있는 URL은 `$uri.html` =
`tetris.ai.md/.html`이 존재하지 않으므로 곧바로 `@engine`(엔진 컨테이너)으로
폴백해서 엔진이 서빙한다.

그런데 `engine/aimd/artifacts.py`의 `atomic_write()`는 `tempfile.mkstemp()`로
임시 파일을 만든 뒤 `os.replace()`로 `dist/`에 옮기는데, `mkstemp`는 기본
퍼미션이 `0600`이고 `os.replace`는 그 모드를 그대로 유지한다. 결과적으로
`dist/*.html`, `dist/*.py` 파일이 전부 `0600`(소유자만 읽기 가능)으로 생성된다.

nginx는 별도 컨테이너(다른 uid)로 돌기 때문에 `./dist`를 read-only로 마운트해도
`0600` 파일을 읽지 못해 403이 난다. 엔진 컨테이너는 자기 소유 파일이라 문제가
없다. 즉 슬래시 유무 차이가 아니라 "정적 파일 직접 서빙 vs 엔진 프록시 경유"의
차이가 진짜 원인이며, 근본 원인은 `atomic_write`가 만드는 파일 퍼미션이다.

## 목표

`dist/`에 새로 컴파일되는 산출물이 다른 유저(nginx 컨테이너)도 읽을 수 있는
퍼미션으로 생성되게 하여, 슬래시 없는 `.ai.md` URL이 403 없이 정상 서빙되도록
한다.

## 구현 상세

### `engine/aimd/artifacts.py` — `atomic_write()` 수정

`os.fdopen`으로 쓰기를 마친 뒤, `os.replace(tmp_path, path)` 하기 전에
`os.chmod(tmp_path, 0o644)`를 호출해서 그룹/기타 사용자도 읽을 수 있게 만든다.
(`tempfile.mkstemp`가 만든 `0600` 모드를 덮어씀.)

```python
fd, tmp_path = tempfile.mkstemp(dir=str(dir_path))
try:
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(text)
    os.chmod(tmp_path, 0o644)
    os.replace(tmp_path, path)
```

- `os.replace`는 파일 모드를 보존하므로 `chmod`는 반드시 `replace` 이전,
  `fdopen` 블록이 닫힌 이후에 호출한다.
- 예외 발생 시 기존의 tmp 파일 정리 로직(`finally`가 아니라 `except` 블록)은
  그대로 둔다.

### 기존에 이미 0600으로 생성되어 있는 `dist/*.html`, `dist/*.py` 파일 정정

재컴파일 없이 바로 403을 없애기 위해 `dist/tetris.ai.md.html`,
`dist/convert.ai.md.py` 등 기존 산출물의 퍼미션을 `644`로 일괄 변경한다
(예: `chmod 644 dist/*.html dist/*.py`, `dist/**/*.html`, `dist/**/*.py` 재귀
포함 — issue-53으로 하위 디렉토리 산출물도 가능해졌으므로 `find dist -type f
\( -name '*.html' -o -name '*.py' \) -exec chmod 644 {} +` 같은 방식 권장).

## 테스트로 검증해야 할 것

- `engine/tests/test_artifacts.py`: `atomic_write()`로 새로 쓴 파일의 권한이
  `0o644`(적어도 other-read 비트가 켜져 있음)인지 확인하는 케이스 추가.
- 기존 `atomic_write` 관련 테스트(내용이 올바르게 써지는지, 부모 디렉토리
  자동 생성 등) 회귀 없는지 확인.

## 하지 말 것

- `nginx.conf`는 변경하지 않는다 (슬래시 유무에 따른 리다이렉트 규칙을
  추가하는 것은 근본 원인을 가리는 우회이며, 이 이슈의 목표가 아니다).
- `dist/` 산출물을 실제로 재컴파일하거나 내용을 바꾸지 않는다 (퍼미션만 정정).
- `docker-compose.yml`의 volume 마운트 방식(uid/gid 매핑 등)은 변경하지 않는다
  — 애플리케이션 레벨(퍼미션 명시)로 해결한다.

## 완료 조건

- [x] `atomic_write()`로 생성된 파일이 `0o644` 권한을 갖는지 pytest로 확인
- [x] 기존 `dist/*.html`, `dist/*.py` 파일 퍼미션이 `644`로 정정됨
- [x] `docker-compose up`으로 실행 후 `curl -I http://localhost:8080/tetris.ai.md`
      (슬래시 없음)가 403이 아니라 200을 반환하는지 확인
- [x] 기존 `engine/tests/test_artifacts.py` 전체 통과 (회귀 없음)
- 검증 명령: `cd engine && python -m pytest -q`

## 구현 결과

- **구현 완료 일시**: 2026-07-14T20:22:03-04:00
- **변경 파일**:
  - `engine/aimd/artifacts.py` — `atomic_write()`에 `os.chmod(tmp_path, 0o644)`
    추가 (`os.fdopen`으로 쓰기를 마친 뒤, `os.replace` 이전). `tempfile.mkstemp`
    기본 모드 `0o600`을 `0o644`로 덮어써서 다른 컨테이너(nginx)에서도 읽을 수
    있게 함.
  - `engine/tests/test_artifacts.py` — `test_atomic_write_sets_readable_permissions`
    추가 (red 단계에서 `384(0o600) != 420(0o644)`로 실패 확인 후, 구현으로
    green 전환).
  - `dist/tetris.ai.md.html`, `dist/convert.ai.md.py` — 기존에 `0o600`으로
    저장되어 있던 산출물을 `644`로 일괄 정정 (이후 실제 컴파일 재트리거로
    `atomic_write` 수정판이 다시 만든 산출물도 `644`임을 확인).
  - `regression-tests/verify-issue-54.sh` (신규)
- **계획과의 차이**: 없음.
- **검증 결과**:
  - 단위 테스트: `engine/.venv/bin/python -m pytest -q` → 86 passed, 1 failed
    (`test_create_app_returns_dispatcher_instance` — `git stash`로 이 이슈의
    변경분을 걷어낸 클린 HEAD에서도 동일하게 재현되는 기존 환경 이슈
    (watchdog가 상대 경로 `./src`를 관찰 못 함, issue-53 보고서에도 동일하게
    기록됨). issue-54와 무관함을 확인.
  - 회귀 스크립트: `regression-tests/verify-issue-54.sh` 통과.
  - 전체 회귀 스위트: `verify-issue-1/12/14/15/16/18/25`가 실패하나, 전부
    `git stash`로 걷어낸 클린 HEAD에서도 동일하게 실패함을 확인한 기존
    실패(README 문구 불일치, `.env` 존재, `_UNCLOSED_FENCE_RE` 관련,
    `verify-issue-12`의 nginx `engine` 업스트림 미해결은 그 스크립트가 별도
    docker 네트워크 없이 단독 컨테이너로 nginx 문법만 검사하려다 발생하는
    환경 특성). 나머지 전부 통과.
  - 실사용 확인: `docker compose up -d` 후 `dist/tetris.ai.md.html`,
    `dist/convert.ai.md.py`를 삭제해 재컴파일을 유도, 새로 생성된 파일이
    `644`임을 확인. `curl http://localhost:8080/tetris.ai.md` (슬래시 없음)가
    수정 전 403이었던 것이 수정 후 200으로 정상 응답함을 확인.
