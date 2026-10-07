#!/usr/bin/env python3
"""Deterministic AI-slop linter. Zero dependencies, Python 3.8+.

Reports every observable slop pattern in a prose file with a line number, the
matched text, and the fix. Scores the draft with fixed arithmetic so the same
findings always produce the same score.

Usage:
    python3 slopcheck.py DRAFT.md
    python3 slopcheck.py DRAFT.md --json
    python3 slopcheck.py DRAFT.md --gate 90
    echo "text" | python3 slopcheck.py -

Exit codes: 0 = passed the gate, 1 = failed the gate, 2 = usage error.
"""

import argparse
import json
import os
import re
import sys

RULES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules.json")

SEVERITY_ORDER = ["note", "minor", "major", "blocker"]

# Abbreviations that end in a period without ending a sentence.
ABBREV = r"(?<!\b[A-Z])(?<!\bMr)(?<!\bMs)(?<!\bDr)(?<!\bSt)(?<!\bvs)(?<!\betc)(?<!\bi\.e)(?<!\be\.g)(?<!\bFig)(?<!\bNo)"
SENTENCE_SPLIT = re.compile(ABBREV + r"(?<=[.!?])[\"')\]]*\s+(?=[A-Z\"'(\[])")

IGNORE_DIRECTIVE = re.compile(r"<!--\s*slop-ignore\s+([A-Za-z0-9,\s]+?)\s*-->")


# --------------------------------------------------------------------------
# Masking: never flag text the writer did not author as prose.
# --------------------------------------------------------------------------

def mask_regions(text):
    """Replace non-prose regions with spaces, preserving offsets and newlines.

    Fenced code, indented code, inline code, YAML frontmatter, blockquotes,
    link targets, and HTML comments are quoted or technical material. Flagging
    them produces noise and, worse, invites edits that break meaning.
    """
    chars = list(text)

    def blank(start, end):
        for i in range(start, min(end, len(chars))):
            if chars[i] != "\n":
                chars[i] = " "

    # YAML frontmatter
    if text.startswith("---"):
        m = re.search(r"\A---\n.*?\n---\n", text, re.DOTALL)
        if m:
            blank(m.start(), m.end())

    for pattern, flags in [
        (r"^```.*?^```", re.DOTALL | re.MULTILINE),   # fenced code
        (r"^~~~.*?^~~~", re.DOTALL | re.MULTILINE),   # fenced code, tildes
        (r"<!--.*?-->", re.DOTALL),                    # HTML comments
        (r"`[^`\n]+`", 0),                             # inline code
        (r"^(?:\t| {4,})\S.*$", re.MULTILINE),         # indented code
        (r"^\s*>.*$", re.MULTILINE),                   # blockquotes
        (r"\]\([^)\s]+\)", 0),                         # link targets
        (r"https?://\S+", 0),                          # bare URLs
        (r"\"(?:[^\"\n]|\n(?!\s*\n))" + r"{1,400}\"", 0),                     # quoted material
        (r"\u201c(?:[^\u201d\n]|\n(?!\s*\n))" + r"{1,400}\u201d", 0),                     # quoted material, curly
    ]:
        for m in re.finditer(pattern, text, flags):
            blank(m.start(), m.end())

    return "".join(chars)


def suppressed_rules(lines):
    """Map line index -> set of rule ids suppressed on that line.

    A directive at the end of a line covers that line and the next one. A
    directive alone on its own line covers the whole paragraph that follows,
    which is what you want when the sentence you are excusing wraps.
    """
    out = {}
    for i, line in enumerate(lines):
        m = IGNORE_DIRECTIVE.search(line)
        if not m:
            continue
        ids = {r.strip().upper() for r in m.group(1).split(",") if r.strip()}
        out.setdefault(i, set()).update(ids)
        if IGNORE_DIRECTIVE.sub("", line).strip():
            out.setdefault(i + 1, set()).update(ids)
            continue
        for j in range(i + 1, len(lines)):
            if not lines[j].strip():
                break
            out.setdefault(j, set()).update(ids)
    return out


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------

def build_matchers(rules):
    compiled = []
    for rule in rules:
        kind = rule["kind"]
        if kind == "words":
            items = sorted(rule["items"], key=len, reverse=True)
            body = "|".join(re.escape(w).replace(r"\-", "-") for w in items)
            rx = [re.compile(r"(?<![\w-])(?:" + body + r")(?![\w-])", re.IGNORECASE)]
            rx += [re.compile(p, re.IGNORECASE) for p in rule.get("extra_patterns", [])]
        elif kind == "phrases":
            items = sorted(rule["items"], key=len, reverse=True)
            # Tolerate any whitespace run and either apostrophe form.
            parts = []
            for phrase in items:
                esc = re.escape(phrase)
                esc = esc.replace(r"\ ", r"\s+").replace(r"'", r"['’]")
                parts.append(esc)
            rx = [re.compile(r"(?<![\w-])(?:" + "|".join(parts) + r")(?![\w-])", re.IGNORECASE)]
        elif kind == "opener":
            items = sorted(rule["items"], key=len, reverse=True)
            body = "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in items)
            rx = [re.compile(r"(?:" + body + r")(?=\s*[,:]?\s)", re.IGNORECASE)]
        elif kind == "density":
            rx = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in rule["patterns"]]
        elif kind == "regex":
            # A few rules key off capitalization: a list of proper nouns is a
            # list of things, not a rhetorical tricolon.
            flags = re.MULTILINE if rule.get("case_sensitive") else re.IGNORECASE | re.MULTILINE
            rx = [re.compile(p, flags) for p in rule["patterns"]]
        else:
            continue
        compiled.append((rule, rx))
    return compiled


def line_index(text):
    starts = [0]
    for m in re.finditer(r"\n", text):
        starts.append(m.end())
    return starts


def locate(starts, pos):
    lo, hi = 0, len(starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if starts[mid] <= pos:
            lo = mid
        else:
            hi = mid - 1
    return lo, pos - starts[lo]


SKIP_BLOCK = re.compile(r"^\s{0,3}(?:#{1,6}\s|\||[-*+]\s|\d+[.)]\s|\[)")


def paragraphs(masked):
    """Yield (offset, text) for each prose paragraph, newlines flattened.

    Prose wraps across lines. Treating each line as a sentence invents short
    fragments out of ordinary word wrap, which the rhythm checks then read as
    manufactured punch. Flattening single newlines to spaces keeps every offset
    intact while restoring the real sentence boundaries.
    """
    flow = re.sub(r"(?<!\n)\n(?!\n)", " ", masked)
    for block in re.finditer(r"[^\n]+", flow):
        text = block.group(0)
        if not text.strip() or SKIP_BLOCK.match(text):
            continue
        yield block.start(), text


def sentence_spans(masked):
    """Yield (start, end, text) for each prose sentence in the masked text."""
    for offset, block in paragraphs(masked):
        cursor = 0
        for piece in SENTENCE_SPLIT.split(block):
            start = block.find(piece, cursor)
            if start < 0:
                continue
            cursor = start + len(piece)
            if piece.strip():
                yield offset + start, offset + cursor, piece.strip()


def find_lexical(compiled, masked, starts, suppress):
    findings = []
    for rule, regexes in compiled:
        if rule["kind"] == "density":
            continue
        rid = rule["id"]
        for rx in regexes:
            for m in rx.finditer(masked):
                if not m.group(0).strip():
                    continue
                line, col = locate(starts, m.start())
                if rid in suppress.get(line, ()) or "ALL" in suppress.get(line, ()):
                    continue
                findings.append({
                    "rule": rid,
                    "name": rule["name"],
                    "severity": rule["severity"],
                    "line": line + 1,
                    "col": col + 1,
                    "start": m.start(),
                    "end": m.end(),
                    "match": " ".join(m.group(0).split())[:90],
                    "fix": rule["fix"],
                })
    return findings


def find_invisible(raw, starts, suppress):
    """Invisible characters are checked against the raw text, not the masked copy.

    A zero-width space inside a code fence is still a zero-width space, and it
    will break whoever copies that snippet.
    """
    try:
        from sanitize import scan
    except ImportError:
        return []
    _, hits = scan(raw)
    findings = []
    seen = set()
    for h in hits:
        if h["category"] != "invisible" or h["action"] != "removed":
            continue
        line, col = locate(starts, h["offset"])
        if "U1" in suppress.get(line, ()) or "ALL" in suppress.get(line, ()):
            continue
        if line in seen:
            continue
        seen.add(line)
        findings.append({
            "rule": "U1", "name": "Invisible character", "severity": "major",
            "line": line + 1, "col": col + 1,
            "start": h["offset"], "end": h["offset"] + 1,
            "match": "{} ({})".format(h["codepoint"], h["name"]),
            "fix": "Run scripts/sanitize.py --fix. These break grep, diffs, and copy-paste.",
        })
    return findings


def find_density(compiled, masked, starts, suppress, words):
    """Some devices are only slop in aggregate.

    "Rather than" is correct English. Three of them in 242 words is a writer who
    cannot state a claim without a foil. Per-occurrence matching cannot see that,
    because every individual instance is defensible. Rate can.
    """
    findings = []
    for rule, regexes in compiled:
        if rule["kind"] != "density" or not words:
            continue
        hits = sorted((m.start(), m.group(0)) for rx in regexes for m in rx.finditer(masked))
        rate = len(hits) * 1000.0 / words
        if len(hits) < rule.get("min_count", 3) or rate < rule["threshold_per_1000"]:
            continue
        line, col = locate(starts, hits[0][0])
        if rule["id"] in suppress.get(line, ()) or "ALL" in suppress.get(line, ()):
            continue
        lines = sorted({locate(starts, pos)[0] + 1 for pos, _ in hits})
        findings.append({
            "rule": rule["id"], "name": rule["name"], "severity": rule["severity"],
            "line": line + 1, "col": col + 1, "start": hits[0][0], "end": hits[0][0] + 1,
            "match": "{} occurrences, {:.1f} per 1000 words (lines {})".format(
                len(hits), rate, ", ".join(str(n) for n in lines[:12])),
            "fix": rule["fix"],
        })
    return findings


def find_rhythm(masked, starts, suppress):
    """Uniform sentence length is the tell no wordlist catches.

    Three consecutive sentences within two words of each other reads as a
    metronome. So does a run of four or more sentences under six words.
    """
    findings = []
    sents = [(s, e, t) for s, e, t in sentence_spans(masked)]
    lengths = [len(t.split()) for _, _, t in sents]

    run = 1
    for i in range(1, len(lengths)):
        if abs(lengths[i] - lengths[i - 1]) <= 2 and lengths[i] >= 8:
            run += 1
        else:
            run = 1
        if run == 4:
            line, col = locate(starts, sents[i - 3][0])
            if "R1" not in suppress.get(line, ()) and "ALL" not in suppress.get(line, ()):
                findings.append({
                    "rule": "R1", "name": "Metronomic rhythm", "severity": "note",
                    "line": line + 1, "col": col + 1,
                    "start": sents[i - 3][0], "end": sents[i - 3][1],
                    "match": " ".join(sents[i - 3][2].split())[:90],
                    "fix": "Four consecutive sentences of near-identical length. Break one.",
                })

    run = 0
    for i, n in enumerate(lengths):
        run = run + 1 if n <= 6 else 0
        if run == 4:
            line, col = locate(starts, sents[i - 3][0])
            if "R2" not in suppress.get(line, ()) and "ALL" not in suppress.get(line, ()):
                findings.append({
                    "rule": "R2", "name": "Stacked fragments", "severity": "minor",
                    "line": line + 1, "col": col + 1,
                    "start": sents[i - 3][0], "end": sents[i - 3][1],
                    "match": " ".join(sents[i - 3][2].split())[:90],
                    "fix": "Four short sentences in a row reads as manufactured punch. Join some.",
                })
    return findings


def find_formatting(masked, starts, suppress):
    """Decoration that does not follow the content."""
    findings = []

    def add(rid, name, sev, pos, match, fix, end=None):
        line, col = locate(starts, pos)
        if rid in suppress.get(line, ()) or "ALL" in suppress.get(line, ()):
            return
        findings.append({"rule": rid, "name": name, "severity": sev, "line": line + 1,
                         "col": col + 1, "start": pos, "end": end if end is not None else pos + len(match),
                         "match": match[:90], "fix": fix})

    # Bold used mid-sentence for emphasis rather than as a label.
    for m in re.finditer(r"(?<![\n*])\s\*\*[^*\n]{1,60}[^*.:\n]\*\*(?![:.\n])", masked, re.MULTILINE):
        # A bold label that opens a list item, at any numbering depth, is structure.
        prefix = masked[masked.rfind("\n", 0, m.start()) + 1:m.start() + 1]
        if re.match(r"^\s*(?:[-*+]|\d+[.)])\s*$", prefix):
            continue
        add("F5", "Decorative bold", "note", m.start(), m.group(0).strip(),
            "Bold mid-sentence is decoration. Cut it or make the sentence carry the emphasis.")

    # A heading whose section is shorter than two sentences.
    heads = list(re.finditer(r"^\s{0,3}#{1,6}\s+.+$", masked, re.MULTILINE))
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(masked)
        body = masked[h.end():end].strip()
        if body and len(list(sentence_spans(body))) < 2 and len(body.split()) < 25:
            add("F6", "Heading over a stub", "note", h.start(), h.group(0).strip(),
                "A header over one or two sentences is scaffolding. Fold it into prose.")

    # Title Case headings.
    for h in heads:
        words = re.sub(r"^\s*#+\s*", "", h.group(0)).split()
        content = [w for w in words if len(w) > 3 and w[:1].isalpha()]
        if len(content) >= 3 and all(w[0].isupper() and not w.isupper() for w in content):
            add("F7", "Title Case heading", "note", h.start(), h.group(0).strip(),
                "Use sentence case unless it is a proper name.")

    return findings


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def dedupe(findings):
    """One observable problem counts once, at its highest applicable severity.

    A faux-insight setup that contains a weasel-attribution phrase is a single
    thing to fix. Counting it twice inflates the penalty and buries the real
    finding under a near-duplicate.
    """
    ranked = sorted(findings, key=lambda f: (-SEVERITY_ORDER.index(f["severity"]),
                                             f["start"] - f["end"], f["start"]))
    kept = []
    for f in ranked:
        covered = any(
            (k["start"] <= f["start"] and f["end"] <= k["end"])
            or (k["rule"] == f["rule"] and f["start"] < k["end"] and k["start"] < f["end"])
            for k in kept)
        if not covered:
            kept.append(f)
    return kept


def score(findings, cfg):
    sev_pts = cfg["severity_points"]
    rep_pts = cfg["repeat_points"]
    cap_mult = cfg["rule_cap_multiplier"]

    by_rule = {}
    for f in findings:
        by_rule.setdefault(f["rule"], []).append(f)

    lines = []
    total = 0.0
    for rid in sorted(by_rule):
        group = by_rule[rid]
        sev = group[0]["severity"]
        n = len(group)
        base = sev_pts[sev]
        raw = base + (n - 1) * rep_pts[sev]
        capped = min(raw, base * cap_mult)
        total += capped
        lines.append({
            "rule": rid, "name": group[0]["name"], "severity": sev, "count": n,
            "deduction": round(capped, 1),
            "arithmetic": "{} + {}x{} = {}{}".format(
                base, n - 1, rep_pts[sev], round(raw, 1),
                " capped at {}".format(base * cap_mult) if capped < raw else ""),
        })

    final = max(cfg["floor"], cfg["start"] - total)
    return round(final, 1), lines


def grade(value):
    for cut, letter in [(97, "A+"), (93, "A"), (90, "A-"), (87, "B+"), (83, "B"), (80, "B-"),
                        (77, "C+"), (73, "C"), (70, "C-"), (67, "D+"), (63, "D"), (60, "D-")]:
        if value >= cut:
            return letter
    return "F"


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def render(result, show_fixes=True):
    out = []
    findings = result["findings"]
    if not findings:
        out.append("No slop patterns found. {}/100 ({}).".format(result["score"], result["grade"]))
        return "\n".join(out)

    out.append("{} finding{} across {} rule{}.".format(
        len(findings), "" if len(findings) == 1 else "s",
        len(result["breakdown"]), "" if len(result["breakdown"]) == 1 else "s"))
    out.append("")

    order = {s: i for i, s in enumerate(reversed(SEVERITY_ORDER))}
    for f in sorted(findings, key=lambda x: (order[x["severity"]], x["line"], x["col"])):
        out.append("  {}:{}  [{}] {} ({})".format(
            f["line"], f["col"], f["rule"], f["name"], f["severity"]))
        out.append('        "{}"'.format(f["match"]))
        if show_fixes:
            out.append("        -> {}".format(f["fix"]))
    out.append("")
    out.append("Score arithmetic (start 100):")
    for row in result["breakdown"]:
        out.append("  -{:<5} {} {} x{}  [{}]".format(
            row["deduction"], row["rule"], row["name"], row["count"], row["arithmetic"]))
    out.append("")
    out.append("Score: {}/100 ({}).  Gate: {} and no findings above {}.  {}".format(
        result["score"], result["grade"], result["gate_score"], result["gate_max_severity"],
        "PASS" if result["passed"] else "FAIL"))
    if not result["passed"] and result["blocking"]:
        out.append("Blocking: {}".format(", ".join(sorted(result["blocking"]))))
    return "\n".join(out)


def analyze(text, rules_path=RULES_PATH, gate_score=None, gate_max_severity=None):
    with open(rules_path, encoding="utf-8") as fh:
        spec = json.load(fh)
    cfg = dict(spec["scoring"])
    if gate_score is not None:
        cfg["gate_score"] = gate_score
    if gate_max_severity is not None:
        cfg["gate_max_severity"] = gate_max_severity

    masked = mask_regions(text)
    starts = line_index(text)
    suppress = suppressed_rules(text.split("\n"))
    compiled = build_matchers(spec["rules"])

    words = len(re.findall(r"\b[\w'-]+\b", masked))
    findings = find_invisible(text, starts, suppress)
    findings += find_lexical(compiled, masked, starts, suppress)
    findings += find_density(compiled, masked, starts, suppress, words)
    findings += find_rhythm(masked, starts, suppress)
    findings += find_formatting(masked, starts, suppress)
    findings = dedupe(findings)

    value, breakdown = score(findings, cfg)
    ceiling = SEVERITY_ORDER.index(cfg["gate_max_severity"])
    blocking = {f["rule"] for f in findings if SEVERITY_ORDER.index(f["severity"]) > ceiling}
    passed = value >= cfg["gate_score"] and not blocking

    return {
        "score": value,
        "grade": grade(value),
        "passed": passed,
        "gate_score": cfg["gate_score"],
        "gate_max_severity": cfg["gate_max_severity"],
        "blocking": sorted(blocking),
        "word_count": words,
        "findings_per_1000_words": round(len(findings) * 1000.0 / words, 1) if words else 0.0,
        "findings": findings,
        "breakdown": breakdown,
    }


def main():
    ap = argparse.ArgumentParser(description="Deterministic AI-slop linter.")
    ap.add_argument("path", help="File to check, or - for stdin.")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    ap.add_argument("--gate", type=float, default=None, help="Minimum passing score (default 90).")
    ap.add_argument("--max-severity", choices=SEVERITY_ORDER, default=None,
                    help="Highest severity allowed through the gate (default minor).")
    ap.add_argument("--quiet", action="store_true", help="Omit fix suggestions.")
    ap.add_argument("--rules", default=RULES_PATH, help="Alternate rules.json.")
    args = ap.parse_args()

    if args.path == "-":
        text = sys.stdin.read()
    else:
        if not os.path.isfile(args.path):
            sys.stderr.write("No such file: {}\n".format(args.path))
            return 2
        with open(args.path, encoding="utf-8") as fh:
            text = fh.read()

    result = analyze(text, args.rules, args.gate, args.max_severity)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render(result, show_fixes=not args.quiet))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
