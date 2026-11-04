# -*- coding: utf-8 -*-
"""가림 결과 노출 검사 — ledger_calc 를 import 하지 않습니다.

연결된 숫자 run 마다 원문 숫자 위치를 모아, 가려진 출력에서 그중 4개를 넘어
숫자로 남으면 누출입니다. 주민등록번호 꼴은 한 자리라도 보이면 누출입니다.
(제품 keep 규칙과 무관한 위치 기준 판정)
"""

import datetime
import re
import unicodedata

_MAX_SEP = 3
_RRN7 = re.compile(r"^\d{6}[1-8]\d{6}$")


def _nfkc(text):
    return unicodedata.normalize("NFKC", text or "")


def _is_letter(ch):
    o = ord(ch)
    return (0x41 <= o <= 0x5A or 0x61 <= o <= 0x7A or 0xAC00 <= o <= 0xD7A3)


def _is_sep_ws(ch):
    if ch in " \t\u00a0":
        return True
    return unicodedata.category(ch) == "Zs" and ch not in "\n\r"


def _consume_sep(text, pos, end):
    if pos >= end:
        return None
    start = pos
    nws = 0
    moved = False
    while pos < end:
        ch = text[pos]
        if _is_sep_ws(ch):
            pos += 1
            moved = True
            continue
        if not ch.isdigit() and not _is_letter(ch) and ch not in "\n\r":
            if nws >= _MAX_SEP:
                return None
            nws += 1
            pos += 1
            moved = True
            continue
        break
    return pos if moved and pos > start else None


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
            clen = pos - d0
            chunks.append(clen)
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


def _is_rrn_digits(digits):
    if len(digits) == 13 and _looks_yymmdd(digits[:6]) and digits[6] in "12345678":
        return True
    return False


def _is_rrn_chunks(chunks, digits):
    if len(chunks) == 2 and chunks[0] == 6 and chunks[1] == 7:
        return _looks_yymmdd(digits[:6]) and digits[6] in "12345678"
    if len(chunks) == 1 and len(digits) == 13:
        return _is_rrn_digits(digits)
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


def _run_is_only_clock(chunks):
    return len(chunks) in (2, 3) and all(c == 2 for c in chunks) and sum(chunks) in (4, 6)


def _run_is_only_calendar(chunks, digits):
    n = len(chunks)
    if n == 1 and chunks[0] == 8 and _valid_date8(digits):
        return True
    if n == 3 and chunks[0] == 4 and chunks[1] in (1, 2) and chunks[2] in (1, 2):
        return _valid_date8(digits)
    return False


def _run_is_business_only(chunks):
    return chunks == (3, 2, 5)


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


def _run_is_comma_amount_only(text, start, end, chunks):
    if len(chunks) < 2:
        return False
    pos = start
    for clen in chunks:
        pos += clen
        if pos >= end:
            break
        nxt = _consume_sep(text, pos, end)
        if nxt is None:
            break
        pos = nxt
    c0 = start
    ce = _try_comma_amount_end(text, c0, end)
    if ce is None or ce < end:
        return False
    return True


def _run_is_date_plus_plain_tail(chunks, digits):
    if len(chunks) < 4:
        return False
    if not (chunks[0] == 4 and chunks[1] in (1, 2) and chunks[2] in (1, 2)):
        return False
    if not _valid_date8(digits[:8]):
        return False
    rest = chunks[3:]
    rest_d = digits[8:]
    if len(rest) == 1 and len(rest_d) <= 8 and rest[0] <= 7:
        return True
    return False


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


def _positions_minus_trailing_keep(text, start, end, chunks, digits, positions):
    n = len(chunks)
    drop = set()
    cr = _chunk_ranges(text, start, end, chunks)
    if n >= 2 and chunks[-2] == 2 and chunks[-1] == 2:
        c0, c1 = cr[n - 2][0], cr[n - 1][1]
        for p in range(c0, c1):
            if text[p].isdigit():
                drop.add(p)
    if n >= 3 and chunks[-3] == 4 and _valid_date8(digits[-8:]):
        c0 = cr[n - 3][0]
        c1 = cr[n - 1][1]
        for p in range(c0, c1):
            if text[p].isdigit():
                drop.add(p)
    return [p for p in positions if p not in drop]


def _run_is_public_exception(text, start, end, chunks, digits):
    if _run_is_only_clock(chunks):
        return True
    if _run_is_only_calendar(chunks, digits):
        return True
    if _run_is_business_only(chunks):
        return True
    if _run_is_comma_amount_only(text, start, end, chunks):
        return True
    if _run_is_date_plus_plain_tail(chunks, digits):
        return True
    if chunks and all(c <= 2 for c in chunks) and sum(chunks) < 9:
        return True
    return False


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


def _leak_visible_digit_count(norm_o, norm_m, positions):
    return sum(
        1
        for p in positions
        if p < len(norm_m) and norm_o[p].isdigit() and norm_m[p].isdigit()
    )


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
        if _run_is_public_exception(norm_o, start, end, chunks, digits):
            continue
        if sum(chunks) < 9 and not any(c >= 5 for c in chunks):
            continue

        positions = [p for p in range(start, end) if norm_o[p].isdigit()]
        positions = _positions_minus_trailing_keep(norm_o, start, end, chunks, digits, positions)
        if len(positions) <= 4:
            continue
        visible = _leak_visible_digit_count(norm_o, norm_m, positions)
        if visible > 4:
            return True
        for k, p in enumerate(positions):
            if k < len(positions) - 4 and norm_m[p].isdigit():
                return True
    return False
