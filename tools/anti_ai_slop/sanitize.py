#!/usr/bin/env python3
"""Strip invisible characters that models leave in generated text.

Zero-width spaces, bidi controls, tag characters, variation selectors,
noncharacters, and unusual spacing all survive a copy-paste and none of them
render. They break grep, diffs, search indexing, and word counts, so removing
them is publishing hygiene independent of who wrote the text.

Usage:
    python3 sanitize.py DRAFT.md              # report what is in there
    python3 sanitize.py DRAFT.md --fix        # rewrite the file in place
    python3 sanitize.py DRAFT.md --fix -o OUT # write a cleaned copy
    cat DRAFT.md | python3 sanitize.py - --fix > clean.md
    python3 sanitize.py DRAFT.md --json

Exit codes: 0 = nothing found (or --fix succeeded), 1 = findings remain, 2 = usage.
"""

import argparse
import json
import os
import sys
import unicodedata

# Deleted outright. None of these carry meaning in Latin-script prose.
DELETE = {
    0x00AD: "soft hyphen",
    0x061C: "Arabic letter mark",
    0x180E: "Mongolian vowel separator",
    0x180F: "Mongolian free variation selector",
    0x200B: "zero-width space",
    0x200E: "left-to-right mark",
    0x200F: "right-to-left mark",
    0x2060: "word joiner",
    0x2061: "function application",
    0x2062: "invisible times",
    0x2063: "invisible separator",
    0x2064: "invisible plus",
    0x2065: "reserved ignorable",
    0x3164: "Hangul filler",
    0xFEFF: "zero-width no-break space",
    0xFFA0: "halfwidth Hangul filler",
}
DELETE.update({cp: "bidi override" for cp in range(0x202A, 0x202F)})
DELETE.update({cp: "bidi isolate" for cp in range(0x2066, 0x206A)})
DELETE.update({cp: "tag character" for cp in range(0xE0000, 0xE0080)})
DELETE.update({cp: "reserved ignorable" for cp in range(0xFFF0, 0xFFF9)})
DELETE.update({cp: "noncharacter" for cp in range(0xFDD0, 0xFDF0)})
for plane in range(17):
    DELETE[plane * 0x10000 + 0xFFFE] = "noncharacter"
    DELETE[plane * 0x10000 + 0xFFFF] = "noncharacter"

# Deleted only when both neighbours are plain Latin. Next to emoji, Indic, or
# Arabic these are load-bearing and removing them corrupts the text.
CONTEXTUAL = {
    0x200C: "zero-width non-joiner",
    0x200D: "zero-width joiner",
}
CONTEXTUAL.update({cp: "variation selector" for cp in range(0xFE00, 0xFE10)})
CONTEXTUAL.update({cp: "variation selector" for cp in range(0xE0100, 0xE01F0)})

# Replaced with an ordinary equivalent.
REPLACE = {
    0x00A0: (" ", "no-break space"),
    0x2000: (" ", "en quad"), 0x2001: (" ", "em quad"),
    0x2002: (" ", "en space"), 0x2003: (" ", "em space"),
    0x2004: (" ", "three-per-em space"), 0x2005: (" ", "four-per-em space"),
    0x2006: (" ", "six-per-em space"), 0x2007: (" ", "figure space"),
    0x2008: (" ", "punctuation space"), 0x2009: (" ", "thin space"),
    0x200A: (" ", "hair space"), 0x202F: (" ", "narrow no-break space"),
    0x205F: (" ", "medium mathematical space"), 0x3000: (" ", "ideographic space"),
    0x2018: ("'", "left single quote"), 0x2019: ("'", "right single quote"),
    0x201A: ("'", "single low quote"), 0x201B: ("'", "reversed single quote"),
    0x201C: ('"', "left double quote"), 0x201D: ('"', "right double quote"),
    0x201E: ('"', "double low quote"), 0x2032: ("'", "prime"), 0x2033: ('"', "double prime"),
    0x2026: ("...", "ellipsis"),
    0x2212: ("-", "minus sign"), 0x2010: ("-", "hyphen"), 0x2011: ("-", "non-breaking hyphen"),
    0x00A0: (" ", "no-break space"),
}

# Reported but never changed automatically: replacing a dash is an editorial
# call about sentence structure, and slopcheck rule F1 already raises it.
REPORT_ONLY = {
    0x2013: "en dash",
    0x2014: "em dash",
}


def is_plain_latin(ch):
    return ch is not None and ord(ch) < 0x0300


def scan(text, keep_smart_quotes=False, keep_dashes=True):
    """Return (cleaned_text, findings). Offsets in findings index the input."""
    out = []
    findings = []
    for i, ch in enumerate(text):
        cp = ord(ch)
        prev = text[i - 1] if i else None
        nxt = text[i + 1] if i + 1 < len(text) else None
        line = text.count("\n", 0, i) + 1

        def note(kind, name, action):
            findings.append({"line": line, "offset": i, "codepoint": "U+{:04X}".format(cp),
                             "name": name, "category": kind, "action": action})

        if cp in DELETE:
            note("invisible", DELETE[cp], "removed")
            continue
        if cp in CONTEXTUAL:
            if is_plain_latin(prev) and is_plain_latin(nxt):
                note("invisible", CONTEXTUAL[cp], "removed")
                continue
            note("invisible", CONTEXTUAL[cp], "kept, adjacent to non-Latin text")
            out.append(ch)
            continue
        if cp in REPORT_ONLY:
            note("typography", REPORT_ONLY[cp], "reported only")
            out.append(ch)
            continue
        if cp in REPLACE:
            repl, name = REPLACE[cp]
            if keep_smart_quotes and name.endswith(("quote", "prime")):
                out.append(ch)
                continue
            note("typography", name, "replaced with {!r}".format(repl))
            out.append(repl)
            continue
        if unicodedata.category(ch) == "Cf":
            note("invisible", "format control", "removed")
            continue
        out.append(ch)
    return "".join(out), findings


def summarize(findings):
    counts = {}
    for f in findings:
        key = (f["codepoint"], f["name"], f["action"])
        counts[key] = counts.get(key, 0) + 1
    return counts


def main():
    ap = argparse.ArgumentParser(description="Strip invisible characters from text.")
    ap.add_argument("path", help="File to clean, or - for stdin.")
    ap.add_argument("--fix", action="store_true", help="Write the cleaned text.")
    ap.add_argument("-o", "--output", help="Write to this path instead of in place.")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    ap.add_argument("--keep-smart-quotes", action="store_true",
                    help="Leave curly quotes and apostrophes alone.")
    args = ap.parse_args()

    if args.path == "-":
        text = sys.stdin.read()
    else:
        if not os.path.isfile(args.path):
            sys.stderr.write("No such file: {}\n".format(args.path))
            return 2
        with open(args.path, encoding="utf-8") as fh:
            text = fh.read()

    cleaned, findings = scan(text, keep_smart_quotes=args.keep_smart_quotes)
    invisible = [f for f in findings if f["category"] == "invisible" and f["action"] == "removed"]

    if args.json:
        print(json.dumps({"findings": findings, "invisible_removed": len(invisible),
                          "clean": not findings}, indent=2))
    else:
        if not findings:
            print("Clean. No invisible characters or typographic substitutions found.")
        else:
            print("{} character{} found.\n".format(len(findings), "" if len(findings) == 1 else "s"))
            for (cp, name, action), n in sorted(summarize(findings).items(),
                                                key=lambda kv: -kv[1]):
                print("  {:>4}x  {:<9} {:<34} {}".format(n, cp, name, action))
            lines = sorted({f["line"] for f in invisible})
            if lines:
                print("\nInvisible characters on line{}: {}".format(
                    "" if len(lines) == 1 else "s",
                    ", ".join(str(n) for n in lines[:20]) + (" ..." if len(lines) > 20 else "")))
            if not args.fix:
                print("\nRun again with --fix to apply.")

    if args.fix:
        dest = args.output or (None if args.path == "-" else args.path)
        if dest is None:
            sys.stdout.write(cleaned)
        else:
            with open(dest, "w", encoding="utf-8") as fh:
                fh.write(cleaned)
            if not args.json:
                print("\nWrote {}".format(dest))
        return 0
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
