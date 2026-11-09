# -*- coding: utf-8 -*-
"""MANIFEST.txt(규칙 파일 목록)와 SHA256SUMS(모든 파일 sha256)를 다시 만든다.

저장소 맨 위에서 `python3 tools/make_manifest.py` 로 실행한다. 표준 라이브러리와 git만 쓴다.
- MANIFEST.txt: 맨 위 주석은 그대로 두고, 판 표시(「(vX.Y)」「# 판: vX.Y」)를 VERSION 파일 값으로 맞춘 뒤
  규칙 파일 줄(파일sha256  본문sha256  파일이름  스킬이름)을 다시 계산한다.
- SHA256SUMS: git이 관리하는 모든 파일(무시 목록 제외, SHA256SUMS 자신 제외)의 `sha256sum -c` 형식 목록.
"""
import hashlib
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINE = re.compile(r"^([0-9a-f]{64})  ([0-9a-f]{64})  (\S+)  (.+)$")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def body_sha256(text):
    match = re.match(r"^---\n.*?\n---\n", text, re.S)
    if not match:
        raise SystemExit("머리말이 없는 규칙 파일이 있어요")
    return sha256_bytes(text[match.end():].strip().encode("utf-8"))


def main():
    os.chdir(ROOT)
    version = open("VERSION", encoding="utf-8").read().strip()
    if not re.fullmatch(r"\d+\.\d+", version):
        raise SystemExit("VERSION 형식이 X.Y가 아니에요: " + version)
    lines = open("MANIFEST.txt", encoding="utf-8").read().splitlines()
    out = []
    for line in lines:
        m = LINE.match(line)
        if m:
            name, skill = m.group(3), m.group(4)
            data = open(name, "rb").read()
            out.append("{}  {}  {}  {}".format(sha256_bytes(data), body_sha256(data.decode("utf-8")), name, skill))
            continue
        if line.startswith("# 판: "):
            line = "# 판: v" + version
        elif out == [] and line.startswith("# ") and re.search(r"\(v[\d.]+\)", line):
            line = re.sub(r"\(v[\d.]+\)", "(v" + version + ")", line, count=1)
        out.append(line)
    with open("MANIFEST.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")

    files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                           check=True, capture_output=True).stdout.decode("utf-8").split("\0")
    files = sorted(f for f in files if f and f != "SHA256SUMS" and os.path.isfile(f))
    with open("SHA256SUMS", "w", encoding="utf-8") as f:
        for name in files:
            f.write("{}  {}\n".format(sha256_bytes(open(name, "rb").read()), name))
    print("MANIFEST.txt, SHA256SUMS 를 v{} 로 다시 만들었어요 (파일 {}개)".format(version, len(files)))


if __name__ == "__main__":
    sys.exit(main())
