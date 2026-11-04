# -*- coding: utf-8 -*-
"""가림 결과 노출 검사 — ledger_calc 를 import 하지 않습니다.

연결 run(숫자 덩어리 + 비문자 구분)마다 감사할 숫자 위치만 보고,
9자리 이상 run 에서는 끝 4자리 밖에 숫자가 보이면 누출.
주민등록번호 꼴은 한 자리라도 보이면 누출(행 제외는 row_contains_rrn).
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
    """비문자·비숫자 구분(글자·줄바꿈 제외)이 이어지면 같은 run."""
    if pos >= end:
        return None
    start = pos
    while pos < end:
        ch = text[pos]
        if ch.isdigit() or _is_letter(ch) or ch in "\n\r":
            break
        pos += 1
    return pos if pos > start else None


def iter_connected_runs(text):
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
            chunks.append(pos - d0)
            if pos >= n:
                break
            nxt = _consume_sep(text, pos, n)
            if nxt is None:
                break
            pos = nxt
            if pos >= n or not text[pos].isdigit():
                break
        end = pos
        digits = "".join(c for c in text[start:end] if c.isdigit())
        yield start, end, tuple(chunks), digits
        i = end if end > start else start + 1


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


def _phone_credible(digits):
    if not re.match(r"^0\d{9,10}$", digits):
        return False
    if len(digits) >= 3 and digits[:3] in _MOBILE3:
        return True
    if len(digits) >= 2 and digits[:2] in PHONE_AREA2:
        return True
    return False


def _is_phone_prefix(chunks, digits):
    if len(chunks) < 3 or chunks[0] != 3 or chunks[1] != 4 or chunks[2] != 4:
        return False
    return _phone_credible(digits[:11])


def _is_valid_hhmm(chunks, digits, ci):
    if ci + 1 >= len(chunks) or chunks[ci] != 2 or chunks[ci + 1] != 2:
        return False
    off = sum(chunks[:ci])
    sub = digits[off : off + 4]
    if len(sub) != 4:
        return False
    hh, mm = int(sub[0:2]), int(sub[2:4])
    return 0 <= hh <= 23 and 0 <= mm <= 59


def _is_card_four_at(chunks, i):
    if i + 3 >= len(chunks):
        return False
    return all(chunks[i + k] == 4 for k in range(4))


def _card_immediately_before_clock(chunks, digits, ci_time):
    cs = ci_time - 4
    if cs < 0 or not _is_card_four_at(chunks, cs):
        return False
    if cs == 0:
        return True
    if sum(chunks[:cs]) <= 2:
        return True
    if cs == 3 and _is_phone_prefix(chunks, digits):
        return True
    return False


def _trailing_card_time(chunks, digits):
    n = len(chunks)
    if n < 6 or not _is_valid_hhmm(chunks, digits, n - 2):
        return False
    return _card_immediately_before_clock(chunks, digits, n - 2)


def _chunk_ranges(text, start, end, chunks):
    pos = start
    ranges = []
    for clen in chunks:
        c0, c1 = pos, pos + clen
        ranges.append((c0, c1))
        pos = c1
        if pos >= end:
            break
        nxt = _consume_sep(text, pos, end)
        if nxt is None:
            break
        pos = nxt
    return ranges


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


def _run_fully_public(text, start, end, chunks, digits):
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
    return False


def _comma_amount_hi(text, start, end, chunks, lo, hi):
    cr = _chunk_ranges(text, start, end, chunks)
    for i in range(lo, hi + 1):
        c0, _ = cr[i]
        if _try_comma_amount_end(text, c0, end) == end and i > lo:
            if i > 0 and chunks[i - 1] >= 5:
                continue
            return i - 1
    return hi


def _audit_chunk_range(chunks, digits):
    """9자리 이상 run: 감사 구간(앞 날짜·끝 달력/시각·전화 접두 제외)."""
    n = len(chunks)
    if sum(chunks) < 9 and not any(c >= 5 for c in chunks):
        return None
    lo, hi = 0, n - 1
    if n >= 4 and _is_date_seq(chunks[:3], digits[:8]) and not _run_is_date_plain_tail(chunks, digits):
        lo = 3
    elif n > 3 and _is_phone_prefix(chunks, digits):
        lo = 3
    if lo == 0:
        for ci in range(1, n):
            if sum(chunks[:ci]) > 2:
                break
            if _is_card_four_at(chunks, ci):
                lo = ci
                break
    if _trailing_card_time(chunks, digits):
        hi = n - 3
    elif n >= 3 and _is_date_seq(chunks[n - 3 : n], digits[-8:]):
        try:
            y = int(digits[-8:][:4])
        except ValueError:
            y = 0
        if 2000 <= y <= 2100:
            hi = n - 4
    if lo <= hi and sum(chunks[lo : hi + 1]) >= 9:
        return lo, hi
    if any(chunks[k] >= 5 for k in range(lo, hi + 1)):
        return lo, hi
    return None


def _audit_positions(text, start, end, chunks, digits):
    if _run_fully_public(text, start, end, chunks, digits):
        return []
    span = _audit_chunk_range(chunks, digits)
    if span is None:
        return []
    lo, hi = span
    hi = _comma_amount_hi(text, start, end, chunks, lo, hi)
    cr = _chunk_ranges(text, start, end, chunks)
    positions = []
    for i in range(lo, hi + 1):
        c0, c1 = cr[i]
        for p in range(c0, c1):
            if text[p].isdigit():
                positions.append(p)
    return positions


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
