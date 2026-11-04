#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""독립 leak_check + mask_text fuzz (QA 재현용).

사용:
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

SEEDS_STRICT = (20261104, 20261105, 20261106, 20261107, 20261108)
SEEDS_REALISTIC = (20261111, 20261112, 20261113, 20261114, 20261115)
N = 3000

SEP_MIXED = (
    "-", " ", "–", "—", "\u2010", "\u2212", "\u3161", "·", "|", "*", ".", "/", "_", ",", "\u00a0",
)


def gen_worker(seed, n, realistic=False):
    rng = random.Random(seed)
    sep_chars = SEP_MIXED if not realistic else ("-", " ", "–", "—", "\u00a0")

    def sep_run():
        if realistic:
            return rng.choice(sep_chars)
        return "".join(rng.choice(sep_chars) for _ in range(rng.randint(1, 2)))

    def card():
        return sep_run().join("{0:04d}".format(rng.randint(0, 9999)) for _ in range(4))

    def acct():
        return sep_run().join((
            "{0:03d}".format(rng.randint(0, 999)),
            "{0:03d}".format(rng.randint(0, 999)),
            "{0:06d}".format(rng.randint(0, 999999)),
        ))

    prefixes = (
        lambda: str(rng.randint(1, 9999999)),
        lambda: "010" + sep_run() + "1234" + sep_run() + "5678",
        lambda: "123" + sep_run() + "45" + sep_run() + "67890",
        lambda: str(rng.randint(1, 99)) + "개",
        lambda: "{0:02d}:{1:02d}".format(rng.randint(0, 23), rng.randint(0, 59)),
        lambda: "20261103",
        lambda: "1,234,567",
        lambda: "2026-11-03",
    )
    texts = []
    attempts = 0
    while len(texts) < n and attempts < 300000:
        attempts += 1
        body = card() if rng.choice((0, 1)) == 0 else acct()
        mode = rng.randint(0, 2)
        if mode == 0:
            text = rng.choice(prefixes)() + " " + body
        elif mode == 1:
            text = body + " " + rng.choice(prefixes)()
        else:
            text = rng.choice(prefixes)() + " " + body + " " + rng.choice(prefixes)()
        if row_contains_rrn(text):
            continue
        texts.append(text)
    return texts


def count_leaks(mask_fn, seeds, n, realistic=False):
    total = 0
    per_seed = {}
    for seed in seeds:
        leaks = 0
        for text in gen_worker(seed, n, realistic=realistic):
            if independent_digit_leak(text, mask_fn(text)):
                leaks += 1
        per_seed[seed] = leaks
        total += leaks
    return total, per_seed


def load_r8():
    path = os.path.join(ROOT, "reference", "ledger_calc_r8.py")
    spec = importlib.util.spec_from_file_location("ledger_calc_r8", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.mask_text


def main():
    r8_mask = load_r8()
    print("=== strict (18종 구분 혼합, 5 seed × {}) ===".format(N))
    print("seeds:", SEEDS_STRICT)
    for name, fn in ("r8", r8_mask), ("r9", mask_text):
        total, per = count_leaks(fn, SEEDS_STRICT, N, realistic=False)
        print(name, "total", total, "per_seed", per)
    print()
    print("=== realistic (하이픈·공백·엔대시, 5 seed × {}) ===".format(N))
    print("seeds:", SEEDS_REALISTIC)
    for name, fn in ("r8", r8_mask), ("r9", mask_text):
        total, per = count_leaks(fn, SEEDS_REALISTIC, N, realistic=True)
        print(name, "total", total, "per_seed", per)


if __name__ == "__main__":
    main()
