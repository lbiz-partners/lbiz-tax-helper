# -*- coding: utf-8 -*-
"""마스킹 결과에 5자리 이상 숫자가 그대로 남았는지 독립적으로 검사해요.

ledger_calc.mask_text 와 다른 방식으로만 판단해요(시험용).
"""

import datetime
import unicodedata

from ledger_calc import iter_connected_digit_sequences


def _nfkc(text):
    return unicodedata.normalize("NFKC", text or "")


def _contiguous_digit_runs(text):
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


def _connected_digit_strings(text):
    """구분 글자로 이어진 한 run 의 숫자만 모아요(ledger 와 같은 run 경계)."""
    norm = _nfkc(text)
    for _start, _end, _chunks, digits in iter_connected_digit_sequences(norm):
        if digits:
            yield digits


def _output_digit_stream(masked_output):
    norm_m = _nfkc(masked_output)
    out_plain = norm_m.replace("*", "")
    return "".join(c for c in out_plain if c.isdigit())


def _trim_preserved_date_suffix(body, out_digits_only):
    """run 끝에 남긴 YYYYMMDD(1900~2100) 는 body 검사에서 빼요."""
    if len(body) < 8:
        return body
    tail8 = body[-8:]
    if tail8 not in out_digits_only:
        return body
    try:
        y = int(tail8[0:4])
        if y < 1900 or y > 2100:
            return body
        datetime.date(y, int(tail8[4:6]), int(tail8[6:8]))
    except ValueError:
        return body
    return body[:-8]


def independent_digit_leak(original, masked_output):
    """True 이면 노출(누출)이 있어요."""
    norm_m = _nfkc(masked_output)
    out_digits_only = _output_digit_stream(masked_output)

    for run in _contiguous_digit_runs(original):
        if len(run) < 5:
            continue
        if run in norm_m:
            return True
        if len(run) > 4:
            tail = run[:-4]
            if len(tail) >= 5 and tail in out_digits_only:
                return True

    for digits in _connected_digit_strings(original):
        if len(digits) <= 4:
            continue
        body = digits[:-4]
        body = _trim_preserved_date_suffix(body, out_digits_only)
        if len(body) < 5:
            continue
        if body in out_digits_only:
            return True
        if len(digits) >= 9 and len(body) >= 9:
            for i in range(len(body) - 8):
                if body[i : i + 9] in out_digits_only:
                    return True
        elif len(body) >= 5:
            for i in range(len(body) - 4):
                for w in range(5, len(body) - i - 3):
                    if body[i : i + w] in out_digits_only:
                        return True
    return False
