# -*- coding: utf-8 -*-
"""가림 결과 노출 검사 — ledger_calc 를 import 하지 않습니다.

연결 run(비문자 구분 + letter→digit 붙임)마다, 9자리 이상이면
run 안 모든 숫자 위치 중 끝 4자리만 숫자로 남을 수 있음. 그 외는 누출.
주민등록번호 꼴은 한 자리라도 보이면 누출(행 제외는 row_contains_rrn).

ledger_calc.mask_text 와 같은 run·last4 규칙을 이 파일에 **다시 구현**한 보조 검사기입니다.
import 는 하지 않지만, 완전히 독립된 판정 알고리즘이라고 보기는 어렵습니다.
"""

import datetime
import re
import unicodedata

PHONE_AREA2 = frozenset(
    ("02", "31", "32", "33", "41", "42", "43", "44", "51", "52", "53", "54", "55", "61", "62", "63", "64")
)
_MOBILE3 = frozenset(("010", "011", "016", "017", "018", "019"))


def _nfkc(text):
    return unicodedata.normalize("NFKC", text or "")


def _is_letter(ch):
    o = ord(ch)
    if 0x41 <= o <= 0x5A or 0x61 <= o <= 0x7A:
        return True
    if 0xAC00 <= o <= 0xD7A3:
        return True
    return False


def _consume_sep(text, pos, end):
    if pos >= end:
        return None
    start = pos
    while pos < end:
        ch = text[pos]
        if ch.isdigit() or _is_letter(ch) or ch in "\n\r":
            break
        pos += 1
    return pos if pos > start else None


def _letter_run_is_latin_label(text, start, end):
    if start >= end:
        return False
    for p in range(start, end):
        ch = text[p]
        if not _is_letter(ch):
            return False
        o = ord(ch)
        if o > 0x7F:
            return False
        if 0x41 <= o <= 0x5A or 0x61 <= o <= 0x7A:
            continue
        return False
    return True


def _min_glued_first_chunk(text, letter_start, letter_end):
    if _letter_run_is_latin_label(text, letter_start, letter_end):
        return 1
    return 3


def _advance_letter_glue(text, pos, end):
    if pos >= end or not _is_letter(text[pos]):
        return None
    p = pos
    while p < end and _is_letter(text[p]):
        p += 1
    if p >= end or not text[p].isdigit():
        return None
    q = p
    while q < end and text[q].isdigit():
        q += 1
    if q - p < _min_glued_first_chunk(text, pos, p):
        if q - p <= 1 and q < end and text[q] in " \t\u00a0":
            return None
        _, _end, _c, digits = _iter_run(text, p, end)
        if len(digits) < 9:
            return None
    return p


def _iter_run(text, start_pos, end_bound):
    chunks = []
    pos = start_pos
    while True:
        if pos >= end_bound or not text[pos].isdigit():
            break
        d0 = pos
        while pos < end_bound and text[pos].isdigit():
            pos += 1
        chunks.append(pos - d0)
        if pos >= end_bound:
            break
        nxt = _consume_sep(text, pos, end_bound)
        if nxt is not None:
            pos = nxt
            continue
        glued = _advance_letter_glue(text, pos, end_bound)
        if glued is not None:
            pos = glued
            continue
        break
    end = pos
    digits = "".join(c for c in text[start_pos:end] if c.isdigit())
    return start_pos, end, tuple(chunks), digits


def _digit_run_may_start_at(text, pos):
    if pos >= len(text) or not text[pos].isdigit():
        return False
    if pos > 0 and _is_letter(text[pos - 1]):
        j = pos - 1
        while j >= 0 and _is_letter(text[j]):
            j -= 1
        letter_start = j + 1
        q = pos
        while q < len(text) and text[q].isdigit():
            q += 1
        if q - pos < _min_glued_first_chunk(text, letter_start, pos):
            if q - pos <= 1 and q < len(text) and text[q] in " \t\u00a0":
                return False
            _, _end, _c, digits = _iter_run(text, pos, len(text))
            if len(digits) < 9:
                return False
    return True


def iter_connected_runs(text):
    n = len(text)
    i = 0
    while i < n:
        if text[i].isdigit() and _digit_run_may_start_at(text, i):
            yield _iter_run(text, i, n)
            _, end, _, _ = _iter_run(text, i, n)
            i = end if end > i else i + 1
            continue
        if _is_letter(text[i]):
            glued = _advance_letter_glue(text, i, n)
            if glued is not None:
                yield _iter_run(text, glued, n)
                _, end, _, _ = _iter_run(text, glued, n)
                i = end if end > glued else i + 1
                continue
        i += 1


def _looks_yymmdd(six):
    if len(six) != 6 or not six.isdigit():
        return False
    mm, dd = int(six[2:4]), int(six[4:6])
    return 1 <= mm <= 12 and 1 <= dd <= 31


def _is_rrn_chunks(chunks, digits):
    if len(chunks) == 2 and chunks[0] == 6 and chunks[1] == 7:
        return _looks_yymmdd(digits[:6]) and digits[6] in "12345678"
    if len(chunks) == 1 and len(digits) == 13:
        return _looks_yymmdd(digits[:6]) and digits[6] in "12345678"
    return False


def _valid_date8(d8):
    if len(d8) != 8:
        return False
    try:
        y = int(d8[0:4])
        if y < 1900 or y > 2100:
            return False
        datetime.date(y, int(d8[4:6]), int(d8[6:8]))
        return True
    except ValueError:
        return False


def _is_date_seq(chunks, digits):
    if len(chunks) != 3 or chunks[0] != 4:
        return False
    return _valid_date8(digits[:8])


def _try_comma_amount_end(text, start, end):
    pos = start
    fl = 0
    while pos < end and text[pos].isdigit():
        fl += 1
        pos += 1
        if fl > 3:
            return None
    if fl < 1 or pos >= end or text[pos] != ",":
        return None
    pos += 1
    groups = 0
    while pos < end:
        if pos + 3 > end or not text[pos : pos + 3].isdigit():
            return None
        groups += 1
        pos += 3
        if pos < end and text[pos] == ",":
            pos += 1
        else:
            break
    return pos if groups >= 1 else None


def _run_is_comma_only(text, start, end, chunks):
    if len(chunks) < 2:
        return False
    ce = _try_comma_amount_end(text, start, end)
    return ce is not None and ce >= end


def _run_is_business(chunks):
    return chunks == (3, 2, 5)


def _run_is_small_counter(chunks):
    return chunks and all(c <= 2 for c in chunks) and sum(chunks) < 9


def _run_is_date_plain_tail(chunks, digits):
    if len(chunks) < 4 or not _is_date_seq(chunks[:3], digits[:8]):
        return False
    rest = chunks[3:]
    rest_d = digits[8:]
    return len(rest) == 1 and len(rest_d) <= 8 and rest[0] <= 7


def _run_is_phone_only(chunks, digits):
    if len(chunks) != 3 or chunks != (3, 4, 4):
        return False
    if digits[:3] not in _MOBILE3:
        return False
    return bool(re.match(r"^0\d{10}$", digits))


def _run_fully_public(text, start, end, chunks, digits):
    if sum(chunks) > 8 and not any(c >= 5 for c in chunks):
        return False
    if _run_is_small_counter(chunks):
        return True
    if _run_is_business(chunks) and len(digits) == 10:
        return True
    if _run_is_comma_only(text, start, end, chunks):
        return True
    if _run_is_date_plain_tail(chunks, digits):
        return True
    if len(chunks) == 3 and _is_date_seq(chunks, digits):
        return True
    if len(chunks) == 1 and chunks[0] == 8 and _valid_date8(digits):
        return True
    if len(chunks) in (2, 3) and all(c == 2 for c in chunks) and sum(chunks) in (4, 6):
        return True
    if _run_is_phone_only(chunks, digits):
        return True
    return False


def _audit_positions(text, start, end, chunks, digits):
    if _run_fully_public(text, start, end, chunks, digits):
        return []
    if len(digits) < 9 and not any(c >= 5 for c in chunks):
        return []
    return [p for p in range(start, end) if text[p].isdigit()]


def _contiguous_digit_strings(text):
    norm = _nfkc(text)
    i = 0
    while i < len(norm):
        if not norm[i].isdigit():
            i += 1
            continue
        j = i
        while j < len(norm) and norm[j].isdigit():
            j += 1
        yield norm[i:j]
        i = j


def independent_digit_leak(original, masked_output):
    norm_o = _nfkc(original)
    norm_m = _nfkc(masked_output)

    for run in _contiguous_digit_strings(original):
        if len(run) >= 5 and run in norm_m:
            return True

    if len(norm_o) != len(norm_m):
        return True

    for start, end, chunks, digits in iter_connected_runs(norm_o):
        if _is_rrn_chunks(chunks, digits):
            for p in range(start, end):
                if norm_o[p].isdigit() and norm_m[p].isdigit():
                    return True
            continue

        positions = _audit_positions(norm_o, start, end, chunks, digits)
        if len(positions) <= 4:
            continue
        visible = sum(
            1 for p in positions if p < len(norm_m) and norm_o[p].isdigit() and norm_m[p].isdigit()
        )
        if visible > 4:
            return True
        for k, p in enumerate(positions):
            if k < len(positions) - 4 and norm_m[p].isdigit():
                return True
    return False
