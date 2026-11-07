"""Fill the #10662 PR body from the template, the CI fills and the rendered impact runs.

Usage: python3 fill_pr_body.py RENDER_TXT OUT_MD [--runs DIR] [--wip "banner text"]

- Template: pr_body/pr_body_template.md. Its __NAME__ placeholders come from
  pr_body/fills.json, except __IMPACT__, which this script builds from
  RENDER_TXT, the output of render_reform_lists.py.
- The impact section copies the renderer's tables and state lines verbatim, so no
  figure passes through a hand edit. The prose around them names the runs; every
  number in it comes from RENDER_TXT too.
- Refuses to write if a placeholder stays unfilled, or if RENDER_TXT does not end in
  "N of N checks pass".
"""

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REVIEWS = HERE.parent / "pr_body"
POLICY_ORDER = [
    "Current law",
    "Texas rebate",
    "End Child Poverty Act",
    "EDAA End Child Poverty Act",
    "BOOST Act",
]


def blocks(text):
    """Split the render output into labelled blocks."""
    lines = text.splitlines()
    out = {"year_tables": {}, "decomposition": {}, "states": {}, "detail": {}}
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^### (\d{4})$", line)
        if m:
            year = m.group(1)
            j = i + 1
            while j < len(lines) and not lines[j].startswith("|"):
                j += 1
            k = j
            while k < len(lines) and lines[k].startswith("|"):
                k += 1
            out["year_tables"][year] = lines[j:k]
            i = k
            continue
        m = re.match(r"^Decomposition, (\d{4}) \(\$m\):", line)
        if m:
            year = m.group(1)
            j = i + 1
            while j < len(lines) and not lines[j].startswith("|"):
                j += 1
            k = j
            while k < len(lines) and lines[k].startswith("|"):
                k += 1
            out["decomposition"][year] = lines[j:k]
            i = k
            continue
        m = re.match(r"^Largest state changes in SPM benefits, (\d{4}) \(\$m\):", line)
        if m:
            year = m.group(1)
            j = i + 1
            body = []
            while j < len(lines) and not re.match(r"^(Own benefit|### |Decomposition|Largest|## )", lines[j]):
                if lines[j].strip():
                    body.append(lines[j])
                j += 1
            out["states"][year] = body
            i = j
            continue
        m = re.match(r"^Own benefit and poverty detail, (\d{4}):", line)
        if m:
            year = m.group(1)
            j = i + 1
            while j < len(lines) and not lines[j].startswith("|"):
                j += 1
            k = j
            while k < len(lines) and lines[k].startswith("|"):
                k += 1
            out["detail"][year] = lines[j:k]
            i = k
            continue
        i += 1
    m = re.search(r"^Before \(main\): \['(\w+)'\]; after \(branch\): \['(\w+)'\]$", text, re.M)
    out["commits"] = (m.group(1), m.group(2)) if m else None
    m = re.search(r"^Dataset: \['([^']+)'\]$", text, re.M)
    out["dataset"] = m.group(1) if m else None
    m = re.search(r"^(\d+) of (\d+) checks pass$", text, re.M)
    out["checks"] = (int(m.group(1)), int(m.group(2))) if m else None
    return out


def policies_in(table):
    return [row.split("|")[1].strip() for row in table[2:]]


def acp_ebb_zero(runs_dir, year):
    """True when every saved run for this year records no ACP or EBB payments."""
    found = False
    for f in Path(runs_dir).glob("*_*.json"):
        row = json.loads(f.read_text())["years"].get(year)
        if row is None:
            continue
        found = True
        if row["acp"] != 0 or row["ebb"] != 0:
            return False
    return found


def tx_senior_note(probe_log):
    """Why senior SPM poverty under the Texas rebate equals current law's rate,
    from tx_only_probe.py's run of the Texas households alone."""
    text = Path(probe_log).read_text()
    subset, national = re.search(
        r"Texas SPM benefits, current law \(\$bn\): subset ([\d.]+) national run ([\d.]+)", text
    ).groups()
    if subset != national:
        sys.exit("refusing: the Texas-only run does not reproduce the national run's Texas totals")
    m = re.search(
        r"seniors 65\+: .*?poor under current law (\d+) records \(([\d,]+)\); under the rebate (\d+) \(([\d,]+)\); "
        r"poor records whose gap is below what the rebate adds: (\d+)\n"
        r"\s+poor records' gaps \(\$\): min ([\d,]+),.*\n"
        r"\s+what the rebate adds to poor records' resources \(\$\): min [\d,]+, median [\d,]+, max ([\d,]+)",
        text,
    )
    poor, _, poor_rebate, _, crossing, min_gap, max_added = m.groups()
    if poor != poor_rebate or crossing != "0":
        sys.exit("refusing: the Texas-only run shows seniors leaving poverty under the rebate")
    return (
        f"Under the Texas rebate, senior SPM poverty after the fix equals current law's rate. "
        f"The rebate adds up to ${max_added} to each poor senior's resources, but in a run of the "
        f"Texas households alone (`tx_only_probe.py`, which reproduces the national run's Texas SPM "
        f"benefits, ${national}bn), the closest of the {poor} poor Texas senior records falls "
        f"${min_gap} short of its threshold, so none crosses it."
    )


STATE_NAMES = {
    "AK": "Alaska", "CA": "California", "CT": "Connecticut", "ME": "Maine",
    "MI": "Michigan", "MN": "Minnesota", "NH": "New Hampshire", "NJ": "New Jersey",
    "NV": "Nevada", "NY": "New York", "OK": "Oklahoma", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SD": "South Dakota", "UT": "Utah", "VT": "Vermont",
    "WA": "Washington", "WI": "Wisconsin", "WY": "Wyoming",
}


def probe_block(log, policy, year):
    """One fix_probe.py compare block: how many states its subset reproduces, and, by
    age group, the records that leave SPM poverty with the fix and their weight."""
    m = re.search(rf"^{policy} {year}: before at \w+, after at \w+\n((?:  .*\n?)+)", log, re.M)
    if not m:
        sys.exit(f"refusing: no {policy} {year} block in its probe log")
    block = m.group(1)
    reproduced = re.findall(
        r"^  (?:before|after): subset reproduces the national run's SPM benefits in all "
        r"(\d+) states, largest gap \$([\d,]+)$",
        block,
        re.M,
    )
    if len(reproduced) != 2 or any(int(gap.replace(",", "")) > 1_000 for _, gap in reproduced):
        sys.exit(f"refusing: the {policy} {year} subset does not reproduce its national run")
    groups = re.findall(
        r"^  (children|adults 18-64|seniors 65\+): .*?leave poverty (\d+) \(([\d,]+)\); "
        r"enter (\d+) \(([\d,]+)\)$",
        block,
        re.M,
    )
    if len(groups) != 3 or any(n != "0" for *_, n, _ in groups):
        sys.exit(f"refusing: the {policy} {year} block lacks a group, or someone enters poverty")
    leave = {label: (int(n), int(w.replace(",", ""))) for label, n, w, _, _ in groups}
    return int(reproduced[0][0]), leave


def national_change(runs_dir, policy, year, key):
    before, after = (
        json.loads((Path(runs_dir) / f"{policy}_{side}.json").read_text())["years"][year][key]
        for side in ("before", "after")
    )
    return after - before


def ecpa_child_note(runs_dir):
    """Why child SPM poverty under both End Child Poverty Act versions does not move
    with the fix in 2027, from fix_probe.py's runs of the states the fix reaches and
    ecpa_child_detail.py's summary of them."""
    runs_dir = Path(runs_dir)
    ecpa_log = (runs_dir / "ecpa_probe/probe.log").read_text()
    edaa_log = (runs_dir / "edaa_probe/probe.log").read_text()
    blocks_ = {
        ("end_child_poverty_act", "2027"): probe_block(ecpa_log, "end_child_poverty_act", "2027"),
        ("end_child_poverty_act", "2024"): probe_block(ecpa_log, "end_child_poverty_act", "2024"),
        ("edaa_end_child_poverty_act", "2027"): probe_block(
            edaa_log, "edaa_end_child_poverty_act", "2027"
        ),
    }
    for (policy, year), (_, leave) in blocks_.items():
        # The probe logs round each group's weight to a person.
        people = -national_change(runs_dir, policy, year, "people_in_spm_poverty")
        if abs(sum(w for _, w in leave.values()) - people) > 2:
            sys.exit(f"refusing: the {policy} {year} probe misses people the national run counts")
    states, leave27 = blocks_[("end_child_poverty_act", "2027")]
    if blocks_[("edaa_end_child_poverty_act", "2027")] != (states, leave27):
        sys.exit("refusing: the two versions' 2027 probes differ")
    if len({n for n, _ in blocks_.values()}) != 1 or states != len(STATE_NAMES):
        sys.exit("refusing: the probes do not cover the same states")
    for policy in ("end_child_poverty_act", "edaa_end_child_poverty_act"):
        if abs(national_change(runs_dir, policy, "2027", "child_spm_percent")) >= 1e-8:
            sys.exit(f"refusing: child SPM poverty moves under {policy} in 2027")
    d = json.loads((runs_dir / "ecpa_probe/child_detail.json").read_text())
    c27, e27, light = d["crossing_2027"], d["crossing_2027_edaa"], d["light_children_2027"]
    if not (
        e27["same_records"]
        and c27["records"] == e27["records"] == leave27["children"][0]
        and c27["weight"] == e27["weight"] < 0.01
    ):
        sys.exit("refusing: child_detail.json and the probe logs disagree on 2027's children")
    c24, h = d["crossing_2024"], d["heaviest_2024"]
    h24, h27 = h["2024"], h["2027"]
    if round(c24["weight"]) != blocks_[("end_child_poverty_act", "2024")][1]["children"][1]:
        sys.exit("refusing: child_detail.json and the probe log disagree on 2024's children")
    if not (h24["poor_before"] and not h24["poor_after"] and h27["poor_before"] and h27["poor_after"]):
        sys.exit("refusing: the 2024 family's crossings differ from what the note says")
    rest = c24["weight"] - h24["weight"]
    if rest > 1:
        sys.exit("refusing: the 2024 family does not account for nearly all of that year's change")
    people27 = -national_change(runs_dir, "end_child_poverty_act", "2027", "people_in_spm_poverty")
    threshold_growth = 100 * (h27["threshold"] / h24["threshold"] - 1)
    resource_growth = 100 * (h27["resources_before"] / h24["resources_before"] - 1)
    return (
        f"Under both End Child Poverty Act versions, the fix lifts {people27:,.0f} people out "
        f"of SPM poverty in 2027, yet the child rate moves by less than 10⁻⁸ percentage "
        f"points. Runs of the {states} states where the fix changes SPM benefits "
        f"(`fix_probe.py`, which reproduces each national run's SPM benefits in every one of "
        f"them) show why. Under either version, the people who leave poverty in 2027 comprise "
        f"{leave27['adults 18-64'][1]:,} adults and {leave27['seniors 65+'][1]:,} seniors. "
        f"The fix also lifts the same {c27['records']} child records under both versions, "
        f"but their weights sum to {c27['weight']:.3f} people: in those states "
        f"{light['under_one']:,} of {light['records']:,} child records carry weights under "
        f"one person, together {light['under_one_weight']:,.0f} of "
        f"{light['children'] / 1e6:.1f} million children. In 2024, under the End Child "
        f"Poverty Act, the fix lifts {c24['weight']:,.0f} children out of poverty, and one "
        f"record, a {h24['age']:.0f}-year-old in {STATE_NAMES[h24['state']]}, accounts for "
        f"all but {rest:.2f} of them. That family's resources fall ${h24['gap']:,.0f} short "
        f"of its threshold, and the fix adds ${h24['rise']:,.0f}. By 2027 its threshold "
        f"grows {threshold_growth:.1f}% and its resources {resource_growth:.1f}%, so the gap "
        f"reaches ${h27['gap']:,.0f} and the same ${h27['rise']:,.0f} leaves the family in "
        f"poverty."
    )


def impact_section(render, runs_dir):
    b = blocks(render)
    if not b["checks"] or b["checks"][0] != b["checks"][1]:
        sys.exit(f"refusing: the renderer's checks did not all pass ({b['checks']})")
    before, after = b["commits"]
    runs = sum(len(policies_in(t)) for t in b["year_tables"].values()) * 2
    parts = []
    parts.append(
        f"Every figure here comes from a full microsimulation of one policy and year on "
        f"`{b['dataset']}`: {runs} runs, one per policy, year and side. They measure this "
        f"PR's change on main as of {before}: the before runs use {before}, and the after "
        f"runs use this branch at {after}, which is {before} plus this PR's model changes. "
        f"Since then the branch has changed tests and the Makefile, merged main's later "
        f"commits, which change none of this PR's files apart from one test, and added the "
        f"two calls that mark the benefit lists modified. Core reads that flag only when a "
        f"simulation turns its macro cache on, and these runs leave it off, so the two calls "
        f"change no figure here. The script, "
        f"`reform_lists.py`, records each run's commit and dataset, and "
        f"`render_reform_lists.py` builds these tables and checks from its output. "
        f"Poverty rates give the weighted share of people in SPM poverty, counting everyone under 18 as a child and everyone 65 or older as a senior."
    )
    if not all(acp_ebb_zero(runs_dir, year) for year in b["year_tables"]):
        sys.exit("refusing: a run records ACP or EBB payments")
    for year in sorted(b["year_tables"], reverse=True):
        parts.append(f"### {year}")
        if year == "2024":
            parts.append(
                "The End Child Poverty Act only, in a year when ACP still paid: the "
                "model reads each year's caps on January 1, when ACP's stood at $30 a "
                "month, $75 on Tribal lands. EBB's cap reaches zero in March 2022 and "
                "ACP's in June 2024, so EBB pays nothing in either year and ACP nothing "
                "in 2027. ACP pays the lesser of its cap and the family's broadband cost "
                "after Lifeline, and the pinned dataset carries no broadband costs, so "
                "ACP pays nothing in 2024 either: every run here records no ACP or EBB "
                "payments. The old copies' double count of them therefore changes no "
                "figure in these tables; the three Tlaib YAML files and invariant 5 "
                "check it for families that receive ACP or EBB."
            )
        parts.append("\n".join(b["year_tables"][year]))
    parts.append("### Where each change comes from")
    parts.append(
        "Each change in an aggregate equals the total of the programs the old copy "
        "lacked, minus the total of those it counted that the baseline does not. "
        "The copies' gaps account for every dollar, to within a few hundred dollars "
        "of float32 rounding:"
    )
    for year in sorted(b["decomposition"], reverse=True):
        parts.append(f"{year} ($m):\n\n" + "\n".join(b["decomposition"][year]))
    for year in sorted(b["states"], reverse=True):
        lines = b["states"][year]
        if lines:
            parts.append(f"Largest state changes in SPM benefits, {year} ($m):\n\n" + "\n".join(lines))
    for year in sorted(b["detail"], reverse=True):
        if b["detail"][year]:
            note = ""
            if year == "2027" and any(row.startswith("| Texas rebate |") for row in b["detail"][year]):
                note = "\n\n" + tx_senior_note(Path(runs_dir) / "tx_only_probe/probe.log")
            if year == "2027" and any(
                row.startswith("| End Child Poverty Act |") for row in b["detail"][year]
            ):
                note += "\n\n" + ecpa_child_note(runs_dir)
            parts.append(
                f"<details><summary>Own benefit and poverty detail, {year}</summary>\n\n"
                + "\n".join(b["detail"][year])
                + note
                + "\n\n</details>"
            )
    checks = b["checks"][1]
    parts.append(
        f"The renderer ran {checks} checks on these runs, and all pass. Among them: "
        f"under current law every recorded number, state totals included, matches "
        f"before and after; each reform's own benefit, market incomes, population, "
        f"`household_state_benefits` and every program's total match on both sides; "
        f"each change in net income equals the change in the benefit aggregate it "
        f"adds; and the branch's list parameter holds the 77 baseline programs plus "
        f"only the policy's own addition."
    )
    return "\n\n".join(parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("render")
    parser.add_argument("--runs", default=str(HERE.parent / "runs"))
    parser.add_argument("out")
    parser.add_argument("--wip", default=None)
    args = parser.parse_args()
    template = (REVIEWS / "pr_body_template.md").read_text()
    fills = json.loads((REVIEWS / "fills.json").read_text())
    body = template.replace("__IMPACT__", impact_section(Path(args.render).read_text(), args.runs))
    for key, value in fills.items():
        if key.startswith("__"):
            body = body.replace(key, value)
    left = sorted(set(re.findall(r"__[A-Z_]+__", body)))
    if left:
        sys.exit(f"refusing: unfilled placeholders {left}")
    if args.wip:
        body = f"**WIP: {args.wip}**\n\n" + body
    Path(args.out).write_text(body.rstrip("\n") + "\n")
    print(f"wrote {args.out} ({len(body)} characters)")


if __name__ == "__main__":
    main()
