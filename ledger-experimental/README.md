# 장부 초안 기능 (실험용, 기본 꺼짐)

이 폴더는 「내 회사 장부 초안」 계산 프로그램과 규칙 초안을 담고 있어요. **아직 공식 규칙(MANIFEST)에는 넣지 않았고, 실험 단계**예요.

## 포함 파일

| 파일 | 설명 |
|---|---|
| `ledger_calc.py` | 장부·손익·현금 흐름 계산 (표준 라이브러리만) |
| `tax-ledger.md` | 봇용 규칙 초안 (7장에 `ledger_calc.py` sha256 고정) |
| `leak_check.py` | 가림 결과 노출 검사 (`ledger_calc` 를 import 하지 않음. 연결 run·last4 판정은 **같은 방식을 따로 짠 보조 검사기**이며, 완전히 독립된 알고리즘이라고 보기는 어려움) |
| `scripts/fuzz_leak_report.py` | `mask_text` + `leak_check` fuzz 재현 |
| `tests/test_ledger.py` | 시험 37개 |
| `reference/ledger_calc_baseline.py` | 이전 세대 보관본 (회귀 비교용, 실행에 쓰지 않음) |

## 시험 실행

```bash
cd ledger-experimental
python3 -m unittest tests.test_ledger
```

## 가림·검사 요약 (2026-11-04 기준)

- **가림(`mask_text`):** NFKC 뒤, 비문자 구분·글자→숫자 붙임으로 이어진 **연결 run**에서 숫자가 9자리 이상이면 run 전체에 **끝 4자리만** 남기는 방식을 씁니다. 단독 8자리 이하 run(날짜·전화·쉼표 금액 등)은 예외로 둘 수 있습니다. 카드 뒤에 금액·시각 등이 이어지면 **그 run의** 끝 4자리만 보일 수 있어, 카드 본문만 항상 끝 4자리가 남는 것은 아닙니다.
- **leak_check:** `ledger_calc` 를 import 하지 않지만, run 나누기·9자리·last4 판정은 **ledger_calc 와 같은 설계를 별도 모듈에 다시 구현**한 것입니다. 시험·fuzz용 **보조 검사기**로 쓰며, 제품과 무관한 완전 독립 판정기는 아닙니다.
- **실험 기능:** 기본 꺼짐, MANIFEST 미포함.
- **fuzz:** `python3 scripts/fuzz_leak_report.py` — strict / realistic / letter-glued / preceding-number+card, 각 5 seed × 3000.

## 켜는 방법 [확인 필요]

공식 스킬로 쓰려면 MANIFEST·README 정식 반영과 대표님 확인이 필요해요. 지금은 저장소에만 두었어요.
