# axiom-symbolic v0.2.0

This repository is the first **non-bounded** proof backend for Axiom. It symbolically executes `AXIOM-PROGRAM/2` into
affine path states and proves one-variable quantifier-free linear-integer proof obligations by checking the exact
integer satisfiability of their negation.

It is intentionally narrow. Unsupported instructions or formulas are rejected. Within the declared fragment, no finite
input range is enumerated.

```bash
python axiom_symbolic.py verify spec.aix program.axp \
  --proof program.axproof \
  --counterexample counterexample.axcex
```

## Attribution

Maintainer of Localzet contributions: **Ivan Zorin (localzet)** — <creator@localzet.com> · https://www.localzet.com. Copyright © 2026 Localzet Group. Original authorship and third-party licenses remain applicable. See [AUTHORS](.github/AUTHORS.md).
