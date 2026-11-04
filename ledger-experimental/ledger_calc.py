#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""세금정리도우미 「내 회사 장부 초안」 계산 프로그램.

- 표준 라이브러리만 써요. 바깥 네트워크·현재 시각·난수는 쓰지 않아요.
- 같은 입력이면 같은 결과가 나와요(JSON은 sort_keys, 금액은 정수 원 단위).
- 세액·환급액 계산, 공제·필요경비 판단, 파일 지우기 기능은 없어요.

명령:
  calc        장부 CSV를 받아 장부 표·월별 손익·월별 현금 흐름·요약을 만들어요.
  topic       일반 절세 정보 한 줄(근거 조문·확인일)을 보여 드려요.
  guard       문장을 보고 정해진 답(거절·세무사 상의 안내 등)을 골라요.
  lint        쓰면 안 되는 표현이 있는지 검사해요.
  list-drafts 지울 수 있는 파일 이름과 개수만 보여 드려요(지우지 않아요).
"""

import argparse
import csv
import datetime
import hashlib
import io
import json
import os
import re
import sys
import unicodedata

NOTICE = "참고용 초안_신고용 아님"
CHECK = "[확인 필요]"
NUMBER_SLOT = "[확인 필요: 법제처 원문 확인 뒤에만]"
CHECK_DATE = "2026-11-03"
CHECK_ORG = "법제처 국가법령정보센터"

REFUSAL = "이 도우미는 사용자님 본인 사업장 자료만 정리해요. 다른 회사 장부는 세무사에게 맡겨 주세요."
FILING_ANSWER = "신고는 세무사와 상의해 주세요."
PERSONAL_ANSWER = "사용자님 숫자나 상황을 넣은 계산·판단은 하지 않아요. 일반 정보 한 줄과 세무사 질문 목록만 드릴게요."
CONFIRM_WITH_ADVISOR = "사용자님 경우에 맞는지는 세무사와 확인해 주세요."
DISCLAIMER = "참고용 안내이며 세무대리나 세무상담이 아닙니다. 최종 판단은 직접 하시고, 중요한 건 세무사와 상의해 주세요."
BASIS = "현금 기준 단순 합계이며 결산 조정·세액 계산은 하지 않았어요."
HASH_MISMATCH = "[확인 필요] 계산 프로그램 해시가 달라 합계를 내지 않았어요."
RRN_MSG = "주민번호가 보여서 옮기지 않았어요. 가려서 다시 보내 주세요"
NO_INFO = "확인한 일반 정보가 아직 없어요."
VAT_REFERRAL = "부가세챙김이가 더 자세히 도와드려요."

INPUT_COLUMNS = ["날짜", "거래처", "내용", "들어온돈", "나간돈", "증빙종류", "계정", "계정상태", "메모", "출처"]
MASK_TEXT_COLUMNS = frozenset(("거래처", "내용", "증빙종류", "계정", "계정상태", "메모", "출처"))
LEDGER_COLUMNS = ["줄번호"] + INPUT_COLUMNS + ["합계반영"]
EVIDENCE_TYPES = ("세금계산서", "카드", "현금영수증", "간이영수증", "없음")

LEDGER_FILE = NOTICE + "_장부.csv"
PNL_FILE = NOTICE + "_월별손익.csv"
CASHFLOW_FILE = NOTICE + "_월별현금흐름.csv"
SUMMARY_FILE = NOTICE + "_요약.md"
RESULT_FILE = "result.json"
OUTPUT_FILES = [LEDGER_FILE, PNL_FILE, CASHFLOW_FILE, SUMMARY_FILE, RESULT_FILE]

OTHER_BUSINESS_PHRASES = ("고객사", "의뢰받은", "의뢰 받은", "지인 회사", "지인회사", "여러 사업자",
                          "다른 회사", "남의 회사", "친구 회사", "다른 사업자", "남의 장부",
                          "거래처 장부", "고객 장부", "클라이언트 회사", "의뢰인", "위임받", "대리로",
                          "친구 가게", "제 동생 가게")
FILING_WORDS = ("신고해도", "신고 해도", "신고하면 돼", "신고하면 되", "신고 가능", "제출해도",
                "제출 해도", "신고서 작성", "신고서 써")
PERSONAL_WORDS = ("제 경우", "저의 경우", "제 상황", "저는 얼마", "얼마 아", "얼마나 아", "얼마 절세",
                  "얼마 환급", "환급 얼마", "세금이 얼마", "세금 얼마", "공제되나", "공제 되나",
                  "공제돼", "공제 돼", "공제 받을 수 있", "공제받을 수 있", "경비로 인정되나",
                  "경비 처리 되나", "경비처리되나", "경비처리 되나", "경비 처리돼", "경비처리돼",
                  "손금 되", "손금 인정", "환급받", "환급 받", "대상자인가", "대상자인가요",
                  "간편장부 대상", "복식부기 해야", "절세 방법", "세금 줄", "줄이는 방법",
                  "종소세 계산", "계산해줘", "계산 해줘", "얼마 받", "얼마 나와", "얼마 내")
LINT_TERMS = ("기장 대행", "기장대행", "장부 대행", "장부대행", "대가 없이", "대가없이",
              "제휴 세무사", "제휴세무사", "세무사 매칭", "세무사매칭", "제휴 노무사", "제휴노무사",
              "노무사 매칭", "노무사매칭", "노무사 연결", "노무사연결", "세무사 연결", "세무사연결",
              "세무사 소개", "세무사소개", "장부 대신", "장부대신", "대신 작성", "대신작성")
LEGAL_TERM = "기장세액공제"

ADVISOR_QUESTIONS = [
    "제 사업 형태와 규모에서는 어떤 장부(간편장부·복식부기)를 써야 하나요?",
    "제 지출 가운데 경비(손금)로 넣을 수 있는 것과 없는 것을 봐 주실 수 있나요?",
    "제가 받을 수 있는 공제·감면이 있는지 확인해 주실 수 있나요?",
    "제 신고 기한과 신고 때 함께 낼 서류는 무엇인가요?",
    "증빙이 없는 거래는 어떻게 처리하면 되나요?",
]

# 일반 절세 정보: 설계 문서의 조문 표만 써요. 세율·한도·금액·기한 숫자는 넣지 않아요.
# links 항목: (법령 이름, 조번호, 가지번호)
TOPICS = {
    "G1": {
        "title": "장부의 종류",
        "info": "사업자는 장부를 갖춰 두고 거래를 기록해야 해요. 개인사업자는 간편장부 또는 복식부기 장부를 쓰고, "
                "법인은 복식부기로 기록해요. 어느 쪽 대상인지 나누는 기준은 " + NUMBER_SLOT,
        "basis": "소득세법 제160조, 소득세법 시행령 제208조, 법인세법 제112조",
        "links": [("소득세법", 160, 0), ("소득세법 시행령", 208, 0), ("법인세법", 112, 0)],
        "remaining": "시행규칙 예외(욕탕업 등) 원문 미확인",
    },
    "G2": {
        "title": "기장세액공제",
        "info": "간편장부대상자가 복식부기에 따라 장부를 작성하고 그 장부로 종합소득세를 신고하면 "
                "기장세액공제를 받을 수 있다는 규정이 있어요. 공제 비율과 한도는 " + NUMBER_SLOT,
        "basis": "소득세법 제56조의2, 제70조 제4항 제3호 (제56조의3은 전자계산서 세액공제로 다른 조문)",
        "links": [("소득세법", 56, 2), ("소득세법", 70, 0)],
        "remaining": "시행령(필요한 사항) 미확인",
    },
    "G3": {
        "title": "종합소득세 신고기간",
        "info": "종합소득이 있는 사람은 정해진 신고기간에 종합소득 과세표준 확정신고를 해요. "
                "성실신고확인 대상자는 신고기간이 따로 정해져 있어요. 신고기간은 " + NUMBER_SLOT,
        "basis": "소득세법 제70조, 제70조의2, 소득세법 시행령 제133조",
        "links": [("소득세법", 70, 0), ("소득세법", 70, 2), ("소득세법 시행령", 133, 0)],
        "remaining": "신고기한이 토요일·공휴일이면 다음 날(국세기본법 원문 미확인)",
    },
    "G4": {
        "title": "법인세 신고",
        "info": "법인은 각 사업연도가 끝난 뒤 정해진 기간 안에 법인세 과세표준을 신고해요. 신고 기한은 " + NUMBER_SLOT,
        "basis": "법인세법 제60조",
        "links": [("법인세법", 60, 0)],
        "remaining": "성실신고확인 대상 법인 범위(법인세법 제60조의2) 미확인",
    },
    "G6": {
        "title": "지출증명(증빙) 받기·보관",
        "info": "사업과 관련해 돈을 쓸 때는 세금계산서·계산서·신용카드 매출전표·현금영수증 같은 증명서류를 받고, "
                "장부와 증빙을 정해진 기간 동안 보관해야 해요. 증빙을 받지 않으면 가산세가 붙을 수 있어요. "
                "보관 기간·기준 금액·가산세 비율은 " + NUMBER_SLOT,
        "basis": "소득세법 제160조의2, 제81조, 제81조의6, 소득세법 시행령 제132조, 제208조의2, "
                 "법인세법 제116조, 제75조의5, 국세기본법 제85조의3",
        "links": [("소득세법", 160, 2), ("소득세법", 81, 0), ("소득세법", 81, 6),
                  ("소득세법 시행령", 132, 0), ("소득세법 시행령", 208, 2),
                  ("법인세법", 116, 0), ("법인세법", 75, 5), ("국세기본법", 85, 3)],
        "remaining": "소규모사업자 범위(가산세 제외, 시행령) 일부만 확인",
    },
    "G7": {
        "title": "경비·손금 인정 요건",
        "info": "개인사업자의 필요경비와 법인의 손금은 사업과 관련해 생긴 비용으로서 일반적으로 인정되는 "
                "통상적인 것이어야 해요. 집안 살림에 쓴 비용이나 업무와 관계없는 비용은 인정되지 않을 수 있어요.",
        "basis": "소득세법 제27조, 제33조, 소득세법 시행령 제78조, 법인세법 제19조",
        "links": [("소득세법", 27, 0), ("소득세법", 33, 0), ("소득세법 시행령", 78, 0), ("법인세법", 19, 0)],
        "remaining": "개인 가사경비 범위(시행령), 법인 업무무관비용(법인세법 제27조)",
    },
    "G8": {
        "title": "기업업무추진비(접대비)",
        "info": "기업업무추진비(예전 이름 접대비)는 정해진 한도 안에서만 손금·필요경비로 인정되고, "
                "한 번에 일정 금액을 넘게 쓴 경우에는 신용카드 매출전표 같은 증빙이 있어야 해요. "
                "한도와 기준 금액은 " + NUMBER_SLOT,
        "basis": "법인세법 제25조, 법인세법 시행령 제41조, 소득세법 제35조",
        "links": [("법인세법", 25, 0), ("법인세법 시행령", 41, 0), ("소득세법", 35, 0)],
        "remaining": "중소기업 판정 기준(조세특례제한법 제6조 제1항 인용)",
    },
    "G15": {
        "title": "신고 때 필요한 장부 관련 서류",
        "info": "복식부기의무자와 법인은 신고할 때 재무상태표·손익계산서와 그 부속서류, 세무조정계산서 등을 "
                "함께 내야 해요. 회사는 상법에 따라 결산 때 재무제표를 작성해요.",
        "basis": "소득세법 제70조 제4·6항, 법인세법 제60조 제2·9항, 상법 제447조, 상법 시행령 제16조",
        "links": [("소득세법", 70, 0), ("법인세법", 60, 0), ("상법", 447, 0), ("상법 시행령", 16, 0)],
        "remaining": "조정반 작성 대상(시행령), 회계기준 종류",
    },
}
VAT_TOPICS = ("G5", "G9", "G10", "G11")
TOPIC_HINTS = (("기장세액공제", "G2"), ("복식부기", "G2"), ("접대", "G8"), ("기업업무추진비", "G8"),
               ("증빙", "G6"), ("영수증", "G6"), ("경비", "G7"), ("손금", "G7"), ("법인세", "G4"),
               ("종합소득세", "G3"), ("종소세", "G3"), ("서류", "G15"), ("장부", "G1"), ("공제", "G2"))

BUSINESS_REG_RE = re.compile(r"^\d{3}[\s\-\.]\d{2}[\s\-\.]\d{5}$")
SENSITIVE_CHUNK_PATTERNS = frozenset(
    ((4, 4, 4, 4), (4, 6, 5), (4, 4, 4, 3), (3, 3, 6), (3, 2, 6))
)
PHONE_LIKE_RE = re.compile(r"^0\d{9,10}$")


def phone_digits_credible(digits):
    if not PHONE_LIKE_RE.match(digits):
        return False
    if len(digits) >= 3 and digits[:3] in ("010", "011", "016", "017", "018", "019"):
        return True
    if len(digits) >= 2 and digits[:2] in PHONE_AREA2:
        return True
    return False

PHONE_AREA2 = frozenset(("02", "31", "32", "33", "41", "42", "43", "44", "51", "52", "53", "54", "55", "61", "62", "63", "64"))
AMOUNT_RE = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)$")
DATE_RE = re.compile(r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class KoreanArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        print("입력 오류: 명령 형식이 맞지 않아요. 「python3 ledger_calc.py -h」로 사용법을 확인해 주세요.")
        emit_json({"status": "input_error", "exit_code": 2, "notice": NOTICE})
        sys.exit(2)


def emit_json(obj):
    print(json.dumps(obj, ensure_ascii=False, sort_keys=True))


def finish(status, code, extra=None):
    obj = {"status": status, "exit_code": code, "notice": NOTICE}
    if extra:
        obj.update(extra)
    emit_json(obj)
    return code


def self_sha256():
    with open(os.path.abspath(__file__), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def normalize_user_text(text):
    return unicodedata.normalize("NFKC", text or "")


def is_text_letter(ch):
    o = ord(ch)
    if 0x41 <= o <= 0x5A or 0x61 <= o <= 0x7A:
        return True
    if 0xAC00 <= o <= 0xD7A3:
        return True
    return False


def is_text_separator(ch):
    return not ch.isdigit() and not is_text_letter(ch)


def is_separator_whitespace(ch):
    if ch in " \t\u00a0":
        return True
    return unicodedata.category(ch) == "Zs" and ch not in "\n\r"


def consume_separator_run(text, pos, end):
    """공백류와 비공백 구분이 임의 순으로 섞인 연속(비공백 구분만 세며 최대 3)."""
    if pos >= end:
        return None
    start = pos
    nws = 0
    moved = False
    while pos < end:
        ch = text[pos]
        if is_separator_whitespace(ch):
            pos += 1
            moved = True
            continue
        if is_text_separator(ch) and ch not in "\n\r":
            nws += 1
            if nws > 3:
                return None
            pos += 1
            moved = True
            continue
        break
    if not moved or pos <= start:
        return None
    return pos


def build_nfkc_mapping(text):
    text = text or ""
    norm_chars = []
    norm_to_orig = []
    for i, ch in enumerate(text):
        for nc in unicodedata.normalize("NFKC", ch):
            norm_chars.append(nc)
            norm_to_orig.append(i)
    return "".join(norm_chars), norm_to_orig


def try_comma_amount_end(text, start, end):
    pos = start
    first_len = 0
    while pos < end and text[pos].isdigit():
        first_len += 1
        pos += 1
        if first_len > 3:
            return None
    if first_len < 1 or pos >= end or text[pos] != ",":
        return None
    pos += 1
    groups = 0
    while pos < end:
        if pos + 3 > end or not text[pos:pos + 3].isdigit():
            return None
        groups += 1
        pos += 3
        if pos < end and text[pos] == ",":
            pos += 1
        else:
            break
    if groups < 1:
        return None
    return pos


def segment_has_comma_amount(text, start, end):
    i = start
    while i < end:
        token_end = try_comma_amount_end(text, i, end)
        if token_end is not None:
            if i > start and text[i - 1].isdigit():
                i += 1
                continue
            if token_end < end and text[token_end].isdigit():
                i += 1
                continue
            return True
        i += 1
    return False


def segment_has_protected_amount_like_token(text, start, end):
    return segment_has_comma_amount(text, start, end)


def is_complete_date_prefix(chunks, digits):
    if len(chunks) < 3 or chunks[0] != 4 or chunks[1] not in (1, 2) or chunks[2] not in (1, 2):
        return False
    if len(digits) < 8:
        return False
    head = digits[:8]
    try:
        y = int(head[0:4])
        if y < 1900 or y > 2100:
            return False
        datetime.date(y, int(head[4:6]), int(head[6:8]))
    except ValueError:
        return False
    return True


def iter_connected_digit_sequences(text):
    """숫자 덩어리와 구분 연속(공백 포함)으로 이어진 한 run 을 찾아요."""
    n = len(text)
    i = 0
    while i < n:
        if not text[i].isdigit():
            i += 1
            continue
        start = i
        chunks = []
        pos = i
        while True:
            if pos >= n or not text[pos].isdigit():
                break
            d0 = pos
            while pos < n and text[pos].isdigit():
                pos += 1
            clen = pos - d0
            chunks.append(clen)
            if pos >= n:
                break
            nxt = consume_separator_run(text, pos, n)
            if nxt is None:
                break
            pos = nxt
            if pos >= n or not text[pos].isdigit():
                break
        end = pos
        digits = "".join(c for c in text[start:end] if c.isdigit())
        yield start, end, tuple(chunks), digits
        i = end if end > start else start + 1


def sequence_separator_runs(text, start, end, chunks):
    if len(chunks) < 2:
        return []
    runs = []
    pos = start
    for idx, clen in enumerate(chunks):
        pos += clen
        if idx + 1 >= len(chunks):
            break
        sep0 = pos
        nxt = consume_separator_run(text, pos, end)
        if nxt is None:
            runs.append(text[sep0:pos])
            break
        runs.append(text[sep0:nxt])
        pos = nxt
    return runs


def is_rrn_digit_pattern(chunks, digits):
    if len(chunks) == 2 and chunks[0] == 6 and chunks[1] == 7:
        return looks_like_yymmdd(digits[:6]) and digits[6] in "12345678"
    if len(chunks) == 1 and len(digits) == 13:
        return looks_like_yymmdd(digits[:6]) and digits[6] in "12345678"
    return False


def is_date_digit_sequence(chunks, digits):
    if len(chunks) != 3 or chunks[0] != 4 or len(digits) != 8:
        return False
    if chunks[1] not in (1, 2) or chunks[2] not in (1, 2):
        return False
    try:
        y = int(digits[0:4])
        if y < 1900 or y > 2100:
            return False
        datetime.date(y, int(digits[4:6]), int(digits[6:8]))
        return True
    except ValueError:
        return False


def is_business_digit_sequence(chunks):
    return chunks == (3, 2, 5)


def is_comma_grouped_amount(chunks, sep_runs):
    if len(chunks) < 2 or chunks[0] < 1 or chunks[0] > 3:
        return False
    if not all(c == 3 for c in chunks[1:]):
        return False
    for run in sep_runs:
        if not run or not any(ch == "," for ch in run):
            return False
        if not all(ch in ", \u00a0" for ch in run):
            return False
    return True


def is_clock_or_ratio_sequence(chunks, digits):
    if len(chunks) == 2 and chunks == (2, 2) and len(digits) == 4:
        return True
    if len(chunks) == 3 and chunks == (2, 2, 2) and len(digits) == 6:
        return True
    return False


def is_comma_separated_card(chunks, sep_runs):
    if len(chunks) != 4 or not all(c == 4 for c in chunks):
        return False
    for run in sep_runs:
        if not run or not all(ch in ", \u00a0" for ch in run):
            return False
        if not any(ch == "," for ch in run):
            return False
    return True


def is_account_comma_digit_pattern(chunks, sep_runs):
    """쉼표로 이은 3-3-6(+) 계좌 꼴은 쉼표 금액 예외로 보지 않아요."""
    if len(chunks) < 3 or chunks[0] != 3 or chunks[1] != 3:
        return False
    if chunks[2] < 6:
        return False
    if len(sep_runs) < 2:
        return False
    for run in sep_runs[:2]:
        if not run or not any(ch == "," for ch in run):
            return False
    return True


def is_card_four_chunk_pattern(chunks, start=0):
    if start + 3 > len(chunks):
        return False
    if all(chunks[start + k] == 4 for k in range(3)):
        return True
    if start + 4 <= len(chunks) and all(chunks[start + k] == 4 for k in range(4)):
        return True
    return False


def has_unit_suffix_immediately(text, pos, end):
    """숫자 덩어리 바로 뒤 한글 단위·% 등(구분 연속 없이)."""
    if pos >= end:
        return False
    ch = text[pos]
    if ch == "%":
        return True
    if is_text_letter(ch):
        return True
    return False


def digit_substring(chunks, digits, i, j):
    off = sum(chunks[:i])
    return digits[off:off + sum(chunks[i:j])]


def chunk_char_range(text, start, end, chunks, idx):
    pos = start
    for k, clen in enumerate(chunks):
        c0, c1 = pos, pos + clen
        if k == idx:
            return c0, c1
        pos = c1
        if k + 1 >= len(chunks):
            break
        nxt = consume_separator_run(text, pos, end)
        if nxt is None:
            break
        pos = nxt
    return start, start


def consume_unit_suffix_end(text, pos, end):
    if pos >= end:
        return pos
    if text[pos] == "%":
        return pos + 1
    if not is_text_letter(text[pos]):
        return pos
    p = pos
    while p < end and is_text_letter(text[p]):
        p += 1
    return p


def chunk_index_at_char(text, start, end, chunks, char_pos):
    for idx in range(len(chunks)):
        c0, c1 = chunk_char_range(text, start, end, chunks, idx)
        if c0 <= char_pos < c1:
            return idx
        if char_pos < c0:
            return idx
    return len(chunks)


def strict_exception_char_end(text, start, end, chunks, digits, idx):
    """규칙 3: 자기 완결 예외만(날짜·쉼표금액·단위·전화·사업자)."""
    n = len(chunks)
    text_end = len(text)
    if idx >= n:
        return None
    sub_c = chunks[idx:]
    sub_d = digit_substring(chunks, digits, idx, n)
    if n == 2 and idx == 0 and is_clock_or_ratio_sequence(chunks, digits):
        _, e = chunk_char_range(text, start, end, chunks, 1)
        return e
    if n == 3 and idx == 0 and is_clock_or_ratio_sequence(chunks, digits):
        _, e = chunk_char_range(text, start, end, chunks, 2)
        return e
    if sub_c[0] == 8 and len(sub_d) >= 8 and idx == 0:
        if idx + 1 < n and chunks[idx + 1] >= 4:
            pass
        else:
            try:
                datetime.date(int(sub_d[0:4]), int(sub_d[4:6]), int(sub_d[6:8]))
            except ValueError:
                pass
            else:
                _, c1 = chunk_char_range(text, start, end, chunks, idx)
                return c1
    if idx + 3 <= n and is_date_digit_sequence(sub_c[:3], sub_d[:8]):
        if is_card_four_chunk_pattern(chunks, idx):
            pass
        else:
            _, e = chunk_char_range(text, start, end, chunks, idx + 2)
            return e
    if idx + 3 <= n and is_business_digit_sequence(sub_c[:3]):
        _, e = chunk_char_range(text, start, end, chunks, idx + 2)
        return e
    if idx + 3 <= n and chunks[idx] == 3 and chunks[idx + 1] == 4 and chunks[idx + 2] == 4:
        sub_d3 = digit_substring(chunks, digits, idx, idx + 3)
        if PHONE_LIKE_RE.match(sub_d3) and idx + 3 >= n:
            _, e = chunk_char_range(text, start, end, chunks, idx + 2)
            return e
    if idx + 2 < n and chunks[idx + 1] == 4 and chunks[idx + 2] == 4 and chunks[idx] in (2, 3):
        sub_d3 = digit_substring(chunks, digits, idx, idx + 3)
        if len(sub_d3) >= 2 and sub_d3[:2] in PHONE_AREA2 and PHONE_LIKE_RE.match(sub_d3) and idx + 3 >= n:
            _, e = chunk_char_range(text, start, end, chunks, idx + 2)
            return e
    if idx + 2 < n and sub_c[0] == 3 and sub_c[1] == 4 and PHONE_LIKE_RE.match(sub_d[:7]) and idx + 2 >= n:
        _, e = chunk_char_range(text, start, end, chunks, idx + 1)
        return e
    c0, c1 = chunk_char_range(text, start, end, chunks, idx)
    ce = try_comma_amount_end(text, c0, text_end)
    if ce is not None:
        if c0 > 0 and text[c0 - 1].isdigit():
            ce = None
        elif ce < text_end and text[ce].isdigit():
            ce = None
        else:
            sep_runs = sequence_separator_runs(text, start, end, chunks)
            if is_account_comma_digit_pattern(chunks, sep_runs):
                ce = None
            elif ce < end and any(chunks[k] >= 5 for k in range(chunk_index_at_char(text, start, end, chunks, ce), n)):
                ce = None
            else:
                return ce
    if has_unit_suffix_immediately(text, c1, text_end):
        return consume_unit_suffix_end(text, c1, text_end)
    return None


def proposed_exception_ranges(text, start, end, chunks, digits):
    n = len(chunks)
    ranges = []
    i = 0
    while i < n:
        ex_end = strict_exception_char_end(text, start, end, chunks, digits, i)
        if ex_end is not None:
            j = chunk_index_at_char(text, start, end, chunks, ex_end - 1)
            if j >= n:
                j = n - 1
            ranges.append((i, j))
            i = j + 1
        else:
            i += 1
    return ranges


def non_keep_group_needs_mask(chunks, lo, hi):
    if lo > hi:
        return False
    if any(chunks[k] >= 5 for k in range(lo, hi + 1)):
        return True
    return sum(chunks[k] for k in range(lo, hi + 1)) >= 9


def is_standalone_date_chunk_range(chunks, digits, i, j):
    if j == i and chunks[i] == 8:
        sub_d = digit_substring(chunks, digits, i, i + 1)
        try:
            datetime.date(int(sub_d[0:4]), int(sub_d[4:6]), int(sub_d[6:8]))
            return True
        except ValueError:
            return False
    if j == i + 2 and i + 3 <= len(chunks):
        sub_c = chunks[i:i + 3]
        sub_d = digit_substring(chunks, digits, i, i + 3)
        return is_date_digit_sequence(sub_c, sub_d)
    return False


def finalize_keep_chunks(n, chunks, props, text, start, end, digits):
    keep = [False] * n

    def covered(k):
        return any(a <= k <= b for a, b in props)

    for i, j in props:
        ok = True
        standalone_date = is_standalone_date_chunk_range(chunks, digits, i, j)
        if i > 0 and not covered(i - 1) and not standalone_date:
            if chunks[i - 1] >= 5 or non_keep_group_needs_mask(chunks, i - 1, i - 1):
                ok = False
            else:
                lo = i - 1
                while lo > 0 and not covered(lo - 1):
                    lo -= 1
                if non_keep_group_needs_mask(chunks, lo, i - 1):
                    ok = False
        if j + 1 < n and not covered(j + 1):
            ok_before_right = ok
            if chunks[j + 1] >= 5:
                ok = False
                if standalone_date and ok_before_right:
                    for k in range(i, j + 1):
                        keep[k] = True
            else:
                hi = j + 1
                while hi + 1 < n and not covered(hi + 1):
                    hi += 1
                if non_keep_group_needs_mask(chunks, j + 1, hi):
                    ok = False
        if ok:
            for k in range(i, j + 1):
                keep[k] = True
    return keep


def run_is_date_plus_short_plain_amount(text, start, end, chunks, digits):
    """날짜 뒤 쉼표 없는 짧은 금액(번호 꼴·9자리 이상 덩어리 제외)만 있을 때 run 전체 유지."""
    n = len(chunks)
    if n < 4 or not is_date_digit_sequence(chunks[:3], digits[:8]):
        return False
    rest = chunks[3:]
    rest_d = digits[8:]
    if is_card_four_chunk_pattern(chunks, 3):
        return False
    if len(rest) >= 4 and all(c == 4 for c in rest[:4]):
        return False
    if tuple(rest) in SENSITIVE_CHUNK_PATTERNS:
        return False
    if len(rest) == 1 and len(rest_d) >= 10:
        return False
    if len(rest) == 1 and rest[0] >= 5:
        last_c0, last_c1 = chunk_char_range(text, start, end, chunks, n - 1)
        if has_unit_suffix_immediately(text, last_c1, len(text)):
            return True
        return False
    if len(rest) >= 2 and sum(rest) >= 9:
        return False
    if len(rest) >= 2 and any(c >= 5 for c in rest):
        return False
    return True


def run_is_only_comma_amount(text, start, end, chunks, digits):
    """connected run 전체가 쉼표 금액 하나뿐일 때."""
    n = len(chunks)
    if n < 2:
        return False
    c0, _ = chunk_char_range(text, start, end, chunks, 0)
    ce = try_comma_amount_end(text, c0, end)
    if ce is None:
        return False
    if c0 > start and text[c0 - 1].isdigit():
        return False
    if ce < end and text[ce].isdigit():
        return False
    sep_runs = sequence_separator_runs(text, start, end, chunks)
    if is_account_comma_digit_pattern(chunks, sep_runs):
        return False
    last_idx = chunk_index_at_char(text, start, end, chunks, ce - 1)
    return last_idx >= n - 1


def run_is_only_dates(chunks, digits):
    """run 안이 합법 날짜(4-2-2 또는 8자리)만 반복일 때."""
    n = len(chunks)
    i = 0
    while i < n:
        if i + 3 <= n and is_date_digit_sequence(chunks[i:i + 3], digit_substring(chunks, digits, i, i + 3)):
            i += 3
            continue
        if i < n and chunks[i] == 8:
            sub_d = digit_substring(chunks, digits, i, i + 1)
            if len(sub_d) == 8:
                try:
                    y = int(sub_d[0:4])
                    if 1900 <= y <= 2100:
                        datetime.date(y, int(sub_d[4:6]), int(sub_d[6:8]))
                        i += 1
                        continue
                except ValueError:
                    pass
        return False
    return i == n and n > 0


def run_is_standalone_business_reg(text, start, end, chunks, digits):
    if chunks != (3, 2, 5) or len(digits) != 10:
        return False
    ok_sep = set("-–—\u2010\u2212\u3161\u1173.\u00b7 \u00a0")
    for run in sequence_separator_runs(text, start, end, chunks):
        if not run:
            return False
        if any(ch in ",;" for ch in run):
            return False
        if not all(ch in ok_sep for ch in run):
            return False
    return True


def run_is_phone_entire_run(chunks, digits, n):
    if n == 3 and chunks[0] == 3 and chunks[1] == 4 and chunks[2] == 4:
        if digits[:3] not in ("010", "011", "016", "017", "018", "019"):
            return False
        return phone_digits_credible(digits)
    if n == 3 and chunks == (2, 4, 4) and digits[:2] == "02":
        return phone_digits_credible(digits)
    if n == 2 and chunks[0] == 3 and chunks[1] == 4:
        return phone_digits_credible(digits[:7])
    return False


def run_is_two_comma_amounts(text, start, end, chunks, digits):
    """쉼표 금액 ~ 쉼표 금액 처럼 금액 두 덩어리만 있는 run."""
    c0, _ = chunk_char_range(text, start, end, chunks, 0)
    ce1 = try_comma_amount_end(text, c0, end)
    if ce1 is None:
        return False
    pos = ce1
    while pos < end and not text[pos].isdigit():
        ch = text[pos]
        if ch in ", \u00a0":
            pos += 1
            continue
        if is_text_separator(ch) or ch in "~\u2013\u2014\u2212\u2010\u2011\u2012\u2015\uff0d":
            pos += 1
            continue
        return False
    if pos >= end:
        return False
    ce2 = try_comma_amount_end(text, pos, end)
    if ce2 is None or ce2 < end:
        return False
    if pos > c0 and text[pos - 1].isdigit():
        return False
    return True


def run_is_standalone_keep(text, start, end, chunks, digits):
    """이웃 숫자 run 과 합쳐진 connected run 이 아니면, 예외 패턴 하나만일 때만 유지."""
    n = len(chunks)
    total = len(digits)
    text_end = len(text)

    if n == 2 and total == 4 and is_clock_or_ratio_sequence(chunks, digits):
        return True
    if n == 3 and total == 6 and is_clock_or_ratio_sequence(chunks, digits):
        return True

    if n == 1:
        c0, c1 = chunk_char_range(text, start, end, chunks, 0)
        if has_unit_suffix_immediately(text, c1, text_end):
            return True
        if chunks[0] == 8 and total == 8:
            try:
                y = int(digits[0:4])
                if 1900 <= y <= 2100:
                    datetime.date(y, int(digits[4:6]), int(digits[6:8]))
                    return True
            except ValueError:
                pass

    if n == 3 and total == 8 and is_date_digit_sequence(chunks, digits):
        return True

    if run_is_standalone_business_reg(text, start, end, chunks, digits):
        return True

    if run_is_phone_entire_run(chunks, digits, n):
        return True

    if run_is_only_comma_amount(text, start, end, chunks, digits):
        return True

    if run_is_two_comma_amounts(text, start, end, chunks, digits):
        return True

    if run_is_date_plus_short_plain_amount(text, start, end, chunks, digits):
        return True

    if run_is_only_dates(chunks, digits):
        return True

    if run_is_small_counter_sequence(chunks, digits):
        return True

    return False


def run_is_small_counter_sequence(chunks, digits):
    """줄 번호·개수처럼 1~2자리 숫자만 이어진 run (장부 예외)."""
    if not chunks or sum(chunks) >= 9:
        return False
    return all(c <= 2 for c in chunks)


def is_valid_clock_hhmm(chunks, digits, chunk_i):
    """chunk_i, chunk_i+1 이 (2,2) 이고 시:분(00:00~23:59)일 때만."""
    if chunk_i + 1 >= len(chunks):
        return False
    if chunks[chunk_i] != 2 or chunks[chunk_i + 1] != 2:
        return False
    sub = digit_substring(chunks, digits, chunk_i, chunk_i + 2)
    if len(sub) != 4 or not sub.isdigit():
        return False
    hh, mm = int(sub[0:2]), int(sub[2:4])
    return 0 <= hh <= 23 and 0 <= mm <= 59


def is_card_followed_by_clock(chunks, digits, card_start):
    if not is_card_four_chunk_at(chunks, card_start):
        return False
    ci = card_start + 4
    if ci + 1 < len(chunks) and is_valid_clock_hhmm(chunks, digits, ci):
        return True
    if ci + 2 < len(chunks) and chunks[ci] == 2 and chunks[ci + 1] == 2 and chunks[ci + 2] == 2:
        off = sum(chunks[:ci])
        sub = digits[off : off + 6]
        if len(sub) == 6:
            hh, mm, ss = int(sub[0:2]), int(sub[2:4]), int(sub[4:6])
            return 0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59
    return False


def card_clock_tail_chunk_hi(chunks, digits, card_start):
    """카드 직후 시각(hh:mm 또는 hh:mm:ss)의 마지막 chunk 인덱스."""
    ci = card_start + 4
    if ci + 2 < len(chunks) and chunks[ci] == 2 and chunks[ci + 1] == 2 and chunks[ci + 2] == 2:
        off = sum(chunks[:ci])
        sub = digits[off : off + 6]
        if len(sub) == 6:
            hh, mm, ss = int(sub[0:2]), int(sub[2:4]), int(sub[4:6])
            if 0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59:
                return ci + 2
    if ci + 1 < len(chunks) and is_valid_clock_hhmm(chunks, digits, ci):
        return ci + 1
    return None


def _card_immediately_before_clock(chunks, digits, ci_time):
    """(2,2) 시각 바로 앞이 4-4-4-4 카드(짧은 접두·전화 허용)일 때만."""
    cs = ci_time - 4
    if cs < 0 or not is_card_four_chunk_at(chunks, cs):
        return False
    if cs == 0:
        return True
    if sum(chunks[:cs]) <= 2:
        return True
    if cs == 3 and run_is_phone_entire_run(chunks[:3], digits[:11], 3):
        return True
    return False


def is_trailing_card_time_not_calendar(chunks, digits):
    """카드 4-4-4-4 직후 (2,2) 시:분만 달력 꼬리와 구분."""
    n = len(chunks)
    if n < 6 or not is_valid_clock_hhmm(chunks, digits, n - 2):
        return False
    ci_time = n - 2
    if _card_immediately_before_clock(chunks, digits, ci_time):
        return True
    if is_date_digit_sequence(chunks[n - 3 : n], digits[-8:]):
        return False
    return False


def is_trailing_calendar_date(chunks, digits):
    n = len(chunks)
    if n < 3:
        return False
    if is_trailing_card_time_not_calendar(chunks, digits):
        return False
    if not is_date_digit_sequence(chunks[n - 3 : n], digits[-8:]):
        return False
    try:
        y = int(digits[-8:][:4])
    except ValueError:
        return False
    return 2000 <= y <= 2100


def is_card_four_chunk_at(chunks, i):
    if i + 3 >= len(chunks):
        return False
    if not all(chunks[i + k] == 4 for k in range(4)):
        return False
    if i == 1 and len(chunks) == 3 and chunks[0] == 3 and chunks[1] == 4 and chunks[2] == 4:
        return False
    return True


def iter_card_four_chunk_starts(chunks):
    """4-4-4-4 카드 덩어리가 시작하는 모든 오프셋."""
    n = len(chunks)
    for i in range(n):
        if is_card_four_chunk_at(chunks, i):
            yield i


def trim_mask_tail_hi(text, start, end, chunks, digits, lo, tail_hi):
    """끝쪽 쉼표 금액·단위 접미사는 가리지 않아요."""
    n = len(chunks)
    for i in range(lo, n):
        c0, _ = chunk_char_range(text, start, end, chunks, i)
        if try_comma_amount_end(text, c0, end) == end and i > lo:
            if i > 0 and chunks[i - 1] >= 5:
                continue
            tail_hi = min(tail_hi, i - 1)
            break
    while tail_hi > lo:
        c0, c1 = chunk_char_range(text, start, end, chunks, tail_hi)
        if has_unit_suffix_immediately(text, c1, end):
            tail_hi -= 1
            continue
        break
    return tail_hi


def mask_sensitive_tail_hi(chunks, digits, n):
    """가릴 구간 끝: 카드 뒤 시각은 run 밖으로 두고, 달력 꼬리는 유지."""
    if is_trailing_card_time_not_calendar(chunks, digits):
        if n >= 2 and chunks[-2] == 2 and chunks[-1] == 2:
            return n - 3
    if n >= 3 and is_trailing_calendar_date(chunks, digits):
        return n - 4
    return n - 1


def iter_mask_spans_in_run(text, start, end, chunks, digits):
    """9자리 이상 connected run: run 전체에서 끝 4자리만 남기고 가려요(단독 예외 run 제외)."""
    n = len(chunks)
    if run_is_standalone_keep(text, start, end, chunks, digits):
        return
    needs = any(c >= 5 for c in chunks) or len(digits) >= 9
    if not needs:
        return

    lo = 0
    if n >= 4 and is_date_digit_sequence(chunks[:3], digits[:8]):
        if run_is_date_plus_short_plain_amount(text, start, end, chunks, digits):
            return
        lo = 3

    tail_hi = mask_sensitive_tail_hi(chunks, digits, n)
    tail_hi = trim_mask_tail_hi(text, start, end, chunks, digits, lo, tail_hi)
    if tail_hi < lo:
        return

    if lo == 0:
        for ci in range(1, n):
            if sum(chunks[:ci]) > 2:
                break
            if is_card_four_chunk_at(chunks, ci):
                lo = ci
                break

    rest_has_card = any(is_card_four_chunk_at(chunks, ci) for ci in range(3, n))
    apply_phone = (
        n >= 6
        and run_is_phone_entire_run(chunks[:3], digits[:11], 3)
        and (not any(chunks[k] >= 4 for k in range(3, n)) or rest_has_card)
    )
    if apply_phone:
        ps0, _ = chunk_char_range(text, start, end, chunks, 0)
        _, ps1 = chunk_char_range(text, start, end, chunks, 2)
        yield ps0, ps1, "last4"
        lo = max(lo, 3)
        phone_masked = True
    else:
        phone_masked = False

    if is_trailing_card_time_not_calendar(chunks, digits):
        card_tail = n - 3
        card_tail = trim_mask_tail_hi(text, start, end, chunks, digits, lo, card_tail)
        if card_tail >= lo:
            short_pre = lo > 0 and sum(chunks[:lo]) <= 2
            if phone_masked and lo >= 3:
                card_mode = "last4"
            elif short_pre:
                card_mode = "last4"
            else:
                card_mode = "all"
            s0, _ = chunk_char_range(text, start, end, chunks, lo)
            _, s1 = chunk_char_range(text, start, end, chunks, card_tail)
            yield s0, s1, card_mode
        card_start = None
        for ci in range(lo, n):
            if is_card_four_chunk_at(chunks, ci):
                card_start = ci
                break
        if card_start is not None:
            ci_time = card_start + 4
            if (
                ci_time + 2 < n
                and chunks[ci_time] == 2
                and chunks[ci_time + 1] == 2
                and chunks[ci_time + 2] == 2
                and ci_time + 3 >= n
            ):
                ts0, _ = chunk_char_range(text, start, end, chunks, ci_time)
                _, ts1 = chunk_char_range(text, start, end, chunks, ci_time + 2)
                yield ts0, ts1, "clock_head"
            elif ci_time + 1 < len(chunks) and is_valid_clock_hhmm(chunks, digits, ci_time):
                t_end = ci_time + 1
                tilde_range = False
                if t_end + 1 < len(chunks):
                    _, c5_end = chunk_char_range(text, start, end, chunks, t_end)
                    c6_start, _ = chunk_char_range(text, start, end, chunks, t_end + 1)
                    sep = text[c5_end:c6_start]
                    tilde_range = "~" in sep or "～" in sep
                if tilde_range:
                    ts0, _ = chunk_char_range(text, start, end, chunks, ci_time)
                    _, ts1 = chunk_char_range(text, start, end, chunks, t_end)
                    yield ts0, ts1, "clock_head_four"
        return

    s0, _ = chunk_char_range(text, start, end, chunks, lo)
    _, s1 = chunk_char_range(text, start, end, chunks, tail_hi)
    yield s0, s1, "last4"


def rrn_chunk_span_is_credible(chunks, digits, i, j):
    """긴 계좌 run 안의 (6,7) 우연 일치는 제외."""
    sub_c = chunks[i:j]
    if len(sub_c) == 1 and sub_c[0] == 13:
        return i == 0
    if len(sub_c) != 2 or sub_c != (6, 7):
        return False
    if i == 0:
        return True
    if i >= 3 and run_is_phone_entire_run(chunks[:i], digits[: sum(chunks[:i])], i):
        return True
    sub_d = digit_substring(chunks, digits, i, j)
    if i >= 2 and all(chunks[k] <= 2 for k in range(i)) and is_rrn_digit_pattern(sub_c, sub_d):
        return True
    if i >= 1 and chunks[i - 1] in (5, 6, 7, 8):
        return True
    if i >= 1 and chunks[i - 1] < 6 and len(chunks) >= 3 and sum(chunks) >= 10:
        return False
    if i >= 1 and chunks[i - 1] >= 6 and chunks[i - 1] != 7:
        return False
    if sum(chunks[:i]) > 10:
        return False
    return True


def iter_rrn_chunk_spans(chunks, digits, for_row=False):
    n = len(chunks)
    for i in range(n):
        for j in range(i + 1, n + 1):
            sub_c = chunks[i:j]
            sub_d = digit_substring(chunks, digits, i, j)
            if not is_rrn_digit_pattern(sub_c, sub_d):
                continue
            if for_row or rrn_chunk_span_is_credible(chunks, digits, i, j):
                yield i, j


def connected_run_should_skip_mask(chunks, digits):
    """주민등록번호가 run 안에 있으면 부분 가림하지 않아요(행 제외는 row_contains_rrn)."""
    for i, j in iter_rrn_chunk_spans(chunks, digits):
        if rrn_chunk_span_is_credible(chunks, digits, i, j):
            return True
    return False


def mask_spans_for_text(norm):
    spans = []
    for start, end, chunks, digits in iter_connected_digit_sequences(norm):
        if connected_run_should_skip_mask(chunks, digits):
            continue
        for item in iter_mask_spans_in_run(norm, start, end, chunks, digits):
            spans.append(item)
    return spans


def mask_digits_in_token(token, mode="last4"):
    if mode == "all":
        return "".join("*" if c.isdigit() else c for c in token)
    if mode == "clock_head":
        seen = 0
        out = []
        for c in token:
            if c.isdigit():
                seen += 1
                out.append("*" if seen <= 2 else c)
            else:
                out.append(c)
        return "".join(out)
    if mode == "clock_head_four":
        seen = 0
        out = []
        for c in token:
            if c.isdigit():
                seen += 1
                out.append("*" if seen <= 4 else c)
            else:
                out.append(c)
        return "".join(out)
    out = []
    seen = 0
    for c in reversed(token):
        if c.isdigit():
            seen += 1
            out.append(c if seen <= 4 else "*")
        else:
            out.append(c)
    return "".join(reversed(out))


def mask_text(text):
    """카드·계좌번호 등: span 합 9자리 이상이면 끝 4자리만 남기고 가려요."""
    original = text or ""
    norm, norm_to_orig = build_nfkc_mapping(original)
    out = list(original)
    for start, end, mode in reversed(mask_spans_for_text(norm)):
        orig_indices = {norm_to_orig[ni] for ni in range(start, end)}
        o_start = min(orig_indices)
        o_end = max(orig_indices) + 1
        masked = mask_digits_in_token(original[o_start:o_end], mode=mode)
        for j, ch in enumerate(masked):
            out[o_start + j] = ch
    return "".join(out)


def parse_amount(raw):
    """("empty"|"ok"|"invalid", 정수) 를 돌려줘요. 읽을 수 없는 값은 추측하지 않아요."""
    s = raw.strip()
    if s.endswith("원"):
        s = s[:-1].strip()
    if s == "":
        return "empty", 0
    if not AMOUNT_RE.match(s):
        return "invalid", 0
    digits = s.replace(",", "")
    if len(digits) >= 13:
        return "invalid", 0
    return "ok", int(digits)


def parse_date(raw):
    m = DATE_RE.match(raw.strip())
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def has_any(text, words):
    return any(w in text for w in words)


def is_other_business_request(text):
    """남의 장부를 대신 해 달라는 뜻일 때만 거절(낱말만으로는 거절하지 않아요)."""
    text = normalize_user_text(text)
    if not text or not text.strip():
        return False
    if has_any(text, OTHER_BUSINESS_PHRASES):
        return True
    if "위임받" in text:
        return True
    if re.search(r"(?:대리|대행)(?:로|으로)?\s*(?:장부|정리|작성|만들)", text):
        return True
    if re.search(r"대신\s*(?:만들|정리|작성|해)", text):
        return True
    if re.search(r"(?:남의|타인|다른\s*사람)\s*(?:회사|가게|사업장|장부)", text):
        return True
    if re.search(r"(?:친구|지인|동생|가족|형|남편|아내)\s*(?:회사|가게|사업장|장부)", text):
        if "우리" not in text and "본인" not in text and "제 회사" not in text:
            return True
    if "클라이언트" in text and ("회사" in text or "장부" in text):
        return True
    return False


def is_personal_question(text):
    if has_any(text, PERSONAL_WORDS):
        return True
    if re.search(r"(경비\s*처리|손금)", text) and re.search(r"(되나요|돼요|되나|돼)", text):
        return True
    if re.search(r"(간편장부|복식부기)", text) and re.search(r"(대상|해야|대상자)", text):
        return True
    if "환급" in text and re.search(r"(받을\s*수\s*있|받을수있|받을\s*수\s*있나)", text):
        return True
    if re.search(r"(계산\s*해|계산해|얼마\s*나와|얼마\s*내|얼마\s*받)", text):
        if any(w in text for w in ("세금", "세액", "종소세", "환급", "공제", "기장세액공제", "종소")):
            return True
    if re.search(r"(절세\s*방법|세금\s*줄|줄이는\s*방법)", text):
        return True
    return False


def looks_like_yymmdd(six):
    if len(six) != 6 or not six.isdigit():
        return False
    mm, dd = int(six[2:4]), int(six[4:6])
    return 1 <= mm <= 12 and 1 <= dd <= 31


def row_contains_rrn(row_text):
    row_text, _ = build_nfkc_mapping(row_text)
    for _start, _end, chunks, digits in iter_connected_digit_sequences(row_text):
        for _i, _j in iter_rrn_chunk_spans(chunks, digits, for_row=True):
            return True
    return False


def won(n):
    return "{:,}원".format(n)


def neutralize_csv_cell(cell):
    if cell is None or cell == "":
        return cell
    if not isinstance(cell, str):
        cell = str(cell)
    if cell[0] in ("=", "+", "@"):
        return "'" + cell
    if cell[0] == "-" and re.match(r"^-\d+\s*\+\s*\d", cell):
        return "'" + cell
    return cell


def csv_bytes(rows):
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    for row in rows:
        writer.writerow([neutralize_csv_cell(c) for c in row])
    return buf.getvalue().encode("utf-8-sig")


def read_ledger(path):
    """입력 CSV를 읽어 (오류 문장, 처리 결과) 를 돌려줘요."""
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            text = f.read()
    except FileNotFoundError:
        return "입력 파일을 찾을 수 없어요.", None
    except UnicodeDecodeError:
        return "입력 파일을 utf-8로 읽을 수 없어요. 엑셀에서 「CSV UTF-8」로 저장해 다시 보내 주세요.", None
    except OSError:
        return "입력 파일을 열 수 없어요.", None

    reader = csv.reader(io.StringIO(text, newline=""))
    header = next(reader, None)
    if header is None or [h.strip() for h in header] != INPUT_COLUMNS:
        return "입력 파일 첫 줄(헤더)이 장부 양식과 달라요. 이렇게 맞춰 주세요: " + ",".join(INPUT_COLUMNS), None

    ledger_rows = []
    needs_check = []
    no_evidence = []
    rrn_lines = []
    included = []  # (월, 계정, 계정상태, 들어온돈, 나간돈)
    rows_total = 0

    for row in reader:
        line = reader.line_num
        if all(c.strip() == "" for c in row):
            continue
        rows_total += 1
        if row_contains_rrn("\n".join(row)):
            # 원본 값은 어디에도 옮기지 않고 줄 번호만 남겨요.
            rrn_lines.append(line)
            continue

        issues = []
        excluded = False
        if len(row) != len(INPUT_COLUMNS):
            issues.append("칸 수가 장부 양식과 달라요")
            excluded = True
            row = (row + [""] * len(INPUT_COLUMNS))[:len(INPUT_COLUMNS)]
        raw = dict(zip(INPUT_COLUMNS, row))
        cell = {k: (mask_text(v.strip()) if k in MASK_TEXT_COLUMNS else v.strip()) for k, v in raw.items()}

        date = parse_date(raw["날짜"])
        if date is None:
            issues.append("날짜를 읽을 수 없어요")
            excluded = True
        in_kind, in_val = parse_amount(raw["들어온돈"])
        out_kind, out_val = parse_amount(raw["나간돈"])
        in_disp = str(in_val) if in_kind == "ok" else ("" if in_kind == "empty" else CHECK)
        out_disp = str(out_val) if out_kind == "ok" else ("" if out_kind == "empty" else CHECK)
        if in_kind == "invalid":
            issues.append("들어온 돈 칸을 읽을 수 없어요")
            excluded = True
        if out_kind == "invalid":
            issues.append("나간 돈 칸을 읽을 수 없어요")
            excluded = True
        if in_kind == "empty" and out_kind == "empty":
            issues.append("들어온 돈·나간 돈 칸이 모두 비어 있어요")
            excluded = True
            in_disp = out_disp = CHECK

        evidence = cell["증빙종류"] or "없음"
        if evidence not in EVIDENCE_TYPES:
            issues.append("증빙 종류를 확인해 주세요(세금계산서/카드/현금영수증/간이영수증/없음)")
        account = cell["계정"] or CHECK
        status = "확정" if cell["계정상태"] == "확정" else "제안"

        ledger_rows.append([str(line), date or cell["날짜"] or CHECK, cell["거래처"], cell["내용"],
                            in_disp, out_disp, evidence, account, status, cell["메모"], cell["출처"],
                            "아니요" if excluded else "예"])
        if issues:
            needs_check.append({"line": line, "reason": "; ".join(issues), "excluded_from_totals": excluded})
        if evidence == "없음":
            no_evidence.append({"line": line, "date": date or cell["날짜"] or CHECK, "vendor": cell["거래처"],
                                "description": cell["내용"], "in": in_disp, "out": out_disp})
        if not excluded:
            included.append((date[:7], account, status, in_val, out_val))

    if rows_total == 0:
        return "입력 파일에 장부 줄이 없어요.", None
    return None, {
        "ledger_rows": ledger_rows,
        "needs_check": needs_check,
        "no_evidence": no_evidence,
        "rrn_lines": rrn_lines,
        "included": included,
        "rows_total": rows_total,
    }


def summarize(data):
    months = {}
    accounts = {}
    for month, account, status, in_val, out_val in data["included"]:
        m = months.setdefault(month, [0, 0])
        m[0] += in_val
        m[1] += out_val
        for key in ((month, account, status), ("전체", account, status)):
            a = accounts.setdefault(key, [0, 0])
            a[0] += in_val
            a[1] += out_val
    monthly = []
    cumulative = 0
    for month in sorted(months):
        in_sum, out_sum = months[month]
        net = in_sum - out_sum
        cumulative += net
        monthly.append({"month": month, "in": in_sum, "out": out_sum, "net": net, "cumulative": cumulative})
    keys = sorted(k for k in accounts if k[0] != "전체") + sorted(k for k in accounts if k[0] == "전체")
    subtotals = [{"month": k[0], "account": k[1], "account_status": k[2], "in": accounts[k][0],
                  "out": accounts[k][1]} for k in keys]
    total_in = sum(m["in"] for m in monthly)
    total_out = sum(m["out"] for m in monthly)
    return monthly, subtotals, {"in": total_in, "out": total_out, "net": total_in - total_out}


def build_summary_md(as_of_line, data, monthly, totals):
    lines = [as_of_line, NOTICE, "", "# 내 회사 장부 초안 요약", ""]
    lines.append("- 입력 줄: {}줄 / 장부에 옮긴 줄: {}줄 / 합계에 넣은 줄: {}줄".format(
        data["rows_total"], len(data["ledger_rows"]), len(data["included"])))
    lines += ["", "## 월별 손익·현금 흐름", "",
              "| 월 | 들어온 돈 | 나간 돈 | 순손익(순현금흐름) | 누적 |", "|---|---:|---:|---:|---:|"]
    for m in monthly:
        lines.append("| {} | {} | {} | {} | {} |".format(m["month"], won(m["in"]), won(m["out"]),
                                                        won(m["net"]), won(m["cumulative"])))
    lines.append("| 합계 | {} | {} | {} | |".format(won(totals["in"]), won(totals["out"]), won(totals["net"])))
    lines += ["", "누적은 0에서 시작했어요(시작 잔액은 넣지 않았어요).", ""]

    lines += ["## 세무사에게 물어볼 것 (증빙 없는 거래)", ""]
    if data["no_evidence"]:
        for item in data["no_evidence"]:
            amount = item["out"] or item["in"] or CHECK
            if amount.isdigit():
                amount = won(int(amount))
            lines.append("- {}번째 줄: {} {} {} (금액 {}) — 증빙이 없어요. 어떻게 처리할지 세무사에게 여쭤 보세요.".format(
                item["line"], item["date"], item["vendor"], item["description"], amount))
    else:
        lines.append("- 없어요.")

    lines += ["", "## 확인 필요 목록", ""]
    if data["needs_check"]:
        for item in data["needs_check"]:
            tail = "합계에서 뺐어요. 추측하지 않았어요." if item["excluded_from_totals"] else "합계에는 넣었어요."
            lines.append("- {}번째 줄: {} {} — {}".format(item["line"], CHECK, item["reason"], tail))
    else:
        lines.append("- 없어요.")

    lines += ["", "## 주민번호 때문에 옮기지 않은 줄", ""]
    if data["rrn_lines"]:
        lines.append("- {}: {}".format(RRN_MSG, ", ".join("{}번째 줄".format(n) for n in data["rrn_lines"])))
    else:
        lines.append("- 없어요.")

    lines += ["", "## 알려 드려요", "",
              "- " + BASIS,
              "- 계정의 「확정」은 사용자님이 「맞아요」 하신 것이고, 「제안」은 아직 확인 전이에요.",
              "- 원본 영수증과 장부는 따로 보관해 주세요.",
              "- " + FILING_ANSWER,
              "", DISCLAIMER]
    return ("\n".join(lines) + "\n").encode("utf-8")


def cmd_calc(args):
    if args.own_business != "yes" or is_other_business_request(args.request_text or ""):
        print(REFUSAL)
        return finish("refused", 2)

    my_hash = self_sha256()
    if args.expect_self_sha256 is None or not str(args.expect_self_sha256).strip():
        print("입력 오류: 계산 전에 --expect-self-sha256 으로 기준 해시를 넘겨 주세요.")
        return finish("input_error", 2)
    expect_hash = args.expect_self_sha256.strip().lower()
    if not SHA256_RE.match(expect_hash):
        print("입력 오류: --expect-self-sha256 값이 sha256 꼴이 아니에요.")
        return finish("input_error", 2)
    if expect_hash != my_hash:
        print(HASH_MISMATCH)
        return finish("hash_mismatch", 3)

    if args.as_of is not None:
        if parse_date(args.as_of) != args.as_of:
            print("입력 오류: 기준일은 YYYY-MM-DD 꼴로 적어 주세요.")
            return finish("input_error", 2)
        as_of_line = "기준일 " + args.as_of
    else:
        as_of_line = "기준일 " + CHECK

    out_dir = args.out
    if os.path.islink(out_dir):
        print("입력 오류: 출력 폴더가 바로가기(심볼릭 링크)여서 쓰지 않았어요.")
        return finish("input_error", 2)
    if os.path.exists(out_dir) and not os.path.isdir(out_dir):
        print("입력 오류: 출력 위치가 폴더가 아니에요.")
        return finish("input_error", 2)
    existing = [n for n in OUTPUT_FILES if os.path.lexists(os.path.join(out_dir, n))]
    if existing:
        print("입력 오류: 이미 있는 파일은 덮어쓰지 않아요. 새 출력 폴더를 정해 주세요: " + ", ".join(existing))
        return finish("input_error", 2)

    error, data = read_ledger(args.input)
    if error:
        print("입력 오류: " + error)
        return finish("input_error", 2)

    monthly, subtotals, totals = summarize(data)
    code = 10 if (data["needs_check"] or data["rrn_lines"]) else 0
    status = "ok_with_checks" if code == 10 else "ok"

    ledger = [[NOTICE], LEDGER_COLUMNS] + data["ledger_rows"]
    pnl = [[NOTICE], ["월", "들어온돈", "나간돈", "순손익"]]
    pnl += [[m["month"], m["in"], m["out"], m["net"]] for m in monthly]
    pnl.append(["합계", totals["in"], totals["out"], totals["net"]])
    pnl += [[], ["계정별 소계 (확정=사용자 확인, 제안=확인 전)"], ["월", "계정", "계정상태", "들어온돈", "나간돈"]]
    pnl += [[s["month"], s["account"], s["account_status"], s["in"], s["out"]] for s in subtotals]
    cash = [[NOTICE], ["월", "들어온돈", "나간돈", "순현금흐름", "누적"]]
    cash += [[m["month"], m["in"], m["out"], m["net"], m["cumulative"]] for m in monthly]
    cash.append(["합계", totals["in"], totals["out"], totals["net"], ""])
    cash.append(["누적은 0에서 시작했어요(시작 잔액은 넣지 않았어요)."])

    result = {
        "notice": NOTICE,
        "as_of": args.as_of if args.as_of is not None else CHECK,
        "status": status,
        "exit_code": code,
        "basis": BASIS,
        "disclaimer": DISCLAIMER,
        "program_sha256": my_hash,
        "totals": totals,
        "monthly": monthly,
        "account_subtotals": subtotals,
        "rows_total": data["rows_total"],
        "rows_in_ledger": len(data["ledger_rows"]),
        "rows_in_totals": len(data["included"]),
        "no_evidence_ask_tax_advisor": data["no_evidence"],
        "needs_check": data["needs_check"],
        "rrn_excluded_lines": data["rrn_lines"],
        "rrn_message": RRN_MSG if data["rrn_lines"] else "",
        "files": OUTPUT_FILES,
    }
    contents = {
        LEDGER_FILE: csv_bytes(ledger),
        PNL_FILE: csv_bytes(pnl),
        CASHFLOW_FILE: csv_bytes(cash),
        SUMMARY_FILE: build_summary_md(as_of_line, data, monthly, totals),
        RESULT_FILE: (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"),
    }

    try:
        os.makedirs(out_dir, exist_ok=True)
        for name in OUTPUT_FILES:
            with open(os.path.join(out_dir, name), "xb") as f:
                f.write(contents[name])
    except OSError:
        print("입력 오류: 출력 파일을 만들 수 없어요.")
        return finish("input_error", 2)

    print(NOTICE)
    print("장부 초안을 만들었어요. 장부에 옮긴 줄 {}줄, 합계에 넣은 줄 {}줄이에요.".format(
        len(data["ledger_rows"]), len(data["included"])))
    if code == 10:
        print("확인 필요 {}줄, 주민번호 때문에 옮기지 않은 줄 {}줄이 있어요. 요약 파일을 봐 주세요.".format(
            len(data["needs_check"]), len(data["rrn_lines"])))
    print("만든 파일: " + ", ".join(OUTPUT_FILES))
    return finish(status, code)


def law_url(law_name, jo, branch):
    encoded = "".join(c if c.isascii() and c.isalnum() else "".join("%{:02X}".format(b) for b in c.encode("utf-8"))
                      for c in law_name)
    return "https://www.law.go.kr/lsLinkProc.do?mode=10&lsNm={}&joNo={:04d}{:02d}000".format(encoded, jo, branch)


def topic_lines(topic_id):
    t = TOPICS[topic_id]
    urls = []
    for law_name, jo, branch in t["links"]:
        url = law_url(law_name, jo, branch)
        if url not in urls:
            urls.append(url)
    return [
        "[{} {}] 일반 정보: {} — 근거 조문: {} — 적용 기간·시행일 {} — 출처 주소: {} — 확인일 {} ({})".format(
            topic_id, t["title"], t["info"], t["basis"], CHECK, " · ".join(urls), CHECK_DATE, CHECK_ORG),
        "세율·한도·금액·기한 같은 숫자: " + NUMBER_SLOT,
        CONFIRM_WITH_ADVISOR,
        "남은 {}: {}".format(CHECK, t["remaining"]),
        DISCLAIMER,
    ]


def cmd_topic(args):
    topic_id = args.id.strip().upper()
    print(NOTICE)
    if topic_id in VAT_TOPICS:
        print(VAT_REFERRAL)
        return finish("vat_referral", 0, {"id": topic_id})
    if topic_id not in TOPICS:
        print(NO_INFO)
        return finish("no_info", 0, {"id": topic_id})
    for line in topic_lines(topic_id):
        print(line)
    return finish("ok", 0, {"id": topic_id})


def cmd_guard(args):
    text = args.text
    print(NOTICE)
    if is_other_business_request(text):
        return finish("refused", 2, {"category": "other_business", "answer": REFUSAL})
    if has_any(text, FILING_WORDS):
        return finish("answered", 0, {"category": "filing", "answer": FILING_ANSWER})
    if is_personal_question(text):
        related = next((tid for word, tid in TOPIC_HINTS if word in text), None)
        if related:
            t = TOPICS[related]
            general = "[{} {}] {} — 근거 조문: {}".format(related, t["title"], t["info"], t["basis"])
        else:
            general = "주제 목록(G1·G2·G3·G4·G6·G7·G8·G15) 가운데 궁금한 주제를 골라 주시면 일반 정보 한 줄을 드릴게요."
        return finish("answered", 0, {"category": "personal", "answer": PERSONAL_ANSWER,
                                      "related_topic": related or "", "general_info": general,
                                      "questions": ADVISOR_QUESTIONS, "advisor_note": CONFIRM_WITH_ADVISOR})
    return finish("pass", 0, {"category": "pass", "answer": ""})


def lint_hits(text):
    hits = []
    for term in LINT_TERMS:
        n = text.count(term)
        if n:
            hits.append({"term": term, "count": n})
    n = text.replace(LEGAL_TERM, "").count("기장")
    if n:
        hits.append({"term": "기장(기장세액공제 밖)", "count": n})
    return hits


def cmd_lint(args):
    print(NOTICE)
    if args.file is not None:
        try:
            with open(args.file, "r", encoding="utf-8-sig") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            print("입력 오류: 검사할 파일을 읽을 수 없어요.")
            return finish("input_error", 2)
    else:
        text = args.text
    hits = lint_hits(text)
    if hits:
        print("쓰면 안 되는 표현이 있어요. 고쳐 주세요.")
        return finish("blocked", 2, {"hits": hits})
    return finish("ok", 0, {"hits": []})


def cmd_list_drafts(args):
    base = args.dir
    if not os.path.isdir(base):
        print("입력 오류: 폴더를 찾을 수 없어요.")
        return finish("input_error", 2)
    files = []
    for root, dirs, names in os.walk(base):
        dirs.sort()
        for name in names:
            files.append(os.path.relpath(os.path.join(root, name), base).replace(os.sep, "/"))
    files.sort()
    print("지울 수 있는 파일이 {}개 있어요.".format(len(files)))
    for name in files:
        print("- " + name)
    print("이 프로그램은 아무것도 지우지 않아요. 이 목록을 보여 드리고 사용자님이 「예」라고 하신 뒤에만 지워요.")
    return finish("ok", 0, {"count": len(files), "files": files})


def build_parser():
    parser = KoreanArgumentParser(prog="ledger_calc.py", description="세금정리도우미 장부 초안 계산 프로그램 (" + NOTICE + ")")
    sub = parser.add_subparsers(dest="command", parser_class=KoreanArgumentParser)
    sub.required = True

    p = sub.add_parser("calc", help="장부 CSV로 장부 표·월별 손익·월별 현금 흐름·요약 만들기")
    p.add_argument("--input", required=True, help="장부 CSV 파일")
    p.add_argument("--out", required=True, help="출력 폴더")
    p.add_argument("--own-business", required=True, help="본인 사업장 자료면 yes")
    p.add_argument("--as-of", help="기준일 YYYY-MM-DD")
    p.add_argument("--expect-self-sha256", required=True, help="이 프로그램 파일의 기대 sha256(필수)")
    p.add_argument("--request-text", help="사용자 요청 문장(다른 회사 요청인지 확인)")
    p.set_defaults(func=cmd_calc)

    p = sub.add_parser("topic", help="일반 절세 정보 한 줄 보기")
    p.add_argument("--id", required=True, help="주제 번호(예: G2)")
    p.set_defaults(func=cmd_topic)

    p = sub.add_parser("guard", help="문장 분류 후 정해진 답 고르기")
    p.add_argument("--text", required=True, help="사용자 문장")
    p.set_defaults(func=cmd_guard)

    p = sub.add_parser("lint", help="쓰면 안 되는 표현 검사")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--text", help="검사할 문장")
    g.add_argument("--file", help="검사할 파일")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("list-drafts", help="지울 수 있는 파일 이름·개수만 보기(지우지 않음)")
    p.add_argument("--dir", required=True, help="장부 초안 폴더")
    p.set_defaults(func=cmd_list_drafts)
    return parser


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
