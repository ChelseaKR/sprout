# Submitted corpus proposals

This is where a submitted corpus proposal lives (research item E5). Drop one YAML file per
species here and open a PR:

```bash
uv run sprout propose template > proposals/my-plant.yaml
uv run sprout propose check proposals/my-plant.yaml   # review just this one
uv run sprout propose check                           # what CI runs: every proposal
```

`sprout propose check` with no arguments is the merge-blocking gate (`make propose-check`,
and the `propose-check` step of the `eval-a11y` CI job). It does **not** look only here: it
walks the repository and reviews every file with the shape of a proposal, wherever it was
filed, and reports a proposal outside `proposals/` or
[`examples/corpus-proposal/`](../examples/corpus-proposal/) as an error rather than
skipping it. Discovering no proposals at all is a hard failure, so the gate cannot quietly
pass by reviewing nothing.

The worked example, the full rule table, and what each of the three statuses means are in
[`examples/corpus-proposal/README.md`](../examples/corpus-proposal/README.md). Nothing here
is ever written into `corpus/` automatically — a proposal is reviewed, then merged by a
human.
