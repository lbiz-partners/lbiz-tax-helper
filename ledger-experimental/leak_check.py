# -*- coding: utf-8 -*-
"""가림 결과 노출 검사 — ledger_calc 를 import 하지 않고, 원문 숫자 위치만 봅니다.

민감 숫자 덩어리마다 출력에 그 끝 4자리를 넘는 숫자가 보이면 True.
주민등록번호 꼴은 한 자리라도 보이면 True(제외되지 않은 행 기준).
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
            letter_before = d0 > 0 and _is_letter(text[d0 - 1])
            chunks.append(clen)
            if pos >= n:
                break
            nxt = _consume_sep(text, pos, n)
            if nxt is None:
                break
            if letter_before and clen <= 2:
                break
            pos = nxt
            if pos >= n or not text[pos].isdigit():
                break
        end = pos
        digits = "".join(c for c in text[start:end] if c.isdigit())
        yield start, end, tuple(chunks), digits
        i = end if end > start else start + 1


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


def _is_card_four_at(chunks, i):
    if i + 3 >= len(chunks):
        return False
    if not all(chunks[i + k] == 4 for k in range(4)):
        return False
    if i >= 1 and chunks[i - 1] == 3 and chunks[i] == 4:
        return False
    if i >= 1 and chunks[0] == 3 and chunks[1] == 4 and i < 3:
        return False
    return True


def _iter_card_starts(chunks):
    i = 0
    n = len(chunks)
    while i + 3 < n:
        if _is_card_four_at(chunks, i):
            yield i
            i += 4
        else:
            i += 1


def _digit_positions_in_span(text, c0, c1):
    return [p for p in range(c0, c1) if p < len(text) and text[p].isdigit()]


def _leak_on_positions(norm_o, norm_m, positions):
    if not positions:
        return False
    orig = [norm_o[p] for p in positions]
    n = len(orig)
    if n <= 4:
        return False
    body = "".join(orig[:-4])
    visible = []
    for k, p in enumerate(positions):
        if p < len(norm_m) and norm_m[p].isdigit():
            visible.append((k, norm_m[p]))
    if not visible:
        return False
    if len(visible) > 4:
        return True
    for k, _ in visible:
        if k < n - 4:
            return True
    vis_s = "".join(d for _, d in visible)
    if len(body) >= 8:
        for i in range(len(body) - 7):
            if body[i : i + 8] in vis_s:
                return True
    for i in range(len(body)):
        for w in range(5, len(body) - i + 1):
            if body[i : i + w] in vis_s:
                return True
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
    c0 = _chunk_ranges(text, start, end, chunks)[0][0]
    ce = _try_comma_amount_end(text, c0, end)
    if ce is None or ce < end:
        return False
    return True


def _drop_trailing_calendar_clock_positions(text, start, end, chunks, digits, positions):
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


def _drop_leading_clock_positions(text, start, end, chunks, positions):
    if len(chunks) >= 2 and chunks[0] == 2 and chunks[1] == 2:
        cr = _chunk_ranges(text, start, end, chunks)
        c0, c1 = cr[0][0], cr[1][1]
        drop = {p for p in range(c0, c1) if text[p].isdigit()}
        return [p for p in positions if p not in drop]
    return positions


def _drop_leading_calendar_positions(text, start, end, chunks, digits, positions):
    drop = set()
    cr = _chunk_ranges(text, start, end, chunks)
    if len(chunks) >= 3 and chunks[0] == 4 and chunks[1] in (1, 2) and chunks[2] in (1, 2):
        if _valid_date8(digits[:8]):
            c0, c1 = cr[0][0], cr[2][1]
            for p in range(c0, c1):
                if text[p].isdigit():
                    drop.add(p)
    elif chunks and chunks[0] == 8 and _valid_date8(digits[:8]):
        c0, c1 = cr[0]
        for p in range(c0, c1):
            if text[p].isdigit():
                drop.add(p)
    return [p for p in positions if p not in drop]


def _sensitive_units_in_run(text, start, end, chunks, digits):
    n = len(chunks)
    cr = _chunk_ranges(text, start, end, chunks)
    if _is_rrn_chunks(chunks, digits):
        pos = []
        for c0, c1 in cr:
            pos.extend(_digit_positions_in_span(text, c0, c1))
        yield pos
        return
    if _run_is_only_clock(chunks) or _run_is_only_calendar(chunks, digits):
        return
    if _run_is_business_only(chunks):
        return
    if _run_is_comma_amount_only(text, start, end, chunks):
        return
    if all(c <= 2 for c in chunks):
        return
    if sum(chunks) < 9 and not any(c >= 5 for c in chunks):
        return

    covered = [False] * n
    for ci in _iter_card_starts(chunks):
        for j in range(ci, ci + 4):
            covered[j] = True
        c0 = cr[ci][0]
        c1 = cr[ci + 3][1]
        yield _digit_positions_in_span(text, c0, c1)

    rem_pos = []
    rem_digits = 0
    text_end = len(text)
    for i in range(n):
        if covered[i]:
            continue
        c0, c1 = cr[i]
        if _try_comma_amount_end(text, c0, text_end) == c1 or (
            _try_comma_amount_end(text, c0, text_end) is not None
            and c0 == cr[i][0]
        ):
            ce = _try_comma_amount_end(text, c0, text_end)
            if ce is not None and ce >= c1:
                continue
        rem_digits += chunks[i]
        rem_pos.extend(_digit_positions_in_span(text, c0, c1))
    if rem_pos and (
        rem_digits >= 9
        or any(chunks[i] >= 5 for i in range(n) if not covered[i])
    ):
        rem_pos = _drop_trailing_calendar_clock_positions(text, start, end, chunks, digits, rem_pos)
        rem_pos = _drop_leading_calendar_positions(text, start, end, chunks, digits, rem_pos)
        rem_pos = _drop_leading_clock_positions(text, start, end, chunks, rem_pos)
        if rem_pos and len(rem_pos) > 4:
            yield rem_pos


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

    for start, end, chunks, digits in iter_connected_runs(norm_o):
        if _is_rrn_chunks(chunks, digits):
            for p in range(start, end):
                if norm_o[p].isdigit() and p < len(norm_m) and norm_m[p].isdigit():
                    return True
            continue
        for unit_pos in _sensitive_units_in_run(norm_o, start, end, chunks, digits):
            if _leak_on_positions(norm_o, norm_m, unit_pos):
                return True
    return False
