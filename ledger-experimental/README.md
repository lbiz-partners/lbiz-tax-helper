# 장부 초안 기능 (실험용, 기본 꺼짐)

이 폴더는 「내 회사 장부 초안」 계산 프로그램과 규칙 초안을 담고 있어요. **아직 공식 규칙(MANIFEST)에는 넣지 않았고, 실험 단계**예요.

## 포함 파일

| 파일 | 설명 |
|---|---|
| `ledger_calc.py` | 장부·손익·현금 흐름 계산 (표준 라이브러리만) |
| `tax-ledger.md` | 봇용 규칙 초안 (7장에 `ledger_calc.py` sha256 고정) |
| `leak_check.py` | 가림 결과 노출 검사 (**ledger_calc 미사용**, 원문 숫자 위치·끝 4자리 규칙) |
| `scripts/fuzz_leak_report.py` | `mask_text` + 독립 `leak_check` fuzz 재현 |
| `tests/test_ledger.py` | 시험 37개 |
| `reference/ledger_calc_r8.py` | 8차 보관본 (회귀 비교용, 실행에 쓰지 않음) |

## 시험 실행

```bash
cd ledger-experimental
python3 -m unittest tests.test_ledger
```

## 11차(2026-11-04) 요약

- **가림:** 글자 붙임(3자리 이상 덩어리)도 이웃 숫자와 연결·9+·4-4-4-4 카드 우선 가림. 주민번호 꼴은 줄 제외 우선.
- **leak_check:** `ledger_calc` 를 import 하지 않음. 가림 함수를 복사하지 않고, 원문 민감 숫자 위치 대비 출력 노출만 검사.
- **실험 기능:** 기본 꺼짐, MANIFEST 미포함.
- **fuzz:** `python3 scripts/fuzz_leak_report.py` — strict / realistic / letter-glued / preceding-number+card, 각 5 seed × 3000.

## 켜는 방법 [확인 필요]

공식 스킬로 쓰려면 MANIFEST·README 정식 반영과 대표님 확인이 필요해요. 지금은 저장소에만 두었어요.
