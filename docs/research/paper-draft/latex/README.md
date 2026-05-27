# FocusParse LaTeX Draft

Date: 2026-05-24

This directory contains the first standalone LaTeX draft generated from the
paper-draft package.

## Entry Point

```text
docs/research/paper-draft/latex/main.tex
```

The draft uses the parent bibliography:

```text
docs/research/paper-draft/references.bib
```

It references the current draft qualitative panels in place:

```text
results/paper/qualitative-figure-panels/figure3-finance-latvia-evidence-binding.png
results/paper/qualitative-figure-panels/figure4-datasheet-jesd204b-evidence-binding.png
```

## Compile Command

From the repo root:

```bash
python3 /Users/gabrielbo/.codex/plugins/cache/openai-bundled/latex/0.2.0/scripts/compile_latex.py /Users/gabrielbo/projects/FocusParse/docs/research/paper-draft/latex/main.tex --json
```

Last verified compile:

```text
2026-05-24: TeX Live / latexmk succeeded and wrote main.pdf (7 pages).
```

## Current Scope

This is not a final venue template. It is a portable article-style draft that
puts the current submission argument, main table, figures, and bibliography into
a compile target. Before submission, convert this into the target venue's style
file and rerun the compile check.
