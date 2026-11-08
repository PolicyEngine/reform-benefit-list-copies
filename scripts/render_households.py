"""Tables from two household_omissions.py runs (before and after the fix).

Usage: python render_households.py BEFORE.json AFTER.json [OUT.md]

Exits 1 if the after run fails a check:
- each program's input reads back as the amount in its household;
- under each reform, every omitted program (and ACP and EBB) changes each total
  between the twins by exactly what it changes under current law;
- under each reform, each benefit total for the household without the program
  exceeds current law's by the reform's own payment and nothing else.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from household_omissions import COUNTED_TWICE, MISSING, PROGRAMS, TOTALS  # noqa: E402

TOLERANCE = 0.01
BENEFIT_TOTALS = ("spm_unit_benefits", "household_benefits")


def delta(rows, reform, total, program):
    levels = rows[reform]["levels"][total]
    return levels[f"{program}-with"] - levels[f"{program}-without"]


def own_payment(rows, reform, key):
    return sum(values[key] for values in rows[reform]["own"].values())


def main():
    before, after = (json.loads(Path(p).read_text()) for p in sys.argv[1:3])
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    lines, failures = [], []
    say = lines.append
    say(f"Before: `{before['commit'][:10]}` ({before['tree']}).")
    say(f"After: `{after['commit'][:10]}` ({after['tree']}).")
    say(f"Each program: ${after['amount']:,.0f} to one of two otherwise identical households.")
    say("")
    for year in sorted(after["years"]):
        b, a = before["years"][year], after["years"][year]
        # Inputs held, in both runs.
        for label, run in (("before", b), ("after", a)):
            for reform, row in run.items():
                for program, value in row["read_back"].items():
                    if abs(value - after["amount"]) > TOLERANCE:
                        failures.append(f"{year} {label} {reform}: {program} reads {value}")
        say(f"### {year}")
        say("")
        say(
            "| Reform | Total | Programs the copy left out | Counted as current law does, before | After | Largest gap after ($) |"
        )
        say("|---|---|---:|---:|---:|---:|")
        for reform, by_total in MISSING.items():
            for total, programs in by_total.items():
                matches_before = sum(
                    abs(delta(b, reform, total, p) - delta(b, "baseline", total, p))
                    <= TOLERANCE
                    for p in programs
                )
                gaps_after = [
                    abs(delta(a, reform, total, p) - delta(a, "baseline", total, p))
                    for p in programs
                ]
                matches_after = sum(g <= TOLERANCE for g in gaps_after)
                say(
                    f"| {reform} | `{total}` | {len(programs)} | {matches_before} | "
                    f"{matches_after} | {max(gaps_after):,.2f} |"
                )
        say("")
        # Every program, every total, every reform, after the fix.
        for reform in MISSING:
            for program in PROGRAMS:
                for total in TOTALS:
                    gap = delta(a, reform, total, program) - delta(
                        a, "baseline", total, program
                    )
                    if abs(gap) > TOLERANCE:
                        failures.append(
                            f"{year} after {reform}: {program} moves {total} by "
                            f"{delta(a, reform, total, program):,.2f}, current law by "
                            f"{delta(a, 'baseline', total, program):,.2f}"
                        )
        # ACP and EBB: counted twice in SPM net income before, once after.
        say("ACP and EBB, change in `spm_unit_net_income` from the program's $1,000:")
        say("")
        say("| Reform | Program | Current law | Reform, before | Reform, after |")
        say("|---|---|---:|---:|---:|")
        for reform in MISSING:
            for program in COUNTED_TWICE:
                say(
                    f"| {reform} | `{program}` | "
                    f"{delta(a, 'baseline', 'spm_unit_net_income', program):,.2f} | "
                    f"{delta(b, reform, 'spm_unit_net_income', program):,.2f} | "
                    f"{delta(a, reform, 'spm_unit_net_income', program):,.2f} |"
                )
        say("")
        # Levels: the reform adds its own payment to each benefit total.
        say(
            "Benefit totals for the households without the program: reform less "
            "current law, against the reform's own payment (largest gap over "
            f"{len(PROGRAMS)} households):"
        )
        say("")
        say("| Reform | Own payment per household ($) | `spm_unit_benefits` gap before | after | `household_benefits` gap before | after |")
        say("|---|---|---:|---:|---:|---:|")
        for reform in MISSING:
            keys = [f"{p}-without" for p in PROGRAMS]
            own_after = sorted({round(own_payment(a, reform, k), 2) for k in keys})
            cells = []
            for total in BENEFIT_TOTALS:
                for label, run in (("before", b), ("after", a)):
                    gaps = [
                        abs(
                            run[reform]["levels"][total][k]
                            - run["baseline"]["levels"][total][k]
                            - own_payment(run, reform, k)
                        )
                        for k in keys
                    ]
                    cells.append(f"{max(gaps):,.2f}")
                    if label == "after" and max(gaps) > TOLERANCE:
                        failures.append(
                            f"{year} after {reform}: {total} differs from current "
                            f"law by more than the own payment ({max(gaps):,.2f})"
                        )
            say(f"| {reform} | {', '.join(f'{x:,.2f}' for x in own_after)} | " + " | ".join(cells) + " |")
        say("")
    say("Checks: " + ("all pass." if not failures else f"{len(failures)} FAIL"))
    for failure in failures:
        say(f"- {failure}")
    text = "\n".join(lines) + "\n"
    print(text)
    if out:
        out.write_text(text)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
