#!/usr/bin/env python3
"""Exact symbolic verifier for Axiom v0.2's deliberately small arithmetic core.

The backend does not enumerate an input range. It symbolically executes AXIOM-PROGRAM/2
into affine path states and checks each proof obligation by exact integer satisfiability
of one-variable linear constraints. The soundness claim is intentionally scoped to the
supported grammar; unsupported constructs are rejected rather than approximated.
"""
from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Iterator

VERSION = "axiom-symbolic/0.2.0"
LOGIC = "QF_LIA_1VAR_AFFINE_PATHS"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Affine:
    a: int = 0
    b: int = 0

    def __add__(self, other: "Affine") -> "Affine":
        return Affine(self.a + other.a, self.b + other.b)

    def __sub__(self, other: "Affine") -> "Affine":
        return Affine(self.a - other.a, self.b - other.b)

    def __neg__(self) -> "Affine":
        return Affine(-self.a, -self.b)

    def eval(self, x: int) -> int:
        return self.a * x + self.b


@dataclass(frozen=True)
class Atom:
    left: Affine
    op: str
    right: Affine

    def negate(self) -> "Atom":
        inverse = {"==": "!=", "!=": "==", "<": ">=", "<=": ">", ">": "<=", ">=": "<"}
        return Atom(self.left, inverse[self.op], self.right)


@dataclass(frozen=True)
class BoolExpr:
    kind: str
    atom: Atom | None = None
    left: "BoolExpr | None" = None
    right: "BoolExpr | None" = None

    @staticmethod
    def true() -> "BoolExpr":
        return BoolExpr("true")

    @staticmethod
    def false() -> "BoolExpr":
        return BoolExpr("false")

    @staticmethod
    def from_atom(atom: Atom) -> "BoolExpr":
        return BoolExpr("atom", atom=atom)


@dataclass
class PathState:
    regs: dict[int, Affine]
    constraints: list[Atom]


@dataclass(frozen=True)
class PathResult:
    constraints: tuple[Atom, ...]
    result: Affine


class TokenStream:
    def __init__(self, text: str):
        self.tokens = list(tokenize(text))
        self.index = 0

    def peek(self) -> str | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def take(self, expected: str | None = None) -> str:
        token = self.peek()
        if token is None:
            raise ValueError("unexpected end of expression")
        if expected is not None and token != expected:
            raise ValueError(f"expected {expected!r}, got {token!r}")
        self.index += 1
        return token


def tokenize(text: str) -> Iterator[str]:
    index = 0
    while index < len(text):
        ch = text[index]
        if ch.isspace():
            index += 1
            continue
        for op in ("||", "&&", "==", "!=", ">=", "<="):
            if text.startswith(op, index):
                yield op
                index += len(op)
                break
        else:
            if ch in "()+-<>!":
                yield ch
                index += 1
                continue
            if ch.isdigit():
                end = index + 1
                while end < len(text) and text[end].isdigit():
                    end += 1
                yield text[index:end]
                index = end
                continue
            if ch.isalpha() or ch == "_":
                end = index + 1
                while end < len(text) and (text[end].isalnum() or text[end] in "_-"):
                    end += 1
                yield text[index:end]
                index = end
                continue
            raise ValueError(f"unexpected character {ch!r} in expression")
            continue
        continue


def parse_bool(text: str, env: dict[str, Affine]) -> BoolExpr:
    stream = TokenStream(text)
    expr = parse_or(stream, env)
    if stream.peek() is not None:
        raise ValueError(f"unexpected token: {stream.peek()}")
    return expr


def parse_or(stream: TokenStream, env: dict[str, Affine]) -> BoolExpr:
    expr = parse_and(stream, env)
    while stream.peek() == "||":
        stream.take()
        expr = BoolExpr("or", left=expr, right=parse_and(stream, env))
    return expr


def parse_and(stream: TokenStream, env: dict[str, Affine]) -> BoolExpr:
    expr = parse_not(stream, env)
    while stream.peek() == "&&":
        stream.take()
        expr = BoolExpr("and", left=expr, right=parse_not(stream, env))
    return expr


def parse_not(stream: TokenStream, env: dict[str, Affine]) -> BoolExpr:
    if stream.peek() == "!":
        stream.take()
        return BoolExpr("not", left=parse_not(stream, env))
    if stream.peek() == "true":
        stream.take()
        return BoolExpr.true()
    if stream.peek() == "false":
        stream.take()
        return BoolExpr.false()
    if stream.peek() == "(":
        # Boolean grouping is ambiguous with arithmetic grouping. Parse optimistically as bool.
        mark = stream.index
        stream.take("(")
        try:
            inner = parse_or(stream, env)
            stream.take(")")
            if stream.peek() not in ("==", "!=", "<", "<=", ">", ">="):
                return inner
        except ValueError:
            pass
        stream.index = mark

    left = parse_int(stream, env)
    op = stream.take()
    if op not in ("==", "!=", "<", "<=", ">", ">="):
        raise ValueError(f"expected comparison operator, got {op!r}")
    right = parse_int(stream, env)
    return BoolExpr.from_atom(Atom(left, op, right))


def parse_int(stream: TokenStream, env: dict[str, Affine]) -> Affine:
    expr = parse_unary(stream, env)
    while stream.peek() in ("+", "-"):
        op = stream.take()
        right = parse_unary(stream, env)
        expr = expr + right if op == "+" else expr - right
    return expr


def parse_unary(stream: TokenStream, env: dict[str, Affine]) -> Affine:
    if stream.peek() == "-":
        stream.take()
        return -parse_unary(stream, env)
    if stream.peek() == "(":
        stream.take()
        inner = parse_int(stream, env)
        stream.take(")")
        return inner
    token = stream.take()
    if token.lstrip("-").isdigit():
        return Affine(0, int(token))
    if token in env:
        return env[token]
    raise ValueError(f"unknown arithmetic symbol: {token}")


def negate(expr: BoolExpr) -> BoolExpr:
    if expr.kind == "true":
        return BoolExpr.false()
    if expr.kind == "false":
        return BoolExpr.true()
    if expr.kind == "atom":
        assert expr.atom is not None
        return BoolExpr.from_atom(expr.atom.negate())
    if expr.kind == "not":
        assert expr.left is not None
        return expr.left
    assert expr.left is not None and expr.right is not None
    if expr.kind == "and":
        return BoolExpr("or", left=negate(expr.left), right=negate(expr.right))
    if expr.kind == "or":
        return BoolExpr("and", left=negate(expr.left), right=negate(expr.right))
    raise ValueError(expr.kind)


def dnf(expr: BoolExpr) -> list[list[Atom]]:
    if expr.kind == "true":
        return [[]]
    if expr.kind == "false":
        return []
    if expr.kind == "atom":
        assert expr.atom is not None
        return [[expr.atom]]
    if expr.kind == "not":
        assert expr.left is not None
        return dnf(negate(expr.left))
    assert expr.left is not None and expr.right is not None
    if expr.kind == "or":
        return dnf(expr.left) + dnf(expr.right)
    if expr.kind == "and":
        out: list[list[Atom]] = []
        for left in dnf(expr.left):
            for right in dnf(expr.right):
                out.append(left + right)
        return out
    raise ValueError(expr.kind)


def ceil_div(a: int, b: int) -> int:
    return -((-a) // b)


def conjunction_model(atoms: Iterable[Atom]) -> int | None:
    lower: int | None = None
    upper: int | None = None
    exact: int | None = None
    excluded: set[int] = set()

    def add_lower(value: int) -> bool:
        nonlocal lower
        lower = value if lower is None else max(lower, value)
        return upper is None or lower <= upper

    def add_upper(value: int) -> bool:
        nonlocal upper
        upper = value if upper is None else min(upper, value)
        return lower is None or lower <= upper

    for atom in atoms:
        diff = atom.left - atom.right
        a, b, op = diff.a, diff.b, atom.op
        if a == 0:
            truth = {
                "==": b == 0,
                "!=": b != 0,
                "<": b < 0,
                "<=": b <= 0,
                ">": b > 0,
                ">=": b >= 0,
            }[op]
            if not truth:
                return None
            continue

        if op == "==":
            numerator = -b
            if numerator % a != 0:
                return None
            value = numerator // a
            if exact is not None and exact != value:
                return None
            exact = value
            continue
        if op == "!=":
            numerator = -b
            if numerator % a == 0:
                excluded.add(numerator // a)
            continue

        # Normalize > and >= to < and <= by negation.
        if op == ">":
            a, b, op = -a, -b, "<"
        elif op == ">=":
            a, b, op = -a, -b, "<="

        if op == "<=":
            if a > 0:
                if not add_upper((-b) // a):
                    return None
            else:
                if not add_lower(ceil_div(-b, a)):
                    return None
        elif op == "<":
            # a*x+b < 0 <=> a*x+b <= -1 for integer x.
            if a > 0:
                if not add_upper((-1 - b) // a):
                    return None
            else:
                if not add_lower(ceil_div(-1 - b, a)):
                    return None
        else:
            raise ValueError(op)

    if exact is not None:
        if lower is not None and exact < lower:
            return None
        if upper is not None and exact > upper:
            return None
        if exact in excluded:
            return None
        return exact

    if lower is None and upper is None:
        candidate = 0
    elif lower is None:
        candidate = min(0, upper)  # type: ignore[arg-type]
    elif upper is None:
        candidate = max(0, lower)
    else:
        candidate = lower

    direction = 1
    if upper is not None and candidate > upper:
        return None
    while candidate in excluded:
        candidate += direction
        if upper is not None and candidate > upper:
            if lower is None:
                direction = -1
                candidate = upper
                while candidate in excluded:
                    candidate -= 1
                    if lower is not None and candidate < lower:
                        return None
                return candidate
            return None
    if lower is not None and candidate < lower:
        return None
    return candidate


def formula_model(expr: BoolExpr, prefix: Iterable[Atom] = ()) -> int | None:
    prefix = list(prefix)
    for branch in dnf(expr):
        model = conjunction_model([*prefix, *branch])
        if model is not None:
            return model
    return None


def parse_kv(raw: str, header: str) -> dict[str, str]:
    lines = raw.splitlines()
    if not lines or lines[0] != header:
        raise ValueError(f"expected {header}")
    out: dict[str, str] = {}
    for line in lines[1:]:
        if not line or line == "code:" or line == "end":
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            out[key] = value
    return out


def code_lines(program: str) -> list[str]:
    lines = program.splitlines()
    try:
        start = lines.index("code:") + 1
        end = lines.index("end", start)
    except ValueError as exc:
        raise ValueError("program misses code:/end block") from exc
    return [line.strip() for line in lines[start:end] if line.strip()]


def reg(word: str) -> int:
    if not word.startswith("r"):
        raise ValueError(f"bad register: {word}")
    return int(word[1:])


def symbolic_execute(program: str) -> list[PathResult]:
    states = [PathState(regs={}, constraints=[])]
    returned: list[PathResult] = []

    for line in code_lines(program):
        words = line.split()
        opcode = words[0]
        if opcode == "RETURN":
            source = reg(words[1])
            for state in states:
                returned.append(PathResult(tuple(state.constraints), state.regs[source]))
            states = []
            continue

        next_states: list[PathState] = []
        for state in states:
            regs = dict(state.regs)
            constraints = list(state.constraints)
            if opcode == "LOAD_INPUT" and len(words) == 3 and words[2] == "x":
                regs[reg(words[1])] = Affine(1, 0)
                next_states.append(PathState(regs, constraints))
            elif opcode == "CONST" and len(words) == 3:
                regs[reg(words[1])] = Affine(0, int(words[2]))
                next_states.append(PathState(regs, constraints))
            elif opcode == "NEG" and len(words) == 3:
                regs[reg(words[1])] = -regs[reg(words[2])]
                next_states.append(PathState(regs, constraints))
            elif opcode in ("ADD", "SUB") and len(words) == 4:
                left = regs[reg(words[2])]
                right = regs[reg(words[3])]
                regs[reg(words[1])] = left + right if opcode == "ADD" else left - right
                next_states.append(PathState(regs, constraints))
            elif opcode == "SELECT_NEG_INPUT" and len(words) == 5 and words[2] == "x":
                dest = reg(words[1])
                negative = regs[reg(words[3])]
                nonnegative = regs[reg(words[4])]
                neg_regs = dict(regs)
                neg_regs[dest] = negative
                pos_regs = dict(regs)
                pos_regs[dest] = nonnegative
                next_states.append(
                    PathState(neg_regs, constraints + [Atom(Affine(1, 0), "<", Affine(0, 0))])
                )
                next_states.append(
                    PathState(pos_regs, constraints + [Atom(Affine(1, 0), ">=", Affine(0, 0))])
                )
            else:
                raise ValueError(f"unsupported instruction: {line}")
        states = next_states

    if states or not returned:
        raise ValueError("program must terminate every symbolic path with RETURN")
    return returned


def ordered_clauses(doc: dict[str, str], prefix: str) -> list[tuple[str, str]]:
    indices = sorted(
        {
            int(key.split('.')[1])
            for key in doc
            if key.startswith(prefix + ".") and key.endswith(".expr")
        }
    )
    return [
        (
            doc.get(f"{prefix}.{index}.id", f"{prefix}-{index}"),
            doc[f"{prefix}.{index}.expr"],
        )
        for index in indices
    ]


def domain_atoms(spec: dict[str, str]) -> list[Atom]:
    input_name = spec["input.0.name"]
    kind = spec[f"domain.{input_name}.kind"]
    if kind == "unbounded":
        return []
    if kind != "range":
        raise ValueError(f"unsupported domain kind: {kind}")
    low = int(spec[f"domain.{input_name}.min"])
    high = int(spec[f"domain.{input_name}.max"])
    x = Affine(1, 0)
    return [Atom(x, ">=", Affine(0, low)), Atom(x, "<=", Affine(0, high))]


def evaluate_program(program: str, x: int) -> int:
    regs: dict[int, int] = {}
    for line in code_lines(program):
        words = line.split()
        opcode = words[0]
        if opcode == "LOAD_INPUT":
            regs[reg(words[1])] = x
        elif opcode == "CONST":
            regs[reg(words[1])] = int(words[2])
        elif opcode == "NEG":
            regs[reg(words[1])] = -regs[reg(words[2])]
        elif opcode == "ADD":
            regs[reg(words[1])] = regs[reg(words[2])] + regs[reg(words[3])]
        elif opcode == "SUB":
            regs[reg(words[1])] = regs[reg(words[2])] - regs[reg(words[3])]
        elif opcode == "SELECT_NEG_INPUT":
            regs[reg(words[1])] = regs[reg(words[3])] if x < 0 else regs[reg(words[4])]
        elif opcode == "RETURN":
            return regs[reg(words[1])]
        else:
            raise ValueError(opcode)
    raise ValueError("no RETURN")


def verify(spec_raw: str, program_raw: str) -> tuple[bool, dict[str, str], dict[str, str] | None]:
    spec = parse_kv(spec_raw, "AXIOM-IR/2")
    program = parse_kv(program_raw, "AXIOM-PROGRAM/2")
    if spec["module"] != program["module"]:
        raise ValueError("spec/program module mismatch")

    paths = symbolic_execute(program_raw)
    requires = ordered_clauses(spec, "requires")
    ensures = ordered_clauses(spec, "ensures")
    base_domain = domain_atoms(spec)

    for path_index, path in enumerate(paths):
        env = {"x": Affine(1, 0), "result": path.result}
        req_formula = BoolExpr.true()
        for _, text in requires:
            req_formula = BoolExpr("and", left=req_formula, right=parse_bool(text, env))

        # Restrict the path to inputs for which all preconditions hold.
        for ensure_id, ensure_text in ensures:
            obligation = BoolExpr(
                "and",
                left=req_formula,
                right=negate(parse_bool(ensure_text, env)),
            )
            model = formula_model(obligation, [*base_domain, *path.constraints])
            if model is not None:
                result = evaluate_program(program_raw, model)
                cex = {
                    "module": spec["module"],
                    "input.x": str(model),
                    "observed.result": str(result),
                    "violated": ensure_id,
                    "path": str(path_index),
                }
                meta = {
                    "paths": str(len(paths)),
                    "obligations": str(len(ensures) * len(paths)),
                }
                return False, meta, cex

    meta = {
        "paths": str(len(paths)),
        "obligations": str(len(ensures) * len(paths)),
    }
    return True, meta, None


def emit_counterexample(cex: dict[str, str]) -> str:
    lines = ["AXIOM-COUNTEREXAMPLE/1"]
    for key in ("module", "input.x", "observed.result", "violated", "path"):
        lines.append(f"{key}={cex[key]}")
    return "\n".join(lines) + "\n"


def emit_proof(spec_raw: str, program_raw: str, valid: bool, meta: dict[str, str], cex: dict[str, str] | None) -> str:
    backend_hash = sha256_bytes(Path(__file__).read_bytes())
    spec = parse_kv(spec_raw, "AXIOM-IR/2")
    input_name = spec["input.0.name"]
    domain_kind = spec[f"domain.{input_name}.kind"]
    lines = [
        "AXIOM-PROOF/2",
        "kind=symbolic",
        f"logic={LOGIC}",
        f"backend={VERSION}",
        f"backend.sha256={backend_hash}",
        f"spec.sha256={sha256_bytes(spec_raw.encode())}",
        f"program.sha256={sha256_bytes(program_raw.encode())}",
        f"domain.kind={domain_kind}",
        f"paths={meta['paths']}",
        f"obligations={meta['obligations']}",
        "soundness.scope=exact-for-supported-fragment",
        f"counterexample={'none' if cex is None else sha256_bytes(emit_counterexample(cex).encode())}",
        f"verdict={'VALID' if valid else 'INVALID'}",
    ]
    return "\n".join(lines) + "\n"


def command_verify(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec)
    program_path = Path(args.program)
    spec_raw = spec_path.read_text()
    program_raw = program_path.read_text()
    valid, meta, cex = verify(spec_raw, program_raw)
    proof = emit_proof(spec_raw, program_raw, valid, meta, cex)
    Path(args.proof).write_text(proof)
    if cex is not None and args.counterexample:
        Path(args.counterexample).write_text(emit_counterexample(cex))
    print("VALID" if valid else "INVALID")
    if cex is not None:
        print(f"counterexample: x={cex['input.x']} result={cex['observed.result']} violates={cex['violated']}")
    return 0 if valid else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("spec")
    verify_parser.add_argument("program")
    verify_parser.add_argument("--proof", required=True)
    verify_parser.add_argument("--counterexample")
    verify_parser.set_defaults(func=command_verify)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
