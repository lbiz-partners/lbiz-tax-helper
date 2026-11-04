# -*- coding: utf-8 -*-
"""마스킹 결과에 5자리 이상 숫자가 그대로 남았는지 독립적으로 검사해요.

ledger_calc.mask_text 와 다른 방식으로만 판단해요(시험용).
"""

import re
import unicodedata

_SEP = re.compile(r"[\s\-\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u3161\u1173·|*.,/:;~]+")


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
    """구분 글자로만 이어진 숫자 덩어리들의 숫자만 이어 붙인 문자열."""
    norm = _nfkc(text)
    parts = _SEP.split(norm)
    for part in parts:
        digits = "".join(c for c in part if c.isdigit())
        if digits:
            yield digits


def independent_digit_leak(original, masked_output):
    """True 이면 노출(누출)이 있어요."""
    norm_o = _nfkc(original)
    norm_m = _nfkc(masked_output)
    out_plain = norm_m.replace("*", "")
    out_digits_only = "".join(c for c in out_plain if c.isdigit())

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
        prefix = digits[:-4]
        if len(prefix) >= 5 and prefix in out_digits_only:
            return True
        if len(digits) >= 9 and len(prefix) >= 5:
            for i in range(len(digits) - 4):
                for w in range(5, len(digits) - i - 3):
                    sub = digits[i : i + w]
                    if sub in out_digits_only:
                        return True
    return False
