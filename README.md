# Reform benefit list copies

Four structural reforms in policyengine-us replaced `spm_unit_benefits` with their own copies of its program list: the Texas rebate, the End Child Poverty Act, its Economic Dignity for All Agenda version and the BOOST Act. The copies fell behind current law, so under each reform the programs a copy lacked dropped out of SPM resources. [PolicyEngine/policyengine-us#10662](https://github.com/PolicyEngine/policyengine-us/pull/10662) moves the list into a parameter, and each reform now adds only its own benefit to it. This repository holds the runs that measure what that change does to each reform's results, with the scripts that produce and check them.

## Runs

Each run computes one policy for one year on the Populace file at `hf://datasets/policyengine/populace-us/populace_us_2024.h5@populace-us-2024-spm-20260909`, with policyengine-us at one of two commits:

- before: main at `e53b426082`;
- after: `ee75695b5a`, which adds the PR's model changes to `e53b426082`.

Twelve runs cover current law and the four reforms in 2027, and the End Child Poverty Act in 2024. `runs/render_final.txt` holds the impact tables and the 106 checks that `render_reform_lists.py` runs on them, and every check passes.

## Files

| Path | Contents |
|---|---|
| `scripts/reform_lists.py` | Runs one policy and year and writes national, state and program totals to `runs/<policy>_<side>.json`. |
| `scripts/run_all.sh` | Runs all twelve. |
| `scripts/render_reform_lists.py`, `scripts/copy_gaps.py` | Build the impact tables and their checks from the run files. |
| `scripts/fill_pr_body.py`, `pr_body/` | Fill the PR description from its template, the CI figures in `fills.json` and the rendered tables. |
| `scripts/fix_probe.py`, `scripts/ecpa_child_detail.py` | Rerun both End Child Poverty Act versions on the 19 states where the change moves SPM benefits, and count who leaves poverty. Output in `runs/ecpa_probe/` and `runs/edaa_probe/`. |
| `scripts/tx_only_probe.py` | Runs current law and the Texas rebate on Texas households alone. Output in `runs/tx_only_probe/`. |
| `scripts/flag_paths.py` | Prints which benefit lists each reformed system marks modified. `runs/flag_paths_2080a2eb6c.txt` comes from the branch before it marked them, and `runs/flag_paths_24b3d552fd.txt` from the PR head. |
| `scripts/mutate_helper.py` | Runs the PR's property test for `add_to_list_parameter` against fourteen broken versions of the helper. Output in `runs/mutate_helper_24b3d552fd.txt`. |
| `scripts/yaml_on_main.sh` | Runs the PR's four reform YAML files against main's code. Output in `runs/yaml_main.txt`. |

## Reproduce

The runs used Python 3.14 and policyengine-core 3.34.2, with each policyengine-us checkout on `PYTHONPATH`. Each national run's memory footprint peaked between 13 and 32 GB.

```bash
git clone https://github.com/PolicyEngine/reform-benefit-list-copies
git clone https://github.com/PolicyEngine/policyengine-us
git -C policyengine-us worktree add ../pe-us-before e53b426082
git -C policyengine-us worktree add ../pe-us-after ee75695b5a
git -C policyengine-us fetch origin pull/10662/head
git -C policyengine-us worktree add ../pe-us-head 24b3d552fd
(cd pe-us-after && uv sync --extra dev && uv pip install pytest policyengine-core==3.34.2)
export MAIN_TREE=$PWD/pe-us-before AFTER_TREE=$PWD/pe-us-after PY=$PWD/pe-us-after/.venv/bin/python
cd reform-benefit-list-copies
```

The national runs and their tables (`reform_lists.py` skips any year its output file already holds):

```bash
rm runs/*_before.json runs/*_after.json
scripts/run_all.sh
$PY scripts/render_reform_lists.py runs > runs/render_final.txt
```

The state probes:

```bash
SRC=$($PY -c "from huggingface_hub import hf_hub_download; print(hf_hub_download('policyengine/populace-us', 'populace_us_2024.h5', repo_type='dataset', revision='populace-us-2024-spm-20260909'))")
$PY scripts/fix_probe.py subset $SRC runs/ecpa_probe end_child_poverty_act 2024 2027
$PY scripts/fix_probe.py subset $SRC runs/edaa_probe edaa_end_child_poverty_act 2027
for run in "ecpa_probe end_child_poverty_act 2027" "ecpa_probe end_child_poverty_act 2024" "edaa_probe edaa_end_child_poverty_act 2027"; do
  read -r dir policy year <<<"$run"
  PYTHONPATH=$MAIN_TREE $PY scripts/fix_probe.py run runs/$dir $policy $year before
  PYTHONPATH=$AFTER_TREE $PY scripts/fix_probe.py run runs/$dir $policy $year after
  $PY scripts/fix_probe.py compare runs/$dir $policy $year
done
$PY scripts/ecpa_child_detail.py runs/ecpa_probe runs/edaa_probe
PYTHONPATH=$AFTER_TREE $PY scripts/tx_only_probe.py $SRC runs/tx_only_probe
```

The flag and mutation checks on the PR head, and its YAML files on main:

```bash
export HEAD_TREE=$(cd ../pe-us-head && pwd)
PYTHONPATH=$HEAD_TREE $PY scripts/flag_paths.py
PYTHONPATH=$HEAD_TREE $PY scripts/mutate_helper.py
PYTHONPATH=$HEAD_TREE $PY scripts/mutate_helper.py --random
scripts/yaml_on_main.sh
```

`mutate_helper.py` runs Hypothesis derandomized, as CI does, unless given `--random`.
