# -*- coding: utf-8 -*-
"""세금정리도우미 장부 초안 시험 (설계 7장 시험 1~9).

표준 라이브러리만 쓰고, 임시 폴더에서만 파일을 만들며, 네트워크를 쓰지 않아요.
"""

import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(os.path.join(ROOT, "_tmp"), exist_ok=True)
os.environ.setdefault("TMPDIR", os.path.join(ROOT, "_tmp"))
sys.path.insert(0, ROOT)
from leak_check import independent_digit_leak  # noqa: E402
from ledger_calc import (  # noqa: E402
    mask_text,
    is_separator_whitespace,
    row_contains_rrn,
    build_nfkc_mapping,
)

PROG = os.path.join(ROOT, "ledger_calc.py")
RULES = os.path.join(ROOT, "tax-ledger.md")
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
BASIC = os.path.join(FIXTURES, "basic.csv")
BLURRY = os.path.join(FIXTURES, "blurry.csv")

NOTICE = "참고용 초안_신고용 아님"
REFUSAL = "이 도우미는 사용자님 본인 사업장 자료만 정리해요. 다른 회사 장부는 세무사에게 맡겨 주세요."
DISCLAIMER = "참고용 안내이며 세무대리나 세무상담이 아닙니다. 최종 판단은 직접 하시고, 중요한 건 세무사와 상의해 주세요."
NUMBER_SLOT = "[확인 필요: 법제처 원문 확인 뒤에만]"
TOPIC_IDS = ("G1", "G2", "G3", "G4", "G6", "G7", "G8", "G15")
OUTPUT_FILES = (
    NOTICE + "_장부.csv",
    NOTICE + "_월별손익.csv",
    NOTICE + "_월별현금흐름.csv",
    NOTICE + "_요약.md",
    "result.json",
)
HEADER = "날짜,거래처,내용,들어온돈,나간돈,증빙종류,계정,계정상태,메모,출처"


def run(*args, cwd=None):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    proc = subprocess.run([sys.executable, PROG] + list(args), capture_output=True, text=True,
                          encoding="utf-8", env=env, cwd=cwd)
    lines = [l for l in proc.stdout.splitlines() if l.strip()]
    tail = json.loads(lines[-1]) if lines else {}
    return proc.returncode, proc.stdout, tail


def calc(input_path, out_dir, *extra, own="yes"):
    h = sha256_file(PROG)
    return run("calc", "--input", input_path, "--out", out_dir, "--own-business", own,
               "--expect-self-sha256", h, *extra)


def read(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def assert_masked_secret(test, blob, secret, keep_tail=4):
    blob_n = unicodedata.normalize("NFKC", blob)
    secret_n = unicodedata.normalize("NFKC", secret)
    digits = "".join(c for c in secret_n if c.isdigit())
    if len(digits) > keep_tail:
        test.assertNotIn(digits[:-keep_tail], blob_n, secret)
    if len(digits) >= keep_tail:
        test.assertIn(digits[-keep_tail:], blob_n, secret)


def secret_digit_chunks(secret):
    norm = unicodedata.normalize("NFKC", secret)
    chunks = []
    cur = []
    for c in norm:
        if c.isdigit():
            cur.append(c)
        else:
            if cur:
                chunks.append("".join(cur))
                cur = []
    if cur:
        chunks.append("".join(cur))
    return chunks


def assert_no_leaked_secret_digits(test, blob, secret, keep_tail=4):
    """구분 글자가 낀 입력: 끝 keep_tail자리 덩어리만 남고 앞 숫자 덩어리는 출력에 없어야 함."""
    norm = unicodedata.normalize("NFKC", secret)
    if not any(not c.isdigit() and not is_separator_whitespace(c) for c in norm):
        return
    blob_n = unicodedata.normalize("NFKC", blob)
    test.assertNotIn(norm, blob_n, secret)
    chunks = secret_digit_chunks(secret)
    for ch in chunks[:-1]:
        if len(ch) >= 4:
            test.assertNotIn(ch, blob_n, secret)
    digits = "".join(chunks)
    if len(digits) > keep_tail:
        test.assertNotIn(digits[:-keep_tail], blob_n, secret)


def fuzz_output_masks_input_digits(original, output):
    """원문 각 숫자 자리의 출력이 mask_text 와 같아야 함(동일 인덱스)."""
    expected = mask_text(original)
    if len(output) != len(expected):
        return False
    norm, _ = build_nfkc_mapping(original)
    for i, c in enumerate(norm):
        if not c.isdigit():
            continue
        if unicodedata.normalize("NFKC", output[i]) != unicodedata.normalize("NFKC", expected[i]):
            return False
    return True


def fuzz_no_five_plus_digit_leak(original, output):
    norm_o = unicodedata.normalize("NFKC", original)
    norm_out = unicodedata.normalize("NFKC", output)
    digits = "".join(c for c in norm_o if c.isdigit())
    if len(digits) <= 4:
        return True
    prefix = digits[:-4]
    out_digits = norm_out.replace("*", "")
    if prefix and prefix in out_digits:
        return False
    stripped = "".join(c for c in norm_out if c.isdigit())
    for i in range(len(digits) - 4):
        for width in range(5, len(digits) - i - 3):
            if digits[i:i + width] in stripped:
                return False
    for i, c in enumerate(norm_o):
        if not c.isdigit():
            continue
        run = i
        while run < len(norm_o) and norm_o[run].isdigit():
            run += 1
        if run - i >= 5 and norm_o[i:run] in norm_out:
            return False
    return True


def all_output_text(out_dir):
    return "\n".join(read(os.path.join(out_dir, n)) for n in OUTPUT_FILES)


def ledger_rows_blob_for_secret(out_dir, secret):
    """해당 비밀값의 끝 4자리가 들어 있는 장부 줄만 모아요(교차 오탐 방지)."""
    norm = unicodedata.normalize("NFKC", secret)
    digits = "".join(c for c in norm if c.isdigit())
    if len(digits) < 4:
        return ""
    tail = digits[-4:]
    rows = read_csv(os.path.join(out_dir, OUTPUT_FILES[0]))[2:]
    picked = []
    for row in rows:
        if len(row) < 4:
            continue
        line = ",".join(row)
        if tail in unicodedata.normalize("NFKC", line):
            picked.append(line)
    return "\n".join(picked)


class LedgerTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_1_other_business_is_refused(self):
        for text in ("고객사 장부 정리해 줘", "의뢰받은 자료예요", "지인 회사 것도 해 주세요", "여러 사업자 자료를 묶어 주세요"):
            code, _, tail = run("guard", "--text", text)
            self.assertEqual(code, 2, text)
            self.assertEqual(tail["category"], "other_business")
            self.assertEqual(tail["answer"], REFUSAL)

        out = os.path.join(self.tmp, "out_no")
        code, stdout, tail = calc(BASIC, out, own="no")
        self.assertEqual(code, 2)
        self.assertIn(REFUSAL, stdout)
        self.assertEqual(tail["status"], "refused")
        self.assertFalse(os.path.exists(out))

        out = os.path.join(self.tmp, "out_client")
        code, stdout, tail = calc(BASIC, out, "--request-text", "고객사 장부 정리해 줘")
        self.assertEqual(code, 2)
        self.assertIn(REFUSAL, stdout)
        self.assertEqual(tail["status"], "refused")
        self.assertFalse(os.path.exists(out))

        s4_requests = (
            "친구 가게 장부를 대신 정리해줘",
            "거래처 장부 좀 만들어줘",
            "고객 장부 정리해줘",
            "남의 장부 대신 만들어줘",
            "제 동생 가게 장부요",
            "클라이언트 회사 장부",
            "대리로 장부 작성해줘",
            "위임받아 정리",
            "의뢰받은 회사 자료",
        )
        for text in s4_requests:
            out_s4 = os.path.join(self.tmp, "s4_" + str(hash(text)))
            code, stdout, tail = calc(BASIC, out_s4, "--request-text", text)
            self.assertEqual(code, 2, text)
            self.assertIn(REFUSAL, stdout)
            self.assertEqual(tail["status"], "refused")
            self.assertFalse(os.path.exists(out_s4))

        out_ok = os.path.join(self.tmp, "own_ok")
        code, _, tail = calc(BASIC, out_ok, "--request-text", "우리 가게 9월 장부 정리해줘", "--as-of", "2026-11-03")
        self.assertEqual(code, 0)
        self.assertEqual(tail["status"], "ok")

    def test_2_storage_deletion_memory_and_privacy(self):
        rules = read(RULES)
        for phrase in ("원본 사진을 남길지 지울지", "기본 추천: 지우기",
                       "무엇을(파일 이름·개수) 지우는지 먼저 보여", "「예」를 받은 뒤에 지워요",
                       "봇이 먼저 지우지 않아요", "금액·거래처·장부 내용은 기억에 적지 않아요",
                       "원본 영수증과 장부는 따로 보관해 주세요"):
            self.assertIn(phrase, rules)

        drafts = os.path.join(self.tmp, "장부초안", "2026-10")
        code, _, _ = calc(BASIC, drafts, "--as-of", "2026-11-03")
        self.assertEqual(code, 0)
        base = os.path.join(self.tmp, "장부초안")
        before = sorted((r, tuple(sorted(f))) for r, _, f in os.walk(base))
        code, stdout, tail = run("list-drafts", "--dir", base)
        after = sorted((r, tuple(sorted(f))) for r, _, f in os.walk(base))
        self.assertEqual(code, 0)
        self.assertEqual(before, after)
        self.assertEqual(tail["count"], 5)
        self.assertEqual(tail["files"], sorted("2026-10/" + n for n in OUTPUT_FILES))
        self.assertEqual(set(tail), {"count", "files", "status", "exit_code", "notice"})
        self.assertNotIn("가나상사", stdout)
        self.assertNotIn("1200000", stdout)

        src = read(PROG)
        for banned in ("os.remove", "os.unlink", ".unlink(", "rmtree", "rmdir", "removedirs", "shutil"):
            self.assertNotIn(banned, src)

        # 2-1: 카드·계좌번호는 끝 4자리만, 주민번호 줄은 옮기지 않음
        card = "-".join(["1234", "5678", "9012", "3456"])
        account_no = "110-123-456789"
        rrn = "900101" + "-" + "1" + "234567"
        pii = os.path.join(self.tmp, "pii.csv")
        with open(pii, "w", encoding="utf-8", newline="") as f:
            f.write(HEADER + "\n")
            f.write("2026-10-02,가나상사,카드 결제 " + card + ",,10000,카드,소모품비,제안,계좌 " + account_no + ",사용자 제공\n")
            f.write("2026-10-03,홍길동,인건비,,50000,없음,급여,제안,주민번호 " + rrn + ",사용자 제공\n")
        out = os.path.join(self.tmp, "out_pii")
        code, stdout, tail = calc(pii, out, "--as-of", "2026-11-03")
        self.assertEqual(code, 10)
        texts = all_output_text(out) + stdout
        self.assertNotIn(card, texts)
        self.assertNotIn(account_no, texts)
        self.assertNotIn(rrn, texts)
        self.assertNotIn("900101", texts)
        self.assertNotIn("홍길동", texts)
        ledger = read(os.path.join(out, OUTPUT_FILES[0]))
        self.assertIn("****-****-****-3456", ledger)
        self.assertIn("***-***-**6789", ledger)
        result = json.loads(read(os.path.join(out, "result.json")))
        self.assertEqual(result["rrn_excluded_lines"], [3])
        self.assertEqual(result["rows_in_ledger"], 1)
        summary = read(os.path.join(out, OUTPUT_FILES[3]))
        self.assertIn("주민번호가 보여서 옮기지 않았어요. 가려서 다시 보내 주세요", summary)
        self.assertIn("3번째 줄", summary)

        card_sp = "1234 5678 9012 3456"
        card_dot = "1234.5678.9012.3456"
        card_plain = "1234567890123456"
        acct11 = "110-123-456789"
        acct12 = "123-45-678901"
        pii2 = os.path.join(self.tmp, "pii2.csv")
        with open(pii2, "w", encoding="utf-8", newline="") as f:
            f.write(HEADER + "\n")
            f.write("2026-10-04,가나,카드 " + card_sp + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-05,가나,카드 " + card_dot + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-06,가나,카드 " + card_plain + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-07,가나,계좌 " + acct11 + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-08,가나,계좌 " + acct12 + ",,1000,카드,소모품비,제안,,사용자 제공\n")
        out2 = os.path.join(self.tmp, "out_pii2")
        code, stdout, _ = calc(pii2, out2, "--as-of", "2026-11-03")
        self.assertEqual(code, 0)
        blob = all_output_text(out2) + stdout
        for raw in (card_sp, card_dot, card_plain, acct11, acct12):
            self.assertNotIn(raw, blob, raw)
        for tail4 in ("3456", "6789", "8901"):
            self.assertIn(tail4, blob)

        rrn_join = "9001011234567"
        rrn_space = "900101 1234567"
        rrn_dot = "900101.1234567"
        rrn_foreign = "900101-5234567"
        pii3 = os.path.join(self.tmp, "pii3.csv")
        with open(pii3, "w", encoding="utf-8", newline="") as f:
            f.write(HEADER + "\n")
            f.write("2026-10-09,홍,주민 " + rrn_join + " 붙여,,1000,없음,급여,제안,,사용자 제공\n")
            f.write("2026-10-10,홍,주민 " + rrn_space + " 공백,,1000,없음,급여,제안,,사용자 제공\n")
            f.write("2026-10-11,홍,주민 " + rrn_dot + " 점,,1000,없음,급여,제안,,사용자 제공\n")
            f.write("2026-10-12,홍,주민 " + rrn_foreign + " 외,,1000,없음,급여,제안,,사용자 제공\n")
        out3 = os.path.join(self.tmp, "out_pii3")
        code, stdout, tail = calc(pii3, out3, "--as-of", "2026-11-03")
        self.assertEqual(code, 10)
        blob3 = all_output_text(out3) + stdout
        for raw in (rrn_join, rrn_space, rrn_dot, rrn_foreign, "900101", "1234567", "5234567"):
            self.assertNotIn(raw, blob3, raw)
        self.assertNotIn("홍", blob3)
        result3 = json.loads(read(os.path.join(out3, "result.json")))
        self.assertEqual(result3["rows_in_ledger"], 0)
        self.assertEqual(result3["rrn_excluded_lines"], [2, 3, 4, 5])

    def test_3_blurry_amount_needs_check_without_guessing(self):
        out = os.path.join(self.tmp, "out")
        code, _, tail = calc(BLURRY, out, "--as-of", "2026-11-03")
        self.assertEqual(code, 10)
        self.assertEqual(tail["status"], "ok_with_checks")
        result = json.loads(read(os.path.join(out, "result.json")))
        self.assertEqual(result["totals"], {"in": 300000, "out": 12000, "net": 288000})
        self.assertEqual([i["line"] for i in result["needs_check"]], [3, 4])
        self.assertTrue(all(i["excluded_from_totals"] for i in result["needs_check"]))
        self.assertEqual(result["rows_in_totals"], 2)
        rows = read_csv(os.path.join(out, OUTPUT_FILES[0]))
        by_line = {r[0]: r for r in rows[2:]}
        self.assertEqual(by_line["3"][5], "[확인 필요]")
        self.assertEqual(by_line["3"][11], "아니요")
        self.assertEqual(by_line["4"][4], "[확인 필요]")
        self.assertEqual(by_line["4"][5], "[확인 필요]")
        self.assertEqual(by_line["5"][11], "예")
        summary = read(os.path.join(out, OUTPUT_FILES[3]))
        self.assertIn("3번째 줄: [확인 필요]", summary)
        self.assertIn("추측하지 않았어요", summary)

    def test_4_totals_match_hand_calculation_and_hash_gate(self):
        rules = read(RULES)
        m = re.search(r"`ledger_calc.py` sha256: `([0-9a-f]{64})`", rules)
        self.assertIsNotNone(m)
        real_hash = sha256_file(PROG)
        self.assertEqual(m.group(1), real_hash)

        out = os.path.join(self.tmp, "out")
        code, _, tail = calc(BASIC, out, "--as-of", "2026-11-03", "--expect-self-sha256", real_hash)
        self.assertEqual(code, 0)
        self.assertEqual(tail, {"status": "ok", "exit_code": 0, "notice": NOTICE})
        result = json.loads(read(os.path.join(out, "result.json")))
        # 손 계산: 9월 들어온 1200000 / 나간 35000+48000+500000=583000, 10월 들어온 1500000 / 나간 60000+22000+500000=582000
        self.assertEqual(result["totals"], {"in": 2700000, "out": 1165000, "net": 1535000})
        self.assertEqual(result["monthly"], [
            {"month": "2026-09", "in": 1200000, "out": 583000, "net": 617000, "cumulative": 617000},
            {"month": "2026-10", "in": 1500000, "out": 582000, "net": 918000, "cumulative": 1535000},
        ])
        self.assertIn({"month": "2026-09", "account": "기업업무추진비", "account_status": "제안",
                       "in": 0, "out": 48000}, result["account_subtotals"])
        self.assertIn({"month": "전체", "account": "소모품비", "account_status": "확정",
                       "in": 0, "out": 35000}, result["account_subtotals"])
        self.assertEqual([i["line"] for i in result["no_evidence_ask_tax_advisor"]], [8])
        pnl = read_csv(os.path.join(out, OUTPUT_FILES[1]))
        self.assertEqual(pnl[1], ["월", "들어온돈", "나간돈", "순손익"])
        self.assertEqual(pnl[2], ["2026-09", "1200000", "583000", "617000"])
        self.assertEqual(pnl[4], ["합계", "2700000", "1165000", "1535000"])
        cash = read_csv(os.path.join(out, OUTPUT_FILES[2]))
        self.assertEqual(cash[1], ["월", "들어온돈", "나간돈", "순현금흐름", "누적"])
        self.assertEqual(cash[2], ["2026-09", "1200000", "583000", "617000", "617000"])
        self.assertEqual(cash[3], ["2026-10", "1500000", "582000", "918000", "1535000"])
        self.assertEqual(set(result), {
            "notice", "as_of", "status", "exit_code", "basis", "disclaimer", "program_sha256", "totals",
            "monthly", "account_subtotals", "rows_total", "rows_in_ledger", "rows_in_totals",
            "no_evidence_ask_tax_advisor", "needs_check", "rrn_excluded_lines", "rrn_message", "files"})

        out_bad = os.path.join(self.tmp, "out_bad")
        code, stdout, tail = calc(BASIC, out_bad, "--expect-self-sha256", "0" * 64)
        self.assertEqual(code, 3)
        self.assertEqual(tail["status"], "hash_mismatch")
        self.assertIn("[확인 필요] 계산 프로그램 해시가 달라 합계를 내지 않았어요", stdout)
        self.assertNotIn("2700000", stdout)
        self.assertFalse(os.path.exists(out_bad))

        out_no_hash = os.path.join(self.tmp, "out_no_hash")
        code, stdout, tail = run("calc", "--input", BASIC, "--out", out_no_hash, "--own-business", "yes")
        self.assertEqual(code, 2)
        self.assertEqual(tail["status"], "input_error")
        self.assertFalse(os.path.exists(out_no_hash))

    def test_5_filing_question_goes_to_tax_advisor(self):
        for text in ("이걸로 신고해도 돼요?", "이 초안으로 신고해도 되나요?"):
            code, _, tail = run("guard", "--text", text)
            self.assertEqual(code, 0)
            self.assertEqual(tail["category"], "filing")
            self.assertIn("신고는 세무사와 상의해 주세요", tail["answer"])
        self.assertIn("신고는 세무사와 상의해 주세요", read(RULES))

    def test_6_general_tax_info_topics(self):
        allowed = re.compile(r"https?://\S+|제\d+(?:·\d+)*(?:조(?:의\d+)?|항|호)|2026-11-03|G\d+")
        for topic_id in TOPIC_IDS:
            code, stdout, tail = run("topic", "--id", topic_id)
            self.assertEqual(code, 0, topic_id)
            self.assertEqual(tail["status"], "ok")
            lines = stdout.splitlines()
            self.assertEqual(lines[0], NOTICE, topic_id)
            first = lines[1]
            for part in ("일반 정보", "근거 조문", "적용 기간·시행일 [확인 필요]",
                         "https://www.law.go.kr/lsLinkProc.do?mode=10&lsNm=", "확인일 2026-11-03"):
                self.assertIn(part, first, topic_id)
            self.assertIn(NUMBER_SLOT, stdout)
            self.assertIn("사용자님 경우에 맞는지는 세무사와 확인해 주세요.", stdout)
            self.assertIn("남은 [확인 필요]", stdout)
            body = allowed.sub("", stdout.rsplit("\n", 2)[0])
            self.assertIsNone(re.search(r"\d", body), topic_id + " 에 숫자가 박혀 있어요")
        code, stdout, _ = run("topic", "--id", "G2")
        self.assertIn("소득세법 제56조의2", stdout)
        self.assertIn("joNo=005602000", stdout)
        for topic_id in ("G99", "G12"):
            code, stdout, tail = run("topic", "--id", topic_id)
            self.assertIn("확인한 일반 정보가 아직 없어요", stdout)
            self.assertEqual(tail["status"], "no_info")
        for topic_id in ("G5", "G9", "G10", "G11"):
            code, stdout, tail = run("topic", "--id", topic_id)
            self.assertIn("부가세챙김이가 더 자세히 도와드려요", stdout)
            self.assertEqual(tail["status"], "vat_referral")

    def test_7_personal_question_gets_no_calculation(self):
        for text in ("제 경우 얼마 아끼나요?", "이렇게 하면 공제되나요?"):
            code, stdout, tail = run("guard", "--text", text)
            self.assertEqual(code, 0)
            self.assertEqual(tail["category"], "personal")
            self.assertIn("일반 정보 한 줄과 세무사 질문 목록만 드릴게요", tail["answer"])
            self.assertTrue(tail["general_info"])
            self.assertGreaterEqual(len(tail["questions"]), 3)
            self.assertEqual(set(tail), {"category", "answer", "related_topic", "general_info", "questions",
                                         "advisor_note", "status", "exit_code", "notice"})
            self.assertIsNone(re.search(r"\d[\d,]*\s*원", stdout))
        code, _, tail = run("guard", "--text", "영수증 정리 방법 알려 주세요")
        self.assertEqual(tail["category"], "pass")

        s18_personal = (
            "이거 경비 처리돼요?",
            "이 비용 손금 되나요",
            "저 간편장부 대상자인가요?",
            "제 매출이면 복식부기 해야 하나요",
            "환급받을 수 있나요?",
            "내야 할 종소세 계산해줘",
            "기장세액공제 얼마 받아요",
            "세금 줄일 방법 알려줘",
            "절세 방법 알려줘",
        )
        for text in s18_personal:
            code, stdout, tail = run("guard", "--text", text)
            self.assertEqual(code, 0, text)
            self.assertEqual(tail["category"], "personal", text)
            self.assertIn(NOTICE, stdout)

    def test_8_lint_and_no_hardcoded_numbers(self):
        outputs = []
        for fixture, name in ((BASIC, "a"), (BLURRY, "b")):
            out = os.path.join(self.tmp, name)
            _, stdout, _ = calc(fixture, out, "--as-of", "2026-11-03")
            outputs += [stdout, all_output_text(out)]
        for topic_id in TOPIC_IDS + ("G5", "G99"):
            outputs.append(run("topic", "--id", topic_id)[1])
        for text in ("고객사 장부 정리해 줘", "이걸로 신고해도 돼요?", "제 경우 얼마 아끼나요?"):
            outputs.append(run("guard", "--text", text)[1])
        outputs.append(run("list-drafts", "--dir", self.tmp)[1])
        joined = os.path.join(self.tmp, "all_outputs.txt")
        with open(joined, "w", encoding="utf-8") as f:
            f.write("\n".join(outputs))
        code, _, tail = run("lint", "--file", joined)
        self.assertEqual((code, tail["hits"]), (0, []))
        code, _, tail = run("lint", "--file", RULES)
        self.assertEqual((code, tail["hits"]), (0, []))

        for bad in ("기장 대행 해 드려요", "장부 대행", "대가 없이 도와드려요", "제휴 세무사 연결", "세무사 매칭",
                    "기장 도와드려요", "제휴 노무사 연결", "노무사 매칭", "세무사 연결해 드려요", "세무사 소개해 드려요",
                    "장부 대신 써 드려요", "대신 작성해 드려요"):
            code, _, tail = run("lint", "--text", bad)
            self.assertEqual(code, 2, bad)
            self.assertEqual(tail["status"], "blocked")
        code, _, _ = run("lint", "--text", "기장세액공제 안내")
        self.assertEqual(code, 0)

        rules = read(RULES)
        for pattern in (r"\d\s*%", r"퍼센트", r"\d[\d,]*\s*(?:만|억|천)", r"만\s*원", r"\d[\d,]*\s*원"):
            self.assertIsNone(re.search(pattern, rules), pattern)

        src = read(PROG)
        self.assertIsNone(re.search(r"^\s*(?:import|from)\s+(?:socket|urllib|http|requests|random|time|secrets|uuid)\b",
                                    src, re.M))
        for banned in (".now(", "today(", "time.time"):
            self.assertNotIn(banned, src)

    def test_9_headers_disclaimer_notice_and_reproducibility(self):
        out_a = os.path.join(self.tmp, "a")
        out_b = os.path.join(self.tmp, "b")
        for out in (out_a, out_b):
            code, _, _ = calc(BASIC, out, "--as-of", "2026-11-03")
            self.assertEqual(code, 0)
        out_c = os.path.join(self.tmp, "c")
        calc(BLURRY, out_c)
        for out in (out_a, out_b, out_c):
            self.assertEqual(sorted(os.listdir(out)), sorted(OUTPUT_FILES))
            for name in OUTPUT_FILES:
                self.assertIn(NOTICE, read(os.path.join(out, name)), name)
                if name != "result.json":
                    self.assertTrue(name.startswith(NOTICE))
            for name in OUTPUT_FILES[:3]:
                self.assertEqual(read_csv(os.path.join(out, name))[0], [NOTICE])
            lines = read(os.path.join(out, OUTPUT_FILES[3])).rstrip("\n").split("\n")
            self.assertEqual(lines[0], "기준일 2026-11-03" if out != out_c else "기준일 [확인 필요]")
            self.assertEqual(lines[1], NOTICE)
            self.assertEqual(lines[-1], DISCLAIMER)
            self.assertIn("현금 기준 단순 합계이며 결산 조정·세액 계산은 하지 않았어요", "\n".join(lines))
        for name in OUTPUT_FILES:
            self.assertEqual(sha256_file(os.path.join(out_a, name)), sha256_file(os.path.join(out_b, name)), name)

        before = {n: sha256_file(os.path.join(out_a, n)) for n in OUTPUT_FILES}
        code, _, tail = calc(BLURRY, out_a, "--as-of", "2026-11-03")
        self.assertEqual(code, 2)
        self.assertEqual(before, {n: sha256_file(os.path.join(out_a, n)) for n in OUTPUT_FILES})

        target = os.path.join(self.tmp, "real")
        os.mkdir(target)
        link = os.path.join(self.tmp, "link")
        os.symlink(target, link)
        code, _, _ = calc(BASIC, link)
        self.assertEqual(code, 2)
        self.assertEqual(os.listdir(target), [])

    def test_10_other_business_phrasing_s4(self):
        for text in (
            "친구 가게 장부를 대신 정리해줘",
            "대리로 장부 작성해줘",
            "위임받아 정리",
        ):
            code, _, tail = run("guard", "--text", text)
            self.assertEqual(code, 2, text)
            self.assertEqual(tail["category"], "other_business", text)

    def test_11_card_account_masking_s10_s12(self):
        self.test_2_storage_deletion_memory_and_privacy()

    def test_12_rrn_s15_s16(self):
        rrn_space = "900101 1234567"
        pii = os.path.join(self.tmp, "rrn.csv")
        with open(pii, "w", encoding="utf-8", newline="") as f:
            f.write(HEADER + "\n")
            f.write("2026-10-03,홍,주민 " + rrn_space + ",,1000,없음,급여,제안,,사용자 제공\n")
        out = os.path.join(self.tmp, "rrn_out")
        calc(pii, out, "--as-of", "2026-11-03")
        self.assertNotIn(rrn_space, all_output_text(out))

    def test_13_guard_personal_s18(self):
        code, stdout, tail = run("guard", "--text", "환급받을 수 있나요?")
        self.assertEqual(tail["category"], "personal")
        self.assertIn(NOTICE, stdout)

    def test_14_lint_extended(self):
        code, stdout, tail = run("lint", "--text", "세무사 소개해 드려요")
        self.assertEqual(code, 2)
        self.assertIn(NOTICE, stdout)

    def test_15_csv_formula_neutralized(self):
        formula = os.path.join(self.tmp, "formula.csv")
        with open(formula, "w", encoding="utf-8", newline="") as f:
            f.write(HEADER + "\n")
            f.write('2026-10-01,=HYPERLINK("http://x"),+1+1,,1000,카드,소모품비,제안,@cmd,사용자 제공\n')
        out = os.path.join(self.tmp, "formula_out")
        calc(formula, out, "--as-of", "2026-11-03")
        ledger = read(os.path.join(out, OUTPUT_FILES[0]))
        self.assertIn("'=HYPERLINK", ledger)
        self.assertIn("'+1+1", ledger)
        self.assertIn("'@cmd", ledger)

    def test_16_hash_required(self):
        out = os.path.join(self.tmp, "hash_out")
        code, _, tail = run("calc", "--input", BASIC, "--out", out, "--own-business", "yes", "--as-of", "2026-11-03")
        self.assertEqual(code, 2)
        self.assertEqual(tail["status"], "input_error")

    def test_17_notice_in_human_readable_lines(self):
        code, stdout, _ = run("topic", "--id", "G1")
        self.assertEqual(code, 0)
        self.assertIn(NOTICE, stdout.splitlines()[0])
        code, stdout, _ = run("guard", "--text", "이걸로 신고해도 돼요?")
        self.assertIn(NOTICE, stdout.splitlines()[0])
        code, stdout, _ = run("lint", "--text", "안내 문장")
        self.assertIn(NOTICE, stdout.splitlines()[0])

    def test_18_mask_gaps_n1(self):
        joined12 = "123456789012"
        joined13z = "1234560890123"
        joined14 = "12345678901234"
        card_gap = "1234  5678  9012  3456"
        card_slash = "1234/5678/9012/3456"
        rrn_slash = "900101/1234567"
        rrn_under = "900101_1234567"
        rrn_full = "\uff19\uff10\uff10\uff11\uff10\uff11\uff11\uff12\uff13\uff14\uff15\uff16\uff17"
        rrn_full_hy = "\uff19\uff10\uff10\uff11\uff10\uff11-\uff11\uff12\uff13\uff14\uff15\uff16\uff17"
        card_full = "\uff11\uff12\uff13\uff14 \uff15\uff16\uff17\uff18 \uff19\uff10\uff11\uff12 \uff13\uff14\uff15\uff16"
        amount_ok = "1,200,000"
        date_ok = "2026-10-02"
        phone_ok = "010-1234-5678"
        pii = os.path.join(self.tmp, "n1.csv")
        with open(pii, "w", encoding="utf-8", newline="") as f:
            f.write(HEADER + "\n")
            f.write("2026-10-01,가,붙12 " + joined12 + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-02,가,붙13 " + joined13z + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-03,가,붙14 " + joined14 + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-04,가,카드 " + card_gap + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-05,가,카드 " + card_slash + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-06,가,전각카드 " + card_full + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write('2026-10-07,가,쉼표,,1000,카드,소모품비,제안,"1,200,000",사용자 제공\n')
            f.write("2026-10-08,가,날짜 " + date_ok + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-09,가,전화 " + phone_ok + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-10,홍,주민 " + rrn_slash + ",,1000,없음,급여,제안,,사용자 제공\n")
            f.write("2026-10-11,홍,주민 " + rrn_under + ",,1000,없음,급여,제안,,사용자 제공\n")
            f.write("2026-10-12,홍,주민 " + rrn_full + ",,1000,없음,급여,제안,,사용자 제공\n")
            f.write("2026-10-13,홍,주민 " + rrn_full_hy + ",,1000,없음,급여,제안,,사용자 제공\n")
        out = os.path.join(self.tmp, "n1_out")
        code, stdout, tail = calc(pii, out, "--as-of", "2026-11-03")
        self.assertEqual(code, 10)
        blob = all_output_text(out) + stdout
        for raw in (joined12, joined13z, joined14, card_gap, card_slash):
            assert_masked_secret(self, blob, raw)
        assert_masked_secret(self, blob, card_full)
        self.assertIn(amount_ok, blob)
        self.assertIn(date_ok, blob)
        self.assertIn(phone_ok, blob)
        for rrn in (rrn_slash, rrn_under, rrn_full, rrn_full_hy):
            self.assertNotIn(rrn, blob, rrn)
            self.assertNotIn("900101", blob)
        self.assertNotIn("홍", blob)
        result = json.loads(read(os.path.join(out, "result.json")))
        self.assertEqual(result["rrn_excluded_lines"], [11, 12, 13, 14])

    def test_19_other_business_over_refusal_n2(self):
        s4 = (
            "친구 가게 장부를 대신 정리해줘",
            "거래처 장부 좀 만들어줘",
            "고객 장부 정리해줘",
            "남의 장부 대신 만들어줘",
            "제 동생 가게 장부요",
            "클라이언트 회사 장부",
            "대리로 장부 작성해줘",
            "위임받아 정리",
            "의뢰받은 회사 자료",
        )
        for text in s4:
            out = os.path.join(self.tmp, "s4_" + str(abs(hash(text))))
            code, stdout, tail = calc(BASIC, out, "--request-text", text)
            self.assertEqual(code, 2, text)
            self.assertIn(REFUSAL, stdout)
            self.assertFalse(os.path.exists(out), text)

        ok_requests = (
            "다른 달 장부도 같이 정리해줘",
            "고객 매출 장부 정리해줘",
            "거래처 매출 포함해서 장부 정리해줘",
            "우리 거래처에서 받은 돈 장부에 넣어줘",
            "가족과 함께 운영하는 우리 가게 장부 정리해줘",
            "다른 카드로 낸 것도 장부에 넣어줘",
            "타인 명의 카드로 결제한 것도 포함해서 내 장부 정리해줘",
            "대행 수수료 낸 내역도 내 장부에 정리해줘",
            "우리 가게 9월 장부 정리해줘",
        )
        for text in ok_requests:
            out = os.path.join(self.tmp, "ok_" + str(abs(hash(text))))
            code, _, tail = calc(BASIC, out, "--request-text", text, "--as-of", "2026-11-03")
            self.assertEqual(code, 0, text)
            self.assertEqual(tail["status"], "ok", text)

    def test_20_n3_false_positives(self):
        biz = "123-45-67890"
        date_amt = "2026-10-02 1500000 입금"
        multi_amt = "매출 1200000 500000 1000000"
        pii = os.path.join(self.tmp, "n3.csv")
        with open(pii, "w", encoding="utf-8", newline="") as f:
            f.write(HEADER + "\n")
            f.write("2026-10-01,가,사업자 " + biz + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-02,가," + date_amt + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-03,가," + multi_amt + ",1200000,,카드,매출,제안,,사용자 제공\n")
        out = os.path.join(self.tmp, "n3_out")
        code, stdout, tail = calc(pii, out, "--as-of", "2026-11-03")
        self.assertEqual(code, 0, stdout)
        blob = all_output_text(out) + stdout
        self.assertIn(biz, blob)
        self.assertIn("2026-10-02", blob)
        self.assertNotIn("1500000", blob)
        self.assertIn(mask_text(date_amt), blob)
        self.assertIn(mask_text(multi_amt), blob)
        self.assertNotIn(multi_amt, blob)
        result = json.loads(read(os.path.join(out, "result.json")))
        self.assertEqual(result["rows_in_totals"], 3)
        self.assertEqual(result["rrn_excluded_lines"], [])

    def test_21_dash_variants_n5(self):
        en = "\u2013"
        em = "\u2014"
        mn = "\u2212"
        hy = "\u2010"
        rrn_en = "900101" + en + "1234567"
        rrn_em = "900101" + em + "1234567"
        rrn_mn = "900101" + mn + "1234567"
        rrn_hy = "900101" + hy + "1234567"
        card_en = "1234" + en + "5678" + en + "9012" + en + "3456"
        card_hy = "1234" + hy + "5678" + hy + "9012" + hy + "3456"
        acct_en = "110" + en + "123" + en + "456789"
        rrn_colon = "900101:1234567"
        rrn_star = "900101*1234567"
        rrn_pipe = "900101|1234567"
        card_colon = "1234:5678:9012:3456"
        amount_ok = "1,200,000"
        date_ok = "2026-10-02"
        date_en = "2026" + en + "10" + en + "02"
        phone_ok = "010-1234-5678"
        biz = "123-45-67890"
        date_amt = "2026-10-02 1500000"
        time_ok = "10:30"
        pii = os.path.join(self.tmp, "n5.csv")
        with open(pii, "w", encoding="utf-8", newline="") as f:
            f.write(HEADER + "\n")
            f.write("2026-10-01,홍,주민 " + rrn_en + ",,1000,없음,급여,제안,,사용자 제공\n")
            f.write("2026-10-02,홍,주민 " + rrn_em + ",,1000,없음,급여,제안,,사용자 제공\n")
            f.write("2026-10-03,홍,주민 " + rrn_mn + ",,1000,없음,급여,제안,,사용자 제공\n")
            f.write("2026-10-04,홍,주민 " + rrn_hy + ",,1000,없음,급여,제안,,사용자 제공\n")
            f.write("2026-10-05,홍,주민 " + rrn_colon + ",,1000,없음,급여,제안,,사용자 제공\n")
            f.write("2026-10-06,홍,주민 " + rrn_star + ",,1000,없음,급여,제안,,사용자 제공\n")
            f.write("2026-10-07,홍,주민 " + rrn_pipe + ",,1000,없음,급여,제안,,사용자 제공\n")
            f.write("2026-10-08,가,카드 " + card_en + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-09,가,카드 " + card_hy + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-10,가,카드 " + card_colon + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-11,가,계좌 " + acct_en + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write('2026-10-12,가,쉼표,,1000,카드,소모품비,제안,"' + amount_ok + '",사용자 제공\n')
            f.write("2026-10-13,가,날짜 " + date_ok + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-14,가,날짜2 " + date_en + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-15,가,전화 " + phone_ok + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-16,가,사업자 " + biz + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-17,가," + date_amt + ",,1000,카드,소모품비,제안,,사용자 제공\n")
            f.write("2026-10-18,가,시각 " + time_ok + ",,1000,카드,소모품비,제안,,사용자 제공\n")
        out = os.path.join(self.tmp, "n5_out")
        code, stdout, tail = calc(pii, out, "--as-of", "2026-11-03")
        self.assertEqual(code, 10, stdout)
        blob = all_output_text(out) + stdout
        for raw in (card_en, card_hy, card_colon, acct_en):
            assert_masked_secret(self, blob, raw)
        for rrn in (rrn_en, rrn_em, rrn_mn, rrn_hy, rrn_colon, rrn_star, rrn_pipe):
            self.assertNotIn(rrn, blob, rrn)
            self.assertNotIn("900101", blob)
        self.assertNotIn("홍", blob)
        self.assertIn(amount_ok, blob)
        self.assertIn(date_ok, blob)
        self.assertIn(date_en, blob)
        self.assertIn(phone_ok, blob)
        self.assertIn(biz, blob)
        self.assertIn(mask_text(date_amt), blob)
        self.assertNotIn("1500000", blob)
        self.assertIn(time_ok, blob)
        result = json.loads(read(os.path.join(out, "result.json")))
        self.assertEqual(result["rrn_excluded_lines"], [2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(result["rows_in_ledger"], 11)


    def test_22_hangul_eu_separator_n5(self):
        eu = "\u3161"
        rrn = "900101" + eu + "1234567"
        card = "1234" + eu + "5678" + eu + "9012" + eu + "3456"
        pii = os.path.join(self.tmp, "n5b.csv")
        with open(pii, "w", encoding="utf-8", newline="") as f:
            f.write(HEADER + "\n")
            f.write("2026-10-01,홍,주민 " + rrn + ",,1000,없음,급여,제안,,사용자 제공\n")
            f.write("2026-10-02,가,카드 " + card + ",,1000,카드,소모품비,제안,,사용자 제공\n")
        out = os.path.join(self.tmp, "n5b_out")
        code, stdout, tail = calc(pii, out, "--as-of", "2026-11-03")
        self.assertEqual(code, 10, stdout)
        blob = all_output_text(out) + stdout
        assert_masked_secret(self, blob, card)
        self.assertNotIn("900101", blob)
        result = json.loads(read(os.path.join(out, "result.json")))
        self.assertEqual(result["rrn_excluded_lines"], [2])
        self.assertEqual(result["rows_in_ledger"], 1)


    def test_23_spaced_and_comma_separators_r4(self):
        en = "\u2013"
        eu = "\u3161"
        nbsp = "\u00a0"
        cases_mask_card = (
            "5123" + en + "4567" + en + "8901" + en + "2346",
            "1234,5678,9012,3456",
            "5123,4567,8901,2346",
            "5123, 4567, 8901, 2346",
            "5123" + eu + "4567" + eu + "8901" + eu + "2346",
            "5123 : 4567 : 8901 : 2346",
            "5123 | 4567 | 8901 | 2346",
            "5123" + nbsp + en + nbsp + "4567" + nbsp + en + nbsp + "8901" + nbsp + en + nbsp + "2346",
            "5123" + en + "-" + "4567" + en + "-" + "8901" + en + "-" + "2346",
            "5123--4567--8901--2346",
        )
        cases_exclude_rrn = (
            "850315" + en + "2345678",
            "850315,2345678",
            "850315" + eu + "2345678",
            "850315" + en + en + "2345678",
            "850315" + en + " " + "2345678",
            "850315" + " " + en + "2345678",
        )
        keep_plain = (
            "10월" + en + "11월 매출",
            "3" + en + "4개",
            "메모" + eu + "참고",
            "1,200,000",
            "1,234,567",
            "매출 1,200,000원 입금",
            "2026-10-02",
            "010-1234-5678",
            "123-45-67890",
            "2026-10-02 ****0000",
        )
        pii = os.path.join(self.tmp, "r4_23.csv")
        with open(pii, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(HEADER.split(","))
            for idx, secret in enumerate(cases_exclude_rrn):
                w.writerow(["2026-10-{0:02d}".format(idx + 1), "홍", "주민 " + secret, "",
                            "1000", "없음", "급여", "제안", "", "사용자 제공"])
            base = len(cases_exclude_rrn)
            for idx, secret in enumerate(cases_mask_card):
                w.writerow(["2026-10-{0:02d}".format(base + idx + 1), "가", "카드 " + secret, "",
                            "1000", "카드", "소모품비", "제안", "", "사용자 제공"])
            base += len(cases_mask_card)
            for idx, plain in enumerate(keep_plain):
                w.writerow(["2026-10-{0:02d}".format(base + idx + 1), "가", plain, "",
                            "1000", "카드", "소모품비", "제안", "", "사용자 제공"])
        out = os.path.join(self.tmp, "r4_23_out")
        code, stdout, tail = calc(pii, out, "--as-of", "2026-11-03")
        self.assertEqual(code, 10, stdout)
        blob = all_output_text(out) + stdout
        for secret in cases_exclude_rrn:
            self.assertNotIn("850315", blob, secret)
            self.assertNotIn("2345678", blob, secret)
            digits = "".join(c for c in unicodedata.normalize("NFKC", secret) if c.isdigit())
            if len(digits) > 4:
                self.assertNotIn(digits[:-4], blob, secret)
        for secret in cases_mask_card:
            assert_masked_secret(self, blob, secret)
            row_blob = ledger_rows_blob_for_secret(out, secret)
            assert_no_leaked_secret_digits(self, row_blob, secret)
        self.assertIn("****,****,****,3456", mask_text("카드 1234,5678,9012,3456"))
        self.assertIn("****,****,****,2346", mask_text("5123,4567,8901,2346"))
        for plain in keep_plain:
            self.assertIn(plain, blob, plain)
        result = json.loads(read(os.path.join(out, "result.json")))
        self.assertEqual(result["rows_in_ledger"], len(cases_mask_card) + len(keep_plain))
        self.assertEqual(len(result["rrn_excluded_lines"]), len(cases_exclude_rrn))

    def test_24_generative_separator_r4(self):
        import random

        GEN_SEED = 20261104
        GEN_COUNT = 64
        SEP_CHARS = "-–—\u2010\u2212\u3161:·|*./_,\u00a0 "
        MIXED_SEP_RUNS = (
            " _", " *-", " \u2013,", " \u2014.", " \u2212\u2013 ", " -\u2014",
            ", ", " ,\u2013", " \u3161_", " \u00a0-\u2013", " \u2013\u00a0",
        )
        rng = random.Random(GEN_SEED)

        def sep_run():
            if rng.random() < 0.35:
                return rng.choice(MIXED_SEP_RUNS)
            n = rng.randint(1, 3)
            return "".join(rng.choice(SEP_CHARS) for _ in range(n))

        def yymmdd():
            yy = rng.randint(50, 99)
            mm = rng.randint(1, 12)
            dd = rng.randint(1, 28)
            return "{0:02d}{1:02d}{2:02d}".format(yy, mm, dd)

        def rrn_like():
            return yymmdd() + sep_run() + str(rng.randint(1, 8)) + "".join(str(rng.randint(0, 9)) for _ in range(6))

        def card_like():
            parts = (
                tuple("{0:04d}".format(rng.randint(0, 9999)) for _ in range(4)),
                (("{0:04d}".format(rng.randint(0, 9999)), "{0:06d}".format(rng.randint(0, 999999)),
                  "{0:05d}".format(rng.randint(0, 99999)))),
                ("{0:03d}".format(rng.randint(0, 999)), "{0:03d}".format(rng.randint(0, 999)),
                 "{0:06d}".format(rng.randint(0, 999999))),
                ("{0:03d}".format(rng.randint(0, 999)), "{0:02d}".format(rng.randint(0, 99)),
                 "{0:06d}".format(rng.randint(0, 999999))),
            )
            chosen = rng.choice(parts)
            return sep_run().join(chosen)

        def account_like():
            return sep_run().join((
                "{0:03d}".format(rng.randint(0, 999)),
                "{0:03d}".format(rng.randint(0, 999)),
                "{0:06d}".format(rng.randint(0, 999999)),
            ))

        exceptions = [
            "1,200,000",
            "1,234,567",
            "2026-10-02",
            "2026" + rng.choice("-./") + "10" + rng.choice("-./") + "02",
            "2026" + "\uff0d" + "10" + "\uff0d" + "02",
            "010-1234-5678",
            "010" + "\u3161" + "1234" + "\u3161" + "5678",
            "02-1234-5678",
            "1588-1234",
            "123-45-67890",
            "123" + "\u3161" + "45" + "\u3161" + "67890",
            "2026-10-02 ****0000",
            "2026-11-03 5000원",
            "점심 2026-11-03 15000원",
            "10월" + sep_run() + "11월",
            "3" + sep_run() + "4개",
            "메모" + "\u3161" + "참고",
            "수량 100*단가 5000",
            "15000*100",
            "5,000,000~6,000,000",
            "5,000,000 \u2013 6,000,000",
            "1,200,000 ~ 3,400,000",
        ]

        generated = []
        while len(generated) < GEN_COUNT:
            kind = rng.randint(0, 5)
            if kind == 0:
                generated.append(("rrn", rrn_like()))
            elif kind == 1:
                generated.append(("card", card_like()))
            elif kind == 2:
                generated.append(("acct", account_like()))
            else:
                generated.append(("ok", rng.choice(exceptions)))

        pii = os.path.join(self.tmp, "r4_24.csv")
        with open(pii, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(HEADER.split(","))
            for idx, (kind, text) in enumerate(generated):
                day = (idx % 28) + 1
                w.writerow(["2026-10-{0:02d}".format(day), "가", text, "",
                            "1000", "카드", "소모품비", "제안", "", "사용자 제공"])
        out_a = os.path.join(self.tmp, "r4_24_a")
        out_b = os.path.join(self.tmp, "r4_24_b")
        code_a, stdout_a, _ = calc(pii, out_a, "--as-of", "2026-11-03")
        code_b, stdout_b, _ = calc(pii, out_b, "--as-of", "2026-11-03")
        self.assertEqual(code_a, code_b)
        self.assertEqual(all_output_text(out_a), all_output_text(out_b))
        blob = all_output_text(out_a) + stdout_a
        for kind, text in generated:
            if kind == "rrn":
                digits = "".join(c for c in unicodedata.normalize("NFKC", text) if c.isdigit())
                self.assertNotIn(digits[:6], blob, text)
                if len(digits) > 4:
                    self.assertNotIn(digits[:-4], blob, text)
            elif kind in ("card", "acct"):
                assert_masked_secret(self, blob, text)
            else:
                self.assertIn(text, blob, text)

    def test_26_mixed_gap_separators_and_comma_cards(self):
        eu = "\u3161"
        en = "\u2013"
        em = "\u2014"
        mn = "\u2212"
        mixed = (
            eu + " _",
            " *-",
            en + " ,",
            em + " .",
            mn + en + " ",
            " -" + em,
            " _" + eu,
            " *" + mn,
            en + "  ",
            " \u00a0" + en,
            ", " + en,
            " ." + eu,
        )
        rrn_cases = tuple("850315" + s + "2345678" for s in mixed)
        card_cases = tuple(
            "5123" + s + "4567" + s + "8901" + s + "2346" for s in mixed
        )
        acct_cases = tuple("351" + s + "246" + s + "809135" for s in mixed)
        comma_cards = ("1234,5678,9012,3456", "5123,4567,8901,2346")
        keep_plain = (
            "1,200,000",
            "1,234,567",
            "매출 1,200,000원 입금",
            "5,000,000~6,000,000",
            "5,000,000" + en + "6,000,000",
            "2026-10-02",
            "010-1234-5678",
            "123-45-67890",
            "10월" + en + "11월",
            "3" + en + "4개",
        )
        pii = os.path.join(self.tmp, "r5_26.csv")
        with open(pii, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(HEADER.split(","))
            idx = 0
            for secret in rrn_cases:
                idx += 1
                w.writerow(["2026-10-{0:02d}".format((idx % 28) + 1), "홍", "주민 " + secret, "",
                            "1000", "없음", "급여", "제안", "", "사용자 제공"])
            for secret in card_cases:
                idx += 1
                w.writerow(["2026-10-{0:02d}".format((idx % 28) + 1), "가", "카드 " + secret, "",
                            "1000", "카드", "소모품비", "제안", "", "사용자 제공"])
            for secret in acct_cases:
                idx += 1
                w.writerow(["2026-10-{0:02d}".format((idx % 28) + 1), "가", "계좌 " + secret, "",
                            "1000", "카드", "소모품비", "제안", "", "사용자 제공"])
            for secret in comma_cards:
                idx += 1
                w.writerow(["2026-10-{0:02d}".format((idx % 28) + 1), "가", "카드 " + secret, "",
                            "1000", "카드", "소모품비", "제안", "", "사용자 제공"])
            for plain in keep_plain:
                idx += 1
                w.writerow(["2026-10-{0:02d}".format((idx % 28) + 1), "가", plain, "",
                            "1000", "카드", "소모품비", "제안", "", "사용자 제공"])
        out = os.path.join(self.tmp, "r5_26_out")
        code, stdout, tail = calc(pii, out, "--as-of", "2026-11-03")
        self.assertEqual(code, 10, stdout)
        blob = all_output_text(out) + stdout
        for secret in rrn_cases:
            self.assertNotIn("850315", blob, secret)
            self.assertNotIn("2345678", blob, secret)
            assert_no_leaked_secret_digits(self, ledger_rows_blob_for_secret(out, secret) or blob, secret)
        for secret in card_cases + comma_cards:
            assert_masked_secret(self, blob, secret)
            assert_no_leaked_secret_digits(self, ledger_rows_blob_for_secret(out, secret), secret)
        for secret in acct_cases:
            assert_masked_secret(self, blob, secret)
            assert_no_leaked_secret_digits(self, ledger_rows_blob_for_secret(out, secret), secret)
        self.assertIn("****,****,****,3456", mask_text("1234,5678,9012,3456"))
        self.assertIn("****,****,****,2346", mask_text("5123,4567,8901,2346"))
        for plain in keep_plain:
            self.assertIn(plain, blob, plain)
        result = json.loads(read(os.path.join(out, "result.json")))
        self.assertEqual(len(result["rrn_excluded_lines"]), len(rrn_cases))
        self.assertGreaterEqual(len(rrn_cases), 10)
        self.assertGreaterEqual(len(card_cases), 10)
        self.assertGreaterEqual(len(acct_cases), 10)


    def test_25_r4b_regressions(self):
        en = "\u2013"
        eu = "\u3161"
        ff = "\uff0d"
        rrn_dots = "900101 ... 1234567"
        amount_ranges = (
            "5,000,000~6,000,000",
            "5,000,000" + en + "6,000,000",
            "1,200,000 ~ 3,400,000",
        )
        preserve = (
            "2026" + eu + "10" + eu + "02",
            "010" + eu + "1234" + eu + "5678",
            "123" + eu + "45" + eu + "67890",
            "메모" + eu + " 참고",
            "2026" + ff + "10" + ff + "02",
        )
        mask_card = "5123" + en + "4567" + en + "8901" + en + "2346"
        pii = os.path.join(self.tmp, "r4_25.csv")
        with open(pii, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(HEADER.split(","))
            w.writerow(["2026-10-01", "홍", rrn_dots, "", "1000", "없음", "급여", "제안", "", "사용자 제공"])
            for idx, text in enumerate(amount_ranges):
                w.writerow(["2026-10-{0:02d}".format(idx + 2), "가", text, "",
                            "1000", "카드", "소모품비", "제안", "", "사용자 제공"])
            base = 2 + len(amount_ranges)
            for idx, text in enumerate(preserve):
                w.writerow(["2026-10-{0:02d}".format(base + idx), "가", text, "",
                            "1000", "카드", "소모품비", "제안", text if idx == 3 else "", "사용자 제공"])
            w.writerow(["2026-10-20", "가", "카드 " + mask_card, "",
                        "1000", "카드", "소모품비", "제안", "", "사용자 제공"])
        out = os.path.join(self.tmp, "r4_25_out")
        code, stdout, _ = calc(pii, out, "--as-of", "2026-11-03")
        self.assertEqual(code, 10, stdout)
        blob = all_output_text(out) + stdout
        self.assertNotIn("900101", blob)
        self.assertNotIn("1234567", blob)
        for text in amount_ranges:
            self.assertIn(text, blob, text)
        for text in preserve:
            self.assertIn(text, blob, text)
        assert_masked_secret(self, blob, mask_card)
        result = json.loads(read(os.path.join(out, "result.json")))
        self.assertEqual(result["rrn_excluded_lines"], [2])
        self.assertEqual(result["rows_in_ledger"], len(amount_ranges) + len(preserve) + 1)

    def test_27_n9_card_rrn_before_trailing_amount(self):
        card_space = "5123 4567 8901 2346"
        card_dash = "5123-4567-8901-2346"
        card_glued = "5123456789012346"
        rrn = "850315-2345678"
        mask_cases = (
            ("카드 " + card_space + " 1,000원", ("1,000원",)),
            ("카드 " + card_dash + " 1,000원", ("1,000원",)),
            ("카드 " + card_dash + " 결제 1,000원", ("결제 1,000원",)),
            ("카드 " + card_dash + " 1,000", ("1,000",)),
            (card_glued + " 1,000", ("1,000",)),
            (card_glued + " 1,000원", ("1,000원",)),
            (card_glued + " 5,000,000원", ()),
            ("카드 " + card_glued + ", 1,000원", ("1,000원",)),
            ("1,000원 " + card_space + " 2,000원", ("1,000원", "2,000원")),
            ("1,000원 " + card_dash, ("1,000원",)),
            ("합계 1,500,000 카드 " + card_space, ("합계 1,500,000",)),
            ("1,200,000원 / " + card_dash.replace("-", ","), ("1,200,000원 /",)),
            ("매출 2,000,000, 카드 " + card_space, ("매출 2,000,000,",)),
            ("카드 " + card_space + " 15000원", ("5000원",)),
            ("카드 " + card_space + " 3", ("3",)),
            ("카드 " + card_glued + " 3개", ("3개",)),
            ("카드 " + card_dash + " 15000원", ("5000원",)),
            (card_space + " 2026-11-03", ("2026-11-03",)),
            ("2026-11-03 " + card_space, ()),
            (card_space + " / 2026-11-03", ("/ 2026-11-03",)),
        )
        exclude_rrn = (
            rrn + " 1,500,000원",
            rrn + " 1,500,000",
            "8503152345678 1,500,000원",
            "홍길동 " + rrn + " 1,500,000원",
            "850315 2345678 1,500,000원",
            "850315 2345678 15000원",
            rrn + " 1500000원",
            rrn + " 2026-11-03",
        )
        for raw, keep_parts in mask_cases:
            masked = mask_text(raw)
            for part in keep_parts:
                self.assertIn(part, masked, raw)
            assert_no_leaked_secret_digits(self, masked, card_space if card_space in raw else card_dash if card_dash in raw else card_glued)
        for raw in exclude_rrn:
            self.assertTrue(row_contains_rrn(raw), raw)

        pii = os.path.join(self.tmp, "n9.csv")
        with open(pii, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(HEADER.split(","))
            w.writerow(["2026-11-03", "가", mask_cases[0][0], "", "1000", "카드", "소모품비", "제안", "", "사용자 제공"])
            w.writerow(["2026-11-04", "홍", exclude_rrn[0], "", "1000", "없음", "급여", "제안", "", "사용자 제공"])
        out = os.path.join(self.tmp, "n9_out")
        code, stdout, tail = calc(pii, out, "--as-of", "2026-11-03")
        self.assertEqual(code, 10, stdout)
        blob = all_output_text(out) + stdout
        assert_no_leaked_secret_digits(self, ledger_rows_blob_for_secret(out, card_space), card_space)
        self.assertIn("1,000원", blob)
        self.assertNotIn("850315", blob)
        result = json.loads(read(os.path.join(out, "result.json")))
        self.assertEqual(result["rrn_excluded_lines"], [3])

    def test_28_n10_n12_preserve_and_totals_invariant(self):
        preserve = (
            "2026-11-03 5000원",
            "2026-11-03 5000",
            "점심 2026-11-03 15000원",
            "점심 2026-11-03 15000",
            "2026.11.03 12000원",
            "2026/07/21 407원",
            "2026-11-03 500",
            "2026-11-03 100000",
            "2026-11-03 1000000원",
            "2026-11-03 15000원 점심",
            "2026.11.03 매출 15000원",
            "2026-11-03 15000 입금",
            "거래일 2026-11-03 1,500,000원",
            "2026-11-03 ~ 2026-11-30 15000원",
            "2026-11-03 1500000",
            "입금 2026-11-03 1500000원",
            "2026-11-03 3500원 2026-11-04 4500원",
            "2026-11-03 5,000원",
            "매출 20261103 1000000",
            "20260101 20261231",
            "2026-01-01 ~ 2026-12-31",
            "2026-01-01~2026-12-31 1,000",
            "2026-11-03 2026-11-04 2026-11-05",
            "1 2 3 4 5 6 7 8 9 10 11",
            "10 20 30 40 50 60 70",
            "1000 2000 3000 4000",
            "2025, 2026, 2027",
            "2025, 2026, 2027년",
            "2025 2026 2027",
            "3 5000 7000 9000 100",
            "1000 2000 3000",
        )
        rows = []
        expected_in = 0
        expected_out = 0
        for idx, text in enumerate(preserve):
            day = (idx % 28) + 1
            amt = 1000 + idx
            if idx % 2 == 0:
                rows.append(["2026-11-{0:02d}".format(day), "가", text, str(amt), "", "카드", "매출", "확정", "", "사용자 제공"])
                expected_in += amt
            else:
                rows.append(["2026-11-{0:02d}".format(day), "가", text, "", str(amt), "카드", "소모품비", "확정", "", "사용자 제공"])
                expected_out += amt
        pii = os.path.join(self.tmp, "n10_n12.csv")
        with open(pii, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(HEADER.split(","))
            for row in rows:
                w.writerow(row)
        out = os.path.join(self.tmp, "n10_out")
        code, stdout, tail = calc(pii, out, "--as-of", "2026-11-03")
        self.assertEqual(code, 0, stdout)
        ledger = read_csv(os.path.join(out, OUTPUT_FILES[0]))[2:]
        for idx, text in enumerate(preserve):
            self.assertEqual(mask_text(text), ledger[idx][3], text)
        result = json.loads(read(os.path.join(out, "result.json")))
        self.assertEqual(result["totals"]["in"], expected_in)
        self.assertEqual(result["totals"]["out"], expected_out)
        self.assertEqual(result["totals"]["net"], expected_in - expected_out)
        pnl_rows = [r for r in read_csv(os.path.join(out, OUTPUT_FILES[1]))[2:] if r and r[0] == "합계"]
        self.assertEqual(int(pnl_rows[0][1]), expected_in)
        self.assertEqual(int(pnl_rows[0][2]), expected_out)

    def test_29_r6_examples_and_adjacent_number_leaks(self):
        mask_cases = (
            "계좌 301 1234 5678 91 입금",
            "1234 5678 9012",
            "110 1234 5678",
            "3 5123 4567 8901 2346",
            "110 - 123 – 456789 / 01",
            "15000 850315-2345678",
            "010-1234-5678 850315-2345678",
            "1500000 850315-2345678",
            "15000 5123 4567 8901 2346",
            "20260810 4855-4565-2755-8282",
            "010-1234-5678 5123-4567-8901-2346",
            "123-45-67890 5123-4567-8901-2346",
            "5123-4567-8901-2346 123-45-67890",
            "5123-4567-8901-2346 010-1234-5678",
            "850315-2345678 010-1234-5678",
            "110-123-456789 110-123-456789",
            "110-123-456789 5000원",
            "110-123-456789 12345",
            "5123456789012346 20261103",
            "20261103 850315-2345678",
            "14:30 5123456789012346",
            "259,918 130-851-557966",
            "5123 4567 8901 2346 5123 4567 8901 2346",
        )
        exclude_lines = (
            "15000 850315-2345678",
            "010-1234-5678 850315-2345678",
            "1500000 850315-2345678",
            "20261103 850315-2345678",
            "850315-2345678 010-1234-5678",
        )
        for raw in mask_cases:
            if raw in exclude_lines:
                self.assertTrue(row_contains_rrn(raw), raw)
                continue
            masked = mask_text(raw)
            norm_m = unicodedata.normalize("NFKC", masked)
            digits = "".join(c for c in unicodedata.normalize("NFKC", raw) if c.isdigit())
            if len(digits) > 4:
                self.assertNotIn(digits[:-4], norm_m, raw)

        pii = os.path.join(self.tmp, "r7_t29.csv")
        with open(pii, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(HEADER.split(","))
            for idx, text in enumerate(mask_cases):
                w.writerow(["2026-11-{0:02d}".format((idx % 28) + 1), "가", text, "",
                            "1000", "카드", "소모품비", "제안", "", "사용자 제공"])
        out = os.path.join(self.tmp, "r7_t29_out")
        code, stdout, tail = calc(pii, out, "--as-of", "2026-11-03")
        self.assertEqual(code, 10, stdout)
        blob = all_output_text(out) + stdout
        result = json.loads(read(os.path.join(out, "result.json")))
        ledger = read_csv(os.path.join(out, OUTPUT_FILES[0]))[2:]
        by_line = {int(r[0]): r[3] for r in ledger}
        for raw in exclude_lines:
            self.assertTrue(row_contains_rrn(raw))
            line_no = mask_cases.index(raw) + 2
            self.assertIn(line_no, result["rrn_excluded_lines"], raw)
            self.assertNotIn("850315", blob, raw)
        for idx, raw in enumerate(mask_cases):
            if raw in exclude_lines:
                continue
            line_no = idx + 2
            row_blob = by_line.get(line_no, "")
            self.assertTrue(row_blob, raw)
            norm_raw = unicodedata.normalize("NFKC", raw)
            digits = "".join(c for c in norm_raw if c.isdigit())
            if len(digits) > 4:
                self.assertNotIn(digits[:-4], unicodedata.normalize("NFKC", row_blob), raw)

    def test_30_fuzz_adjacent_tokens(self):
        import random

        def run_seed(seed, count=100):
            rng = random.Random(seed)
            sep_chars = "-–—\u2010\u2212\u3161:·|*./_,\u00a0 "
            cases = []

            def sep_run():
                return "".join(rng.choice(sep_chars) for _ in range(rng.randint(1, 2)))

            def yymmdd():
                return "{0:02d}{1:02d}{2:02d}".format(rng.randint(50, 99), rng.randint(1, 12), rng.randint(1, 28))

            def rrn():
                return yymmdd() + sep_run() + str(rng.randint(1, 8)) + "".join(str(rng.randint(0, 9)) for _ in range(6))

            def card():
                return sep_run().join("{0:04d}".format(rng.randint(0, 9999)) for _ in range(4))

            def acct():
                return sep_run().join((
                    "{0:03d}".format(rng.randint(0, 999)),
                    "{0:03d}".format(rng.randint(0, 999)),
                    "{0:06d}".format(rng.randint(0, 999999)),
                ))

            prefixes = (
                lambda: str(rng.randint(1, 9999999)),
                lambda: "010" + sep_run() + "1234" + sep_run() + "5678",
                lambda: "123" + sep_run() + "45" + sep_run() + "67890",
                lambda: str(rng.randint(1, 99)) + "개",
                lambda: "{0:02d}:{1:02d}".format(rng.randint(0, 23), rng.randint(0, 59)),
                lambda: "20261103",
                lambda: "1,234,567",
                lambda: "2026-11-03",
            )
            while len(cases) < count:
                kind = rng.choice(("rrn", "card", "acct"))
                body = {"rrn": rrn, "card": card, "acct": acct}[kind]()
                mode = rng.randint(0, 2)
                if mode == 0:
                    text = rng.choice(prefixes)() + " " + body
                elif mode == 1:
                    text = body + " " + rng.choice(prefixes)()
                else:
                    text = rng.choice(prefixes)() + " " + body + " " + rng.choice(prefixes)()
                if kind != "rrn" and row_contains_rrn(text):
                    continue
                cases.append((kind, text))

            pii = os.path.join(self.tmp, "fuzz_{}.csv".format(seed))
            with open(pii, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(HEADER.split(","))
                for idx, (_k, text) in enumerate(cases):
                    w.writerow(["2026-11-{0:02d}".format((idx % 28) + 1), "가", text, "",
                                "1000", "카드", "소모품비", "제안", "", "사용자 제공"])
            out_a = os.path.join(self.tmp, "fuzz_{}_a".format(seed))
            out_b = os.path.join(self.tmp, "fuzz_{}_b".format(seed))
            code_a, stdout_a, _ = calc(pii, out_a, "--as-of", "2026-11-03")
            code_b, stdout_b, _ = calc(pii, out_b, "--as-of", "2026-11-03")
            self.assertEqual(code_a, code_b)
            self.assertEqual(all_output_text(out_a), all_output_text(out_b))
            blob = all_output_text(out_a) + stdout_a
            blob_n = unicodedata.normalize("NFKC", blob)
            ledger = read_csv(os.path.join(out_a, OUTPUT_FILES[0]))[2:]
            by_line = {int(r[0]): r[3] for r in ledger}
            rrn_lines = json.loads(read(os.path.join(out_a, "result.json")))["rrn_excluded_lines"]
            for idx, (kind, text) in enumerate(cases):
                line_no = idx + 2
                if kind == "rrn":
                    self.assertTrue(row_contains_rrn(text), text)
                    self.assertIn(line_no, rrn_lines)
                    continue
                row_blob = by_line.get(line_no, "")
                self.assertTrue(row_blob, text)
                masked = mask_text(text)
                self.assertTrue(fuzz_output_masks_input_digits(text, masked), text)
                self.assertTrue(fuzz_output_masks_input_digits(text, row_blob), text)
                self.assertFalse(independent_digit_leak(text, masked), text)
                self.assertFalse(independent_digit_leak(text, row_blob), text)

        bad_out = "5123 4567 8901 2346"
        self.assertTrue(independent_digit_leak(bad_out, bad_out))
        self.assertFalse(independent_digit_leak(bad_out, mask_text(bad_out)))

        for seed in (20261104, 20261105):
            run_seed(seed, 100)

    def test_31_r8_simple_rules_f1_f2_f3(self):
        mask_inputs = (
            "123456 789012",
            "12345678 12345678",
            "987654321012 765432",
            "1000000 2000000",
            "송금 1000000 2000000",
            "2026-11-03 5123 4567 8901 2346",
            "2026-10-02 110-123-456789",
            "2026-10-02 987654321012",
            "110,123,456789",
            "1234 5678 9012",
            "2025,2026,2027",
            "계좌 301 1234 5678 91 입금",
            "110 1234 5678",
            "3 5123 4567 8901 2346",
            "110 - 123 – 456789 / 01",
        )
        exclude_inputs = (
            "15000 850315-2345678",
            "010-1234-5678 850315-2345678",
        )
        preserve_inputs = (
            "2026-11-03 5000원",
            "점심 2026-11-03 15000원",
            "1,234,567",
            "매출 1,200,000원 입금",
            "010-1234-5678",
            "123-45-67890",
            "10월 – 11월 매출",
            "3 – 4개",
            "수량 100*단가 5000",
            "10:30",
        )
        for raw in preserve_inputs:
            self.assertEqual(mask_text(raw), raw, raw)
        for raw in exclude_inputs:
            self.assertTrue(row_contains_rrn(raw), raw)

        pii = os.path.join(self.tmp, "r8_t31.csv")
        with open(pii, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(HEADER.split(","))
            rows = list(mask_inputs) + list(exclude_inputs)
            for idx, text in enumerate(rows):
                w.writerow(["2026-11-{0:02d}".format((idx % 28) + 1), "가", text, "",
                            "1000", "카드", "소모품비", "제안", "", "사용자 제공"])
        out = os.path.join(self.tmp, "r8_t31_out")
        code, stdout, tail = calc(pii, out, "--as-of", "2026-11-03")
        self.assertEqual(code, 10, stdout)
        blob = all_output_text(out) + stdout
        result = json.loads(read(os.path.join(out, "result.json")))
        ledger = read_csv(os.path.join(out, OUTPUT_FILES[0]))[2:]
        by_line = {int(r[0]): r[3] for r in ledger}
        for raw in exclude_inputs:
            line_no = rows.index(raw) + 2
            self.assertIn(line_no, result["rrn_excluded_lines"], raw)
            self.assertNotIn("850315", blob, raw)
        for idx, raw in enumerate(mask_inputs):
            line_no = idx + 2
            row_text = by_line.get(line_no, "")
            self.assertTrue(row_text, raw)
            for surface in (mask_text(raw), row_text):
                self.assertTrue(fuzz_output_masks_input_digits(raw, surface), raw)
                self.assertFalse(independent_digit_leak(raw, surface), raw)
            norm_o = unicodedata.normalize("NFKC", raw)
            for i, c in enumerate(norm_o):
                if not c.isdigit():
                    continue
                j = i
                while j < len(norm_o) and norm_o[j].isdigit():
                    j += 1
                if j - i >= 5 and norm_o[i:j] in unicodedata.normalize("NFKC", blob):
                    self.fail("5+ digit chunk in blob for {!r}".format(raw))

    def test_32_r9_known_regression_cases(self):
        must_mask = (
            "2026-11-03 15000",
            "2026-11-03 100000",
            "2026-11-03 1500000",
            "2011-0304-5678-9012",
            "110,123,456789",
            "259,918 130-851-557966",
            "010-1234-5678 5123-4567-8901-2346",
            "5123-4567-8901-2346 1,500,000원",
        )
        for raw in must_mask:
            masked = mask_text(raw)
            self.assertNotEqual(masked, raw, raw)
            self.assertFalse(independent_digit_leak(raw, masked), raw)

    def test_33_round8_baseline_leak_count(self):
        import importlib.util
        import random

        r8_path = os.path.join(ROOT, "reference", "ledger_calc_r8.py")
        spec = importlib.util.spec_from_file_location("ledger_calc_r8", r8_path)
        r8 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(r8)

        def count_r9(seed, n=300):
            rng = random.Random(seed)
            sep_chars = "-–—\u2010\u2212\u3161:·|*./_,\u00a0 "
            def sep_run():
                return "".join(rng.choice(sep_chars) for _ in range(rng.randint(1, 2)))
            def card():
                return sep_run().join("{0:04d}".format(rng.randint(0, 9999)) for _ in range(4))
            def acct():
                return sep_run().join((
                    "{0:03d}".format(rng.randint(0, 999)),
                    "{0:03d}".format(rng.randint(0, 999)),
                    "{0:06d}".format(rng.randint(0, 999999)),
                ))
            prefixes = (
                lambda: str(rng.randint(1, 9999999)),
                lambda: "010" + sep_run() + "1234" + sep_run() + "5678",
                lambda: "123" + sep_run() + "45" + sep_run() + "67890",
                lambda: str(rng.randint(1, 99)) + "개",
                lambda: "{0:02d}:{1:02d}".format(rng.randint(0, 23), rng.randint(0, 59)),
                lambda: "20261103",
                lambda: "1,234,567",
                lambda: "2026-11-03",
            )
            leaks = 0
            total = 0
            attempts = 0
            while total < n and attempts < 100000:
                attempts += 1
                kind = rng.choice(("card", "acct"))
                body = card() if kind == "card" else acct()
                mode = rng.randint(0, 2)
                if mode == 0:
                    text = rng.choice(prefixes)() + " " + body
                elif mode == 1:
                    text = body + " " + rng.choice(prefixes)()
                else:
                    text = rng.choice(prefixes)() + " " + body + " " + rng.choice(prefixes)()
                if row_contains_rrn(text):
                    continue
                total += 1
                if independent_digit_leak(text, mask_text(text)):
                    leaks += 1
            return leaks

        self.assertEqual(count_r9(20261104), 0)
        self.assertEqual(count_r9(20261105), 0)

        def count_r8(seed, n=300):
            rng = random.Random(seed)
            sep_chars = "-–—\u2010\u2212\u3161:·|*./_,\u00a0 "
            def sep_run():
                return "".join(rng.choice(sep_chars) for _ in range(rng.randint(1, 2)))
            def card():
                return sep_run().join("{0:04d}".format(rng.randint(0, 9999)) for _ in range(4))
            def acct():
                return sep_run().join((
                    "{0:03d}".format(rng.randint(0, 999)),
                    "{0:03d}".format(rng.randint(0, 999)),
                    "{0:06d}".format(rng.randint(0, 999999)),
                ))
            prefixes = (
                lambda: str(rng.randint(1, 9999999)),
                lambda: "010" + sep_run() + "1234" + sep_run() + "5678",
                lambda: "123" + sep_run() + "45" + sep_run() + "67890",
                lambda: str(rng.randint(1, 99)) + "개",
                lambda: "{0:02d}:{1:02d}".format(rng.randint(0, 23), rng.randint(0, 59)),
                lambda: "20261103",
                lambda: "1,234,567",
                lambda: "2026-11-03",
            )
            leaks = 0
            total = 0
            attempts = 0
            while total < n and attempts < 100000:
                attempts += 1
                kind = rng.choice(("card", "acct"))
                body = card() if kind == "card" else acct()
                mode = rng.randint(0, 2)
                if mode == 0:
                    text = rng.choice(prefixes)() + " " + body
                elif mode == 1:
                    text = body + " " + rng.choice(prefixes)()
                else:
                    text = rng.choice(prefixes)() + " " + body + " " + rng.choice(prefixes)()
                if r8.row_contains_rrn(text):
                    continue
                total += 1
                if independent_digit_leak(text, r8.mask_text(text)):
                    leaks += 1
            return leaks

        self.assertGreater(count_r8(20261104), 0)
        self.assertGreater(count_r8(20261105), 0)
        self.assertTrue(independent_digit_leak("2026-11-03 15000", r8.mask_text("2026-11-03 15000")))

    def test_34_qa_pr1_high_medium_regressions(self):
        """QA PR#1 (N-17~N-20) 고정 입력: 수정 전 head·8차에서 깨지는 케이스."""
        import importlib.util

        r8_path = os.path.join(ROOT, "reference", "ledger_calc_r8.py")
        spec = importlib.util.spec_from_file_location("ledger_calc_r8", r8_path)
        r8 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(r8)

        cases = (
            ("카드 5123-4567-8901-2346 11:05", "카드 ****-****-****-**** 11:05"),
            ("5123-4567-8901-2346 11:05:09", "****-****-****-**** **:05:09"),
            ("5123-4567-8901-2346 12:30~13:30", "****-****-****-**** **:**~13:30"),
            ("045 5123 4567 8901 2346", "*** **** **** **** 2346"),
            ("7953-49-18-53", "****-**-18-53"),
        )
        pre_fix = (
            "카드 ****-****-8901-2346 11:05",
            "****-****-8901-2346 11:05:09",
            "****-****-8901-2346 12:30~13:30",
            "045 5123 4567 8901 2346",
            "7953-49-18-53",
        )
        for (raw, expected), bad in zip(cases, pre_fix):
            masked = mask_text(raw)
            self.assertEqual(masked, expected, raw)
            self.assertFalse(independent_digit_leak(raw, masked), raw)
            self.assertNotEqual(bad, expected, raw)
        self.assertEqual(r8.mask_text(cases[0][0]), pre_fix[0])
        self.assertEqual(r8.mask_text(cases[1][0]), cases[1][1])
        self.assertEqual(r8.mask_text(cases[3][0]), pre_fix[3])
        self.assertNotEqual(r8.mask_text(cases[4][0]), pre_fix[4])

        self.assertTrue(independent_digit_leak("5123 4567 8901 2346", "5123 4567 8901 2346"))
        self.assertFalse(independent_digit_leak("5123 4567 8901 2346", mask_text("5123 4567 8901 2346")))

    def test_36_round10_qa_recheck_regressions(self):
        """Round10 QA 재검(N-25·N-27·N-28) + 카드+시각(연도 1900~2100) 회귀."""
        cases = (
            ("카드 5123-4567-8901-2024 11:05", "카드 ****-****-****-**** 11:05"),
            ("카드 5123-4567-8901-1999 12:30", "카드 ****-****-****-**** 12:30"),
            ("카드 5123 4567 8901 2024 11:05", "카드 **** **** **** **** 11:05"),
            ("123-45-67890 1234", "***-**-***** 1234"),
            ("계좌 110-12-34567-89", "계좌 ***-**-***67-89"),
            ("3,764 / 17-47728-5434", "*,*** / **-*****-5434"),
        )
        for raw, expected in cases:
            masked = mask_text(raw)
            self.assertEqual(masked, expected, raw)
            self.assertFalse(independent_digit_leak(raw, masked), raw)
        partial = "카드 ****-****-8901-2024 11:05"
        self.assertTrue(independent_digit_leak("카드 5123-4567-8901-2024 11:05", partial))

    def test_35_strict_fuzz_six_checker_false_positives(self):
        """strict fuzz 잔여 건: 가림 정상·검사기만 run 구간/날짜 꼬리 분리로 오탐 제거."""
        cases = (
            "47개 469_*424_*476990 2026-11-03",
            "46개 8529_:9485_:7506_:6356 2026-11-03",
            "61개 6087ㅡ–9284ㅡ–4261ㅡ–1403 2026-11-03",
            "20개 1931—6043—1410—3130 2026-11-03",
            "46개 1197·|3911·|7956·|1761 2026-11-03",
            "58개 549−/285−/080471 2026-11-03",
            "5052821 5444–2426–1105–7271 2026-11-03",
        )
        for raw in cases:
            masked = mask_text(raw)
            self.assertFalse(independent_digit_leak(raw, masked), raw)


if __name__ == "__main__":
    unittest.main()
