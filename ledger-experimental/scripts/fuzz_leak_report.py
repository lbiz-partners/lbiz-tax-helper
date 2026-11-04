#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mask_text + leak_check 보조 검사 fuzz 재현.

  cd ledger-experimental
  python3 scripts/fuzz_leak_report.py
"""

import importlib.util
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from leak_check import independent_digit_leak  # noqa: E402
from ledger_calc import mask_text, row_contains_rrn  # noqa: E402

N = 3000
SEEDS_STRICT = (20261104, 20261105, 20261106, 20261107, 20261108)
SEEDS_REALISTIC = (20261111, 20261112, 20261113, 20261114, 20261115)
SEEDS_GLUED = (20261121, 20261122, 20261123, 20261124, 20261125)
SEEDS_PRECARD = (20261131, 20261132, 20261133, 20261134, 20261135)

SEP_MIXED = (
    "-", " ", "–", "—", "\u2010", "\u2212", "\u3161", "·", "|", "*", ".", "/", "_", ",", "\u00a0", ":", ";", "~",
)
GLUED_LABELS = (
    "카드", "카드번호", "계좌", "주민번호", "입금자", "Visa", "메모", "a", "A", "번호",
)
REALISTIC_SEP = ("-", " ", "–", "—", "\u00a0")


def _sep_run(rng, realistic=False):
    if realistic:
        return rng.choice(REALISTIC_SEP)
    return "".join(rng.choice(SEP_MIXED) for _ in range(rng.randint(1, 2)))


def _card(rng, realistic=False):
    return _sep_run(rng, realistic).join("{0:04d}".format(rng.randint(0, 9999)) for _ in range(4))


def _acct(rng, realistic=False):
    return _sep_run(rng, realistic).join((
        "{0:03d}".format(rng.randint(0, 999)),
        "{0:03d}".format(rng.randint(0, 999)),
        "{0:06d}".format(rng.randint(0, 999999)),
    ))


def gen_strict(seed, n):
    rng = random.Random(seed)
    prefixes = (
        lambda: str(rng.randint(1, 9999999)),
        lambda: "010" + _sep_run(rng) + "1234" + _sep_run(rng) + "5678",
        lambda: "123" + _sep_run(rng) + "45" + _sep_run(rng) + "67890",
        lambda: str(rng.randint(1, 99)) + "개",
        lambda: "{0:02d}:{1:02d}".format(rng.randint(0, 23), rng.randint(0, 59)),
        lambda: "20261103",
        lambda: "1,234,567",
        lambda: "2026-11-03",
    )
    out = []
    attempts = 0
    while len(out) < n and attempts < 400000:
        attempts += 1
        body = _card(rng) if rng.choice((0, 1)) == 0 else _acct(rng)
        mode = rng.randint(0, 2)
        if mode == 0:
            text = rng.choice(prefixes)() + " " + body
        elif mode == 1:
            text = body + " " + rng.choice(prefixes)()
        else:
            text = rng.choice(prefixes)() + " " + body + " " + rng.choice(prefixes)()
        if row_contains_rrn(text):
            continue
        out.append(text)
    return out


def gen_realistic(seed, n):
    rng = random.Random(seed)
    out = []
    attempts = 0
    while len(out) < n and attempts < 400000:
        attempts += 1
        body = _card(rng, True) if rng.choice((0, 1)) == 0 else _acct(rng, True)
        prefix = rng.choice((
            lambda: str(rng.randint(1, 999999)),
            lambda: "{0:02d}:{1:02d}".format(rng.randint(0, 23), rng.randint(0, 59)),
            lambda: "2026-11-03",
        ))()
        text = prefix + " " + body if rng.choice((0, 1)) else body + " " + prefix
        if row_contains_rrn(text):
            continue
        out.append(text)
    return out


def gen_letter_glued(seed, n):
    rng = random.Random(seed)
    out = []
    attempts = 0
    while len(out) < n and attempts < 400000:
        attempts += 1
        label = rng.choice(GLUED_LABELS)
        sep = _sep_run(rng)
        if rng.choice((0, 1)) == 0:
            body = _card(rng) if rng.choice((0, 1)) == 0 else _acct(rng)
            if rng.choice((0, 1)) == 0:
                text = label + body
            else:
                text = label + sep + body
        else:
            rrn = "{0:06d}{1}{2:07d}".format(
                rng.randint(0, 999999), sep, rng.randint(0, 9999999)
            )
            text = label + rrn if rng.choice((0, 1)) else label + sep + rrn
        if row_contains_rrn(text) and "주민" not in label:
            continue
        out.append(text)
    return out


def gen_preceding_card(seed, n):
    rng = random.Random(seed)
    out = []
    attempts = 0
    while len(out) < n and attempts < 400000:
        attempts += 1
        pre = rng.choice((
            lambda: str(rng.randint(1, 99)),
            lambda: str(rng.randint(100000, 9999999)),
            lambda: "010" + _sep_run(rng) + "{0:04d}".format(rng.randint(0, 9999)),
        ))()
        card = _card(rng)
        time = "{0:02d}:{1:02d}".format(rng.randint(0, 23), rng.randint(0, 59))
        text = pre + " " + card + " " + time
        if row_contains_rrn(text):
            continue
        out.append(text)
    return out


def count_leaks(mask_fn, texts):
    leaks = 0
    for text in texts:
        if independent_digit_leak(text, mask_fn(text)):
            leaks += 1
    return leaks


def load_baseline_mask():
    path = os.path.join(ROOT, "reference", "ledger_calc_baseline.py")
    spec = importlib.util.spec_from_file_location("ledger_calc_baseline", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.mask_text


def run_suite(name, seeds, generator, mask_fn):
    print("=== {} (5 seed × {}) ===".format(name, N))
    print("seeds:", seeds)
    total = 0
    per = {}
    for seed in seeds:
        texts = generator(seed, N)
        c = count_leaks(mask_fn, texts)
        per[seed] = c
        total += c
    print("total", total, "per_seed", per)
    print()


def main():
    baseline_mask = load_baseline_mask()
    run_suite("strict", SEEDS_STRICT, gen_strict, mask_text)
    run_suite("realistic", SEEDS_REALISTIC, gen_realistic, mask_text)
    run_suite("letter-glued", SEEDS_GLUED, gen_letter_glued, mask_text)
    run_suite("preceding-number+card", SEEDS_PRECARD, gen_preceding_card, mask_text)
    print("(reference baseline strict total on same strict generator)")
    t = sum(count_leaks(baseline_mask, gen_strict(s, N)) for s in SEEDS_STRICT)
    print("baseline strict total", t)


if __name__ == "__main__":
    main()
