# 장부 초안 기능 (실험용, 기본 꺼짐)

이 폴더는 「내 회사 장부 초안」 계산 프로그램과 규칙 초안을 담고 있어요. **아직 공식 규칙(MANIFEST)에는 넣지 않았고, 실험 단계**예요.

## 포함 파일

| 파일 | 설명 |
|---|---|
| `ledger_calc.py` | 장부·손익·현금 흐름 계산 (표준 라이브러리만) |
| `tax-ledger.md` | 봇용 규칙 초안 (7장에 `ledger_calc.py` sha256 고정) |
| `leak_check.py` | 가림 결과 노출 검사 (**ledger_calc 와 별도 구현**, 시험용) |
| `scripts/fuzz_leak_report.py` | 독립 검사기 fuzz 재현 스크립트 |
| `tests/test_ledger.py` | 시험 36개 |
| `reference/ledger_calc_r8.py` | 8차 보관본 (회귀 비교용, 실행에 쓰지 않음) |

## 시험 실행

```bash
cd ledger-experimental
python3 -m unittest tests.test_ledger
```

## 10차(2026-11-04) 요약

- **가림 구조:** 이웃 숫자 run 을 먼저 합쳐 9자리 이상이면 기본 가림 → 그다음 **단독 run** 만 예외(날짜·쉼표 금액·단위·전화·사업자번호 등).
- **실험 기능:** 기본 꺼짐, MANIFEST 미포함. 합계·거절 로직은 그대로.
- **노출 검사:** `leak_check.py` 는 제품 코드를 import 하지 않아요. `scripts/fuzz_leak_report.py` 로 strict/realistic fuzz 수치를 재현할 수 있어요(아래는 개발 VM 기준 예시).

```bash
python3 scripts/fuzz_leak_report.py
```

## 켜는 방법 [확인 필요]

공식 스킬로 쓰려면 MANIFEST·README 정식 반영과 대표님 확인이 필요해요. 지금은 저장소에만 두었어요.
