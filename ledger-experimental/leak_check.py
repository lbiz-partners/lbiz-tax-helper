# -*- coding: utf-8 -*-
"""마스킹 결과에 5자리 이상 숫자가 그대로 남았는지 독립적으로 검사해요.

ledger_calc.mask_text 와 다른 방식으로만 판단해요(시험용).
연결 run 본문은 **같은 run 구간**의 마스킹 출력 숫자만 보고, 다른 run(예: 「47개」의 47)과
이어 붙인 전역 숫자열로는 판정하지 않아요.
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


def _run_output_digits(norm_masked, start, end):
    """한 connected run 구간에서만 보이는 숫자(별표 제거)."""
    end = min(end, len(norm_masked))
    if start >= end:
        return ""
    seg = norm_masked[start:end].replace("*", "")
    return "".join(c for c in seg if c.isdigit())


def _trim_preserved_date_prefix(body, run_out_digits):
    """run 앞에 남긴 YYYYMMDD 는 body 검사에서 빼요."""
    if len(body) < 8:
        return body
    head8 = body[:8]
    if head8 not in run_out_digits:
        return body
    try:
        y = int(head8[0:4])
        if y < 1900 or y > 2100:
            return body
        datetime.date(y, int(head8[4:6]), int(head8[6:8]))
    except ValueError:
        return body
    return body[8:]


def _trim_preserved_date_suffix(body, run_out_digits):
    """run 끝에 남긴 YYYYMMDD(1900~2100) 는 body 검사에서 빼요."""
    if len(body) < 8:
        return body
    tail8 = body[-8:]
    if tail8 not in run_out_digits:
        return body
    try:
        y = int(tail8[0:4])
        if y < 1900 or y > 2100:
            return body
        datetime.date(y, int(tail8[4:6]), int(tail8[6:8]))
    except ValueError:
        return body
    return body[:-8]


def _split_run_out_date_suffix(run_out_digits):
    """run 출력 끝 YYYYMMDD(합법) 를 분리해, 앞쪽만 민감 숫자로 봐요."""
    if len(run_out_digits) < 8:
        return run_out_digits, ""
    tail8 = run_out_digits[-8:]
    try:
        y = int(tail8[0:4])
        if y < 1900 or y > 2100:
            return run_out_digits, ""
        datetime.date(y, int(tail8[4:6]), int(tail8[6:8]))
    except ValueError:
        return run_out_digits, ""
    return run_out_digits[:-8], tail8


def _body_leaks_in_run(body, run_out_digits, full_digit_len):
    sensitive_out, _date_tail = _split_run_out_date_suffix(run_out_digits)
    if len(body) < 5:
        return False
    if body in sensitive_out:
        return True
    if full_digit_len >= 9 and len(body) >= 9:
        for i in range(len(body) - 8):
            if body[i : i + 9] in sensitive_out:
                return True
    for i in range(len(body) - 4):
        for w in range(5, len(body) - i - 3):
            if body[i : i + w] in sensitive_out:
                return True
    return False


def independent_digit_leak(original, masked_output):
    """True 이면 노출(누출)이 있어요."""
    norm_o = _nfkc(original)
    norm_m = _nfkc(masked_output)
    out_digits_only = "".join(c for c in norm_m.replace("*", "") if c.isdigit())

    for run in _contiguous_digit_runs(original):
        if len(run) < 5:
            continue
        if run in norm_m:
            return True
        if len(run) > 4:
            tail = run[:-4]
            if len(tail) >= 5 and tail in out_digits_only:
                return True

    for start, end, _chunks, digits in iter_connected_digit_sequences(norm_o):
        if len(digits) <= 4:
            continue
        run_out = _run_output_digits(norm_m, start, end)
        body = digits[:-4]
        body = _trim_preserved_date_prefix(body, run_out)
        body = _trim_preserved_date_suffix(body, run_out)
        if _body_leaks_in_run(body, run_out, len(digits)):
            return True
    return False
