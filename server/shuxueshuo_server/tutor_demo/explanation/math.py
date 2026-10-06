"""Q12 pilot kernel. No eval/sympify of user strings; all facts use exact algebra.

The supported domain is rational expressions on m in (0, 3), n = 6 - 2m.
Unknown proofs are reported as unsupported, never as mathematical falsehood.
"""

import ast
import re
from dataclasses import dataclass, field

import sympy as s

from .contracts import Operation

M, N = s.symbols("m n", positive=True)
U, V = s.symbols("U V", positive=True)
D1, D2 = 2 * M + 1, N + 1
TARGET = 1 / D1 + 1 / D2


class MathIssue(Exception):
    def __init__(self, message, status="invalid"):
        super().__init__(message)
        self.status = status


def tex(expr):
    return s.latex(expr)


def reduce(expr):
    return s.cancel(expr.subs(N, 6 - 2 * M))


def split(term):
    """(rational coefficient, numerator factors, denominator factors) without re-multiplying."""
    coefficient, rest = term.as_coeff_Mul()
    numerator, denominator = [], []
    for factor in s.Mul.make_args(rest):
        if factor == 1:
            continue
        if factor.is_Pow and factor.exp.is_negative:
            denominator.append(factor.base ** -factor.exp)
        else:
            numerator.append(factor)
    return s.Rational(coefficient), numerator, denominator


def nonnegative(expr, strict=False):
    expr = reduce(expr)
    try:
        bad = expr <= 0 if strict else expr < 0
        return s.reduce_inequalities([bad, M > 0, M < 3], M).as_set() == s.EmptySet
    except (NotImplementedError, ValueError, TypeError):
        return False


@dataclass
class MathState:
    aliases: dict = field(default_factory=dict)
    expression: s.Expr = TARGET
    lower: s.Expr | None = None
    equalities: list = field(default_factory=list)
    complete: bool = False
    # Board layout: terms over the same denominator shown as one fraction.
    grouped: bool = False

    def canonical(self, expr):
        return expr.xreplace({s.Symbol(k, positive=True): v for k, v in self.aliases.items()})

    def coordinates(self):
        d1, d2 = D1, D2
        for name, original in self.aliases.items():
            if original == D1:
                d1 = s.Symbol(name, positive=True)
            if original == D2:
                d2 = s.Symbol(name, positive=True)
        return d1, d2

    @staticmethod
    def basis(expr):
        return s.expand(s.cancel(expr.subs({M: (U - 1) / 2, N: V - 1}, simultaneous=True)))

    def present(self, expr):
        # Substitute in the two-denominator coordinate system, then expand only
        # there. This preserves whole denominators in the student's board.
        d1, d2 = self.coordinates()
        return self.basis(expr).subs({U: d1, V: d2}, simultaneous=True)

    def group(self, expr):
        """present(), with the numerators of terms over the same denominator added together."""
        d1, d2 = self.coordinates()
        numerators = {}
        for term in s.Add.make_args(self.basis(self.canonical(expr))):
            denominator = s.fraction(term)[1].as_coeff_Mul()[1]
            numerators[denominator] = numerators.get(denominator, 0) + term * denominator
        terms = []
        for denominator, numerator in numerators.items():
            numerator = s.expand(numerator.subs({U: d1, V: d2}, simultaneous=True))
            if numerator != 0:
                # Three factors: Mul(1/6, n-1) alone would distribute back to n/6 - 1/6.
                coefficient, rest = numerator.primitive()
                terms.append(s.Mul(coefficient, rest, 1 / denominator.subs({U: d1, V: d2}, simultaneous=True)))
        return s.Add(*terms)

    def display(self, expr):
        return self.present(self.canonical(expr))

    def board(self):
        """The current expression as the student sees it."""
        return self.group(self.expression) if self.grouped else self.display(self.expression)

    @staticmethod
    def normalize_input(text):
        text = text.strip().replace("−", "-").replace("×", "*").replace("÷", "/").replace("^", "**")
        return re.sub(r"(?<=\d)(?=[a-z(])|(?<=\))(?=[a-z(])", "*", text)

    def verbatim(self, text):
        """LaTeX of a validated input in the student's own structure (no simplification)."""
        self.parse(text)
        symbols = {"m": M, "n": N, **{k: s.Symbol(k, positive=True) for k in self.aliases}}
        lazy = {"evaluate": False}

        def build(node):
            if isinstance(node, ast.Constant):
                return s.Integer(node.value)
            if isinstance(node, ast.Name):
                return symbols[node.id]
            if isinstance(node, ast.UnaryOp):
                value = build(node.operand)
                return s.Mul(-1, value, **lazy) if isinstance(node.op, ast.USub) else value
            a, b = build(node.left), build(node.right)
            return {
                ast.Add: lambda: s.Add(a, b, **lazy),
                ast.Sub: lambda: s.Add(a, s.Mul(-1, b, **lazy), **lazy),
                ast.Mult: lambda: s.Mul(a, b, **lazy),
                ast.Div: lambda: s.Pow(b, -1, **lazy) if a == 1 else s.Mul(a, s.Pow(b, -1, **lazy), **lazy),
                ast.Pow: lambda: s.Pow(a, b, **lazy),
            }[type(node.op)]()

        return s.latex(build(ast.parse(self.normalize_input(text), mode="eval").body), order="none")

    def parse(self, text):
        text = self.normalize_input(text)
        if not text or len(text) > 160:
            raise MathIssue("请填写一个简短的数学表达式。", "clarify")
        try:
            tree = ast.parse(text, mode="eval")
        except (SyntaxError, ValueError):
            raise MathIssue("暂时无法读取这个式子，请使用括号和 + - * /，例如 1/(2*m+1)。", "clarify") from None
        if len(list(ast.walk(tree))) > 65:
            raise MathIssue("这个式子超出了 demo 的验算范围，请分成较小的步骤。", "unsupported")
        symbols = {"m": M, "n": N, **{k: s.Symbol(k, positive=True) for k in self.aliases}}

        def read(node):
            if isinstance(node, ast.Constant) and type(node.value) is int and abs(node.value) <= 1000:
                return s.Integer(node.value)
            if isinstance(node, ast.Name) and node.id in symbols:
                return symbols[node.id]
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
                value = read(node.operand)
                return -value if isinstance(node.op, ast.USub) else value
            if isinstance(node, ast.BinOp):
                a, b = read(node.left), read(node.right)
                if isinstance(node.op, ast.Add):
                    return a + b
                if isinstance(node.op, ast.Sub):
                    return a - b
                if isinstance(node.op, ast.Mult):
                    return a * b
                if isinstance(node.op, ast.Div):
                    self.check_nonzero(self.canonical(b))
                    return a / b
                if isinstance(node.op, ast.Pow) and b.is_Integer and abs(b) <= 4:
                    numerator, denominator = s.fraction(reduce(self.canonical(a)))
                    if any(s.Poly(part, M).degree() * abs(b) > 8 for part in (numerator, denominator)) or (a.is_Integer and len(str(abs(a))) * abs(b) > 24):
                        raise MathIssue("这个幂超出了 demo 的验算范围。", "unsupported")
                    if b <= 0:
                        self.check_nonzero(self.canonical(a))
                    return a ** b
            raise MathIssue("只能使用已定义变量、整数、四则运算和小整数次幂；其他写法暂不支持。", "unsupported")

        expr = read(tree.body)
        rational = reduce(self.canonical(expr))
        for part in s.fraction(rational):
            poly = s.Poly(part, M)
            if poly.degree() > 8 or any(abs(c) > 10**12 for c in poly.all_coeffs()):
                raise MathIssue("这个式子超出了 demo 的验算范围。", "unsupported")
        return expr

    @staticmethod
    def check_nonzero(expr):
        value = reduce(expr)
        if any(s.Poly(part, M).degree() > 8 for part in s.fraction(value)):
            raise MathIssue("这个分母超出了 demo 的验算范围。", "unsupported")
        if value == 0:
            raise MathIssue("这个分母为零，不能进行除法。")
        try:
            zeros = s.solveset(value, M, domain=s.Interval.open(0, 3))
        except (NotImplementedError, ValueError):
            raise MathIssue("暂时无法确认分母在原题范围内非零。", "unsupported") from None
        if zeros is not s.EmptySet:
            raise MathIssue("这个分母在原题范围内可能为零，需要先处理定义域，不能直接约掉。", "unsupported")

    def terms(self):
        """Displayed terms in reading order: constants, then by the whole denominator they divide."""
        d1, d2 = self.display(D1), self.display(D2)

        def order(term):
            denominator = split(term)[2]
            return (not term.is_number, 0 if d1 in denominator else 1 if d2 in denominator else 2)
        return sorted(s.Add.make_args(self.board()), key=order)

    def board_tex(self):
        latex = ""
        for index, term in enumerate(self.terms()):
            piece = tex(term)
            latex += piece if not index or piece.startswith("-") else "+" + piece
        return latex

    def objects(self):
        """Referenceable sub-expressions: both whole denominators, then every term."""
        found = [self.display(D1), self.display(D2)]
        for term in self.terms():
            if not term.is_number and term not in found:
                found.append(term)
        return found

    def equivalent(self, left, right):
        return reduce(self.canonical(self.parse(left)) - self.canonical(self.parse(right))) == 0

    def object_for(self, text):
        """The referenceable object equal in value to text, or None."""
        value = reduce(self.canonical(self.parse(text)))
        return next((o for o in self.objects() if reduce(self.canonical(o) - value) == 0), None)

    def matches_object(self, text):
        return self.object_for(text) is not None

    def marked(self):
        """Current expression in LaTeX with each object wrapped in \\htmlData{obj=i}."""
        objects = self.objects()

        def find(expr):
            return next((i for i, o in enumerate(objects) if o == expr), None)

        def wrap(expr, body):
            index = find(expr)
            return body if index is None else f"\\htmlData{{obj={index}}}{{{body}}}"

        def product(coefficient, factors):
            # Factor lists, not sympy Mul: Mul(8, n+1) would auto-distribute to 8n+8.
            parts = [f"\\left({wrap(f, tex(f))}\\right)" if f.is_Add and len(factors) + (coefficient != 1) > 1
                     else wrap(f, tex(f)) for f in factors]
            if coefficient != 1 or not parts:
                parts.insert(0, tex(coefficient))
            return " ".join(parts)

        def term(expr):
            p, numerator, denominator = split(expr)
            if not denominator and p.q == 1:
                return wrap(expr, product(p, numerator))
            top = product(s.Integer(p.p), numerator)
            bottom = product(s.Integer(p.q), denominator)
            return wrap(expr, f"\\frac{{{top}}}{{{bottom}}}")

        latex = ""
        for index, item in enumerate(self.terms()):
            piece = term(item)
            latex += piece if not index or piece.startswith("-") else "+" + piece
        return latex

    def describe(self, op: Operation, inferred=()):
        """Plain-language echo of what the executor will run; math segments flag inferred arguments."""
        def math(arg):
            return {"math": self.verbatim(getattr(op, arg)), "inferred": arg in inferred}

        text = lambda value: {"text": value}
        return {
            "claim": lambda: [math("a"), text(" = "), math("b")],
            "evaluate": lambda: [text("计算 "), math("a")],
            "substitute": lambda: [text(f"设 {op.name} = "), math("a")],
            "multiply": lambda: [text("给整个式子乘 "), math("a")],
            "expand": lambda: [text("展开、化简当前式子")],
            "combine": lambda: [text("把分母相同的项合并成一个分式")],
            "amgm": lambda: [text("对 "), math("a"), text(" 和 "), math("b"), text(" 用基本不等式")],
            "attain": lambda: [text("当 "), math("a"), text(" = "), math("b"), text(" 时取等")],
        }[op.op]()

    def view(self):
        mapping = {M: M, N: N}
        for name, expr in self.aliases.items():
            symbol = s.Symbol(name, positive=True)
            mapping[M if expr == D1 else N] = (symbol - 1) / 2 if expr == D1 else symbol - 1
        relation = s.expand((2 * M + N - 6).subs(mapping, simultaneous=True))
        constant = relation.subs({symbol: 0 for symbol in relation.free_symbols})
        conditions = [f"{tex(relation - constant)}={tex(-constant)}"]
        conditions += [f"{name}>1" for name in self.aliases]
        conditions += [f"{tex(v)}>0" for original, v in mapping.items() if original == v]
        return {
            "expression": self.board_tex(),
            "marked": self.marked(),
            "conditions": conditions,
            "aliases": {k: tex(v) for k, v in self.aliases.items()},
            "objects": [{"id": i, "expression": str(o), "latex": tex(o)} for i, o in enumerate(self.objects())],
            "lower": tex(self.lower) if self.lower is not None else None,
            "complete": self.complete,
        }

    def fact_key(self, a, b):
        numerator = s.fraction(s.cancel(s.expand(self.canonical(a - b))))[0]
        if numerator == 0:
            return None
        poly = s.Poly(numerator, M, N)
        return "fact:" + s.srepr(s.expand(numerator / poly.LC()))

    def execute(self, op: Operation):
        a = self.parse(op.a) if op.a else s.Integer(0)
        b = self.parse(op.b) if op.b else s.Integer(0)
        ca, cb = self.canonical(a), self.canonical(b)
        lines, component, title = [], "formula", "整理关系"
        visual, checks, key = {}, {}, None
        before_expression, before_board, before_tex = self.expression, self.board(), self.board_tex()
        if op.op == "claim":
            if reduce(ca - cb) != 0:
                raise MathIssue(f"根据原条件，${tex(a)}={tex(b)}$ 不恒成立。请检查等式两边。")
            lines = [f"{tex(a)}={tex(b)}"]
            key = self.fact_key(a, b)
        elif op.op == "evaluate":
            value = reduce(ca)
            if value.free_symbols:
                raise MathIssue("由当前条件还不能把这个式子求成一个定值。", "unsupported")
            title = "计算表达式"
            lines = [f"{tex(a)}={tex(value)}"]
            key = self.fact_key(a, value)
        elif op.op == "substitute":
            if op.name in self.aliases:
                raise MathIssue(f"变量 {op.name} 已有定义。可以撤回或从此前步骤另开思路。", "clarify")
            original = next((d for d in (D1, D2) if s.cancel(ca - d) == 0), None)
            if original is None:
                raise MathIssue("这个 demo 暂时支持对目标中的分母整体换元；其他换元还不能核验。", "unsupported")
            if original in self.aliases.values():
                raise MathIssue("这个整体已经有新变量名，可以直接使用它继续。", "clarify")
            self.aliases[op.name] = original
            key = "alias:" + s.srepr(original)
            title, component = "定义新变量", "substitution"
            lines = [f"{op.name}={tex(a)}", f"{op.name}>1", f"F={self.board_tex()}"]
            lines += self.view()["conditions"]
        elif op.op == "multiply":
            if reduce(ca - 1) != 0:
                raise MathIssue(f"由原条件，所选乘数化为 ${tex(reduce(ca))}$，不等于 1，不能保持原式的值。")
            self.expression = self.present(self.canonical(self.expression) * ca)
            self.grouped = False
            title, component = "乘 1 配式", "rewrite"
            lines = [f"{tex(a)}=1", f"F=\\left({before_tex}\\right)\\left({tex(a)}\\right)", f"F={self.board_tex()}"]
        elif op.op == "expand":
            self.expression = self.present(self.canonical(self.expression))
            self.grouped = False
            title = "展开与化简"
            lines = [f"F={before_tex}", f"F={self.board_tex()}"]
        elif op.op == "combine":
            self.grouped = True
            title = "合并同分母的项"
            lines = [f"F={before_tex}", f"F={self.board_tex()}"]
        elif op.op == "amgm":
            if nonnegative(-ca) or nonnegative(-cb):
                raise MathIssue("所选项中有一项不是正数，不能这样应用正项基本不等式。")
            if not nonnegative(ca, strict=True) or not nonnegative(cb, strict=True):
                raise MathIssue("尚不能确认这两项在原题范围内都为正，不能按正项应用这里的基本不等式。", "unsupported")
            title, component = "应用基本不等式", "amgm"
            a, b = self.display(a), self.display(b)
            visual = {"terms": [str(a), str(b)], "labels": [f"${tex(a)}$", f"${tex(b)}$"]}
            product, total = reduce(ca * cb), reduce(ca + cb)
            checks = {"fixed_product": not product.free_symbols, "fixed_sum": not total.free_symbols, "positivity": True}
            if not product.free_symbols and product > 0:
                checks["pair_sum_min"] = str(2 * s.sqrt(product))
            terms_key = "|".join(sorted(s.srepr(reduce(c)) for c in (ca, cb)))
            lines = [f"{tex(a)}>0,\\quad {tex(b)}>0", f"{tex(a)}+{tex(b)}\\ge 2\\sqrt{{\\left({tex(a)}\\right)\\left({tex(b)}\\right)}}"]
            bound = None
            # Constant product: find the same positive multiplier of both chosen
            # terms in the CURRENT expression. No hidden target transformation.
            if not product.free_symbols and product > 0:
                def basis(e):
                    return s.expand(s.cancel(e.subs({M: (U - 1) / 2, N: V - 1}, simultaneous=True)))
                e, aa, bb = basis(self.canonical(self.expression)), basis(ca), basis(cb)
                if aa != bb and not aa.is_number and not bb.is_number:
                    weight = e.coeff(aa)
                    rest = reduce((e - weight * (aa + bb)).subs({U: D1, V: D2}, simultaneous=True))
                    if weight.is_number and weight > 0 and not rest.free_symbols:
                        bound = rest + 2 * weight * s.sqrt(product)
                        # Fixed product, minimising the sum of the two terms of the target.
                        checks["sum_target"] = True
            # Constant denominator sum: the requested AM-GM gives a product
            # upper bound, then reciprocation is permitted because both are >0.
            if not total.free_symbols and total > 0 and reduce(TARGET - (ca + cb) / (ca * cb)) == 0:
                bound = 4 / total
                lines += [f"\\left({tex(a)}\\right)\\left({tex(b)}\\right)\\le {tex(total**2 / 4)}", f"F=\\frac{{{tex(total)}}}{{\\left({tex(a)}\\right)\\left({tex(b)}\\right)}}\\ge {tex(bound)}"]
            if bound is not None:
                if not nonnegative(TARGET - bound):
                    raise MathIssue("暂时无法核验由此得到的目标下界。", "unsupported")
                self.lower = bound if self.lower is None else max(self.lower, bound)
                self.equalities.append(ca - cb)
                lines.append(f"F\\ge {tex(self.lower)}")
            else:
                lines.append("\\text{这条不等式成立；尚未由此建立目标的常数下界。}")
            key = f"amgm:{terms_key}|bound:{s.srepr(bound)}"
        elif op.op == "attain":
            relation = reduce(ca - cb)
            if relation == 0:
                raise MathIssue("这个关系本来就成立，尚未限定取等的位置。", "clarify")
            roots = s.solveset(relation, M, domain=s.Interval.open(0, 3))
            if roots == s.EmptySet:
                raise MathIssue("这个取等关系在原题的正数范围内没有解。")
            if not isinstance(roots, s.FiniteSet):
                raise MathIssue("暂时无法求出这个关系在原题范围内的候选点。", "unsupported")
            if not roots:
                raise MathIssue("这个取等关系在原题的正数范围内没有解。")
            points = [(r, s.simplify(6 - 2 * r), s.simplify(TARGET.subs({M: r, N: 6 - 2 * r}))) for r in roots]
            if self.lower is not None and not any(s.simplify(value - self.lower) == 0 for _, _, value in points):
                values = "，".join(f"$F={tex(value)}$" for _, _, value in points)
                raise MathIssue(f"按这个关系回代，得到{values}，没有达到已建立的下界 ${tex(self.lower)}$。请检查实际应用不等式的两项。")
            title, component = "检查取等", "equality"
            point_key = "|".join(sorted(s.srepr(r) for r in roots))
            lines = [f"{tex(a)}={tex(b)}"]
            for m, n, value in points:
                lines += [f"m={tex(m)},\\quad n={tex(n)},\\quad 2m+n=6", f"m>0,\\ n>0,\\quad F={tex(value)}"]
            if self.lower is not None:
                # Attaining a proven bound is a different conclusion from checking a candidate.
                key = f"bound_attained:{s.srepr(self.lower)}:{point_key}"
                self.complete = True
                lines.append(f"\\min F={tex(self.lower)}")
            else:
                key = f"candidate_verified:{point_key}"
                lines.append("\\text{已核验候选点，尚未证明它是最小值。}")
        if op.op in {"multiply", "expand", "combine"}:
            # Algebraic form in the original variables; the constraint is NOT applied,
            # otherwise every equivalent rewrite would collapse to the same value.
            after, before = (s.cancel(self.canonical(e)) for e in (self.expression, before_expression))
            if after != before:
                key = "expr:" + s.srepr(after)
            elif self.board() != before_board:
                # Same value, new layout: a step for the student, not a new mathematical fact.
                key = "board:" + s.srepr(self.board())
        result = lines[0] + r",\quad F=" + self.board_tex() if op.op == "substitute" else lines[-1]
        # key is None when nothing new was established (identity, unchanged expression).
        return {"title": title, "component": component, "visual": visual, "lines": lines, "result": result,
                "operation": op.model_dump(), "status": "verified", "key": key, "checks": checks}
