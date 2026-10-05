# axiom-symbolic v0.2.0

Это первый **не bounded** proof-backend Axiom. Он символически исполняет `AXIOM-PROGRAM/2` в affine path states и
доказывает одномерные quantifier-free linear-integer obligations через точную проверку целочисленной выполнимости их
отрицания.

Фрагмент намеренно узкий. Неподдерживаемые инструкции и формулы отвергаются, а не приближаются. Внутри заявленного
фрагмента конечный диапазон входов не перебирается.

```bash
python axiom_symbolic.py verify spec.aix program.axp \
  --proof program.axproof \
  --counterexample counterexample.axcex
```

## Авторство

Сопровождающий собственных изменений: **Ivan Zorin (localzet)** — <creator@localzet.com> · https://www.localzet.com. Copyright © 2026 Localzet Group. Исходное авторство и лицензии сторонних компонентов сохраняются. См. [AUTHORS](.github/AUTHORS.md).
