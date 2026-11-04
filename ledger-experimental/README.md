# 장부 초안 기능 (실험용, 기본 꺼짐)

이 폴더는 「내 회사 장부 초안」 계산 프로그램과 규칙 초안을 담고 있어요. **아직 공식 규칙(MANIFEST)에는 넣지 않았고, 실험 단계**예요.

## 포함 파일

| 파일 | 설명 |
|---|---|
| `ledger_calc.py` | 장부·손익·현금 흐름 계산 (표준 라이브러리만) |
| `tax-ledger.md` | 봇용 규칙 초안 (7장에 `ledger_calc.py` sha256 고정) |
| `leak_check.py` | 가림 결과 노출 검사 (마스킹 로직과 별도) |
| `tests/test_ledger.py` | 시험 33개 |
| `reference/ledger_calc_r8.py` | 8차 보관본 (회귀 비교용, 실행에 쓰지 않음) |

## 시험 실행

```bash
cd ledger-experimental
python3 -m unittest tests.test_ledger
```

## 9차(2026-11-04) 요약

- 상수님이 승인하신 **단순 가림 규칙**을 기준으로 F1·F2·F3 등 노출을 줄였어요.
- `test_30`·`leak_check.py`로 무작위 300건×2 seed 에서 **노출 0건**을 확인해요.
- 8차 대비: 같은 무작위 조건에서 8차는 독립 검사기 기준 다수 노출, 9차는 0건 (`test_33`).

## 켜는 방법 [확인 필요]

공식 스킬로 쓰려면 MANIFEST·README 정식 반영과 대표님 확인이 필요해요. 지금은 저장소에만 두었어요.
