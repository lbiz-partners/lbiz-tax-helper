# -*- coding: utf-8 -*-
"""가림 결과 노출 검사 — ledger_calc 와 **별도 구현**(import 없음).

원문 connected run 의 가림 대상 span 마다, 마스킹 후 같은 위치에서
끝 4자리를 넘는 숫자 노출·8자리 부분 노출이 있으면 True.
"""

import datetime
import re
import unicodedata

BUSINESS_REG_RE = re.compile(r"^\d{3}[\s\-\.]\d{2}[\s\-\.]\d{5}$")
SENSITIVE_CHUNK_PATTERNS = frozenset(
    ((4, 4, 4, 4), (4, 6, 5), (4, 4, 4, 3), (3, 3, 6), (3, 2, 6))
)
PHONE_LIKE_RE = re.compile(r"^0\d{9,10}$")
PHONE_AREA2 = frozenset(("02", "31", "32", "33", "41", "42", "43", "44", "51", "52", "53", "54", "55", "61", "62", "63", "64"))
AMOUNT_RE = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)$")

def looks_like_yymmdd(six):
    if len(six) != 6 or not six.isdigit():
        return False
    mm, dd = int(six[2:4]), int(six[4:6])
    return 1 <= mm <= 12 and 1 <= dd <= 31

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
            letter_before = d0 > 0 and is_text_letter(text[d0 - 1])
            chunks.append(pos - d0)
            if pos >= n:
                break
            nxt = consume_separator_run(text, pos, n)
            if nxt is None:
                break
            if letter_before:
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


def run_is_phone_entire_run(chunks, digits, n):
    if n == 3 and chunks[0] == 3 and chunks[1] == 4 and chunks[2] == 4:
        return PHONE_LIKE_RE.match(digits)
    if n == 3 and chunks[1] == 4 and chunks[2] == 4 and chunks[0] in (2, 3):
        return len(digits) >= 2 and digits[:2] in PHONE_AREA2 and PHONE_LIKE_RE.match(digits)
    if n == 2 and chunks[0] == 3 and chunks[1] == 4:
        return PHONE_LIKE_RE.match(digits[:7])
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

    if n == 3 and is_business_digit_sequence(chunks) and total == 10:
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


def iter_mask_spans_in_run(text, start, end, chunks, digits):
    """9자리 이상(또는 5자리 덩어리) connected run 은 기본 가림, 단독 예외 run 만 유지."""
    n = len(chunks)
    if run_is_standalone_keep(text, start, end, chunks, digits):
        return
    needs = any(c >= 5 for c in chunks) or len(digits) >= 9
    if not needs:
        return
    if n >= 7 and is_date_digit_sequence(chunks[n - 3:n], digits[-8:]):
        body_n = n - 3
        if body_n >= 1 and (any(chunks[i] >= 5 for i in range(body_n)) or sum(chunks[:body_n]) >= 9):
            s0, _ = chunk_char_range(text, start, end, chunks, 0)
            _, s1 = chunk_char_range(text, start, end, chunks, body_n - 1)
            yield s0, s1
            return
    if n >= 4 and is_date_digit_sequence(chunks[:3], digits[:8]):
        if not run_is_date_plus_short_plain_amount(text, start, end, chunks, digits):
            s0, _ = chunk_char_range(text, start, end, chunks, 3)
            _, s1 = chunk_char_range(text, start, end, chunks, n - 1)
            yield s0, s1
            return
    s0, _ = chunk_char_range(text, start, end, chunks, 0)
    _, s1 = chunk_char_range(text, start, end, chunks, n - 1)
    yield s0, s1

def connected_run_contains_rrn(chunks, digits):
    n = len(chunks)
    for i in range(n):
        for j in range(i + 1, n + 1):
            sub_c = chunks[i:j]
            sub_d = digit_substring(chunks, digits, i, j)
            if is_rrn_digit_pattern(sub_c, sub_d):
                return True
    return False
def _leak_in_char_span(norm_o, norm_m, s0, s1):
    pairs = []
    for pos in range(s0, min(s1, len(norm_o), len(norm_m))):
        if norm_o[pos].isdigit():
            pairs.append((pos, norm_o[pos]))
    n = len(pairs)
    if n <= 4:
        return False
    body = "".join(d for _, d in pairs[:-4])
    vis = "".join(norm_m[pos] for pos, _ in pairs if norm_m[pos].isdigit())
    if not vis:
        return False
    for k, (pos, _) in enumerate(pairs):
        if k < n - 4 and norm_m[pos].isdigit():
            return True
    if len(body) >= 8:
        for i in range(len(body) - 7):
            if body[i : i + 8] in vis:
                return True
    for i in range(len(body)):
        for w in range(5, len(body) - i + 1):
            if body[i : i + w] in vis:
                return True
    return False


def _contiguous_runs(text):
    norm = unicodedata.normalize("NFKC", text or "")
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
    norm_o = unicodedata.normalize("NFKC", original or "")
    norm_m = unicodedata.normalize("NFKC", masked_output or "")

    for run in _contiguous_runs(original):
        if len(run) >= 5 and run in norm_m:
            return True

    for start, end, chunks, digits in iter_connected_digit_sequences(norm_o):
        if connected_run_contains_rrn(chunks, digits):
            continue
        if run_is_standalone_keep(norm_o, start, end, chunks, digits):
            continue
        spans = list(iter_mask_spans_in_run(norm_o, start, end, chunks, digits))
        if not spans:
            continue
        for s0, s1 in spans:
            seg = norm_m[s0:min(s1, len(norm_m))]
            if "*" not in seg and any(norm_o[p].isdigit() for p in range(s0, min(s1, len(norm_o)))):
                if len(digits) > 4:
                    vis = "".join(c for c in seg if c.isdigit())
                    if vis and len(vis) > 4:
                        return True
                    if vis == digits and len(digits) > 4:
                        return True
            if _leak_in_char_span(norm_o, norm_m, s0, s1):
                return True
    return False
