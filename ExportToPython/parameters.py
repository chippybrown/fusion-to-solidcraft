"""
    User parameter and geometry utilities for Build123D Python script generation.

    Written by Ran Peleg, Visionware Solutions Pty Ltd
    ran@visionware.com.au
    Provided as-is, without warranty of any kind under Apache-2.0 license
"""

from __future__ import annotations

import keyword
import math
import os
import re
from typing import Iterable, List, Optional, Tuple

import adsk.core
import adsk.fusion

import Utils

class Parameters:
    # Tokenizer for Fusion parameter expressions.
    _EXPR_TOKEN_RE = re.compile(
        r"[A-Za-z_][A-Za-z0-9_]*"
        r"|\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?"
        r"|[()+\-*/]"
        r"|\s+"
    )
    _IDENTIFIER_RE = re.compile(r"^[A-Za-z_]")
    _NUMBER_RE = re.compile(r"^[0-9.]")

    def _register_user_parameters(self):
            """Build a Fusion parameter name -> Python variable name registry."""

            user_params = Utils._iter_fusion_collection(Utils._safe_getattr(self.design, "userParameters", None))
            if not user_params:
                return

            reserved = {self.model_var, "part", "self"}

            for parameter in user_params:
                name = Utils._safe_getattr(parameter, "name", None)
                if not name or name in self.parameter_vars:
                    continue

                # Fusion allows non-numeric user parameters (e.g. text/list-driven
                # "configuration" parameters). Parameter.value raises for these;
                # skip registering them as a shared variable rather than crash --
                # any dimension expression referencing one by name will simply
                # fall back to a baked literal via _param_expr, same as for any
                # other unregistered parameter.
                try:
                    parameter.value
                except Exception:
                    self.unsupported.append(
                        f"User parameter '{name}' has a non-numeric value (e.g. a text/list parameter) "
                        "and was not exported as a shared script variable."
                    )
                    continue

                unit = (Utils._safe_getattr(parameter, "unit", "") or "").strip().lower()
                if unit in self.LENGTH_UNITS:
                    kind = "length"
                    value = Utils._param_value_mm(parameter)
                elif unit in self.ANGLE_UNITS:
                    kind = "angle"
                    value = Utils._param_value_degrees(parameter)
                else:
                    kind = "unitless"
                    value = Utils._param_value_number(parameter)

                var_name = name #Utils._safe_var_name(name)
                if keyword.iskeyword(var_name):
                    var_name = f"param_{var_name}"
                base_name = var_name
                suffix = 2
                while var_name in reserved:
                    var_name = f"{base_name}_{suffix}"
                    suffix += 1
                reserved.add(var_name)

                self.parameter_vars[name] = var_name
                self.parameter_kinds[name] = kind
                self.parameter_values[var_name] = value

    def _write_parameter_variables(self):
            if not self.parameter_vars:
                return

            user_params = {
                Utils._safe_getattr(parameter, "name", None): parameter
                for parameter in Utils._iter_fusion_collection(Utils._safe_getattr(self.design, "userParameters", None))
            }

            self.writer.line()
            self.writer.line("# Fusion user parameters -- edit these to keep every dimension that")
            self.writer.line("# reused the same Fusion parameter in sync, just like in Fusion.")
            for name, var_name in self.parameter_vars.items():
                parameter = user_params.get(name)
                if parameter is None:
                    continue
                kind = self.parameter_kinds[name]
                if kind == "length":
                    value_str = Utils._fmt(Utils._param_value_mm(parameter))
                elif kind == "angle":
                    value_str = Utils._fmt(Utils._param_value_degrees(parameter))
                else:
                    value_str = Utils._fmt(Utils._param_value_number(parameter))

                expression = Utils._safe_getattr(parameter, "expression", "") or ""
                self.writer.line(f"{var_name} = {value_str}  # Fusion parameter '{name}' = {expression}")

    def _tokenize_param_expression(self, expression: str):
            pos = 0
            tokens: List[str] = []
            for match in self._EXPR_TOKEN_RE.finditer(expression):
                if match.start() != pos:
                    return None
                token = match.group(0)
                pos = match.end()
                if not token.isspace():
                    tokens.append(token)
            if pos != len(expression):
                return None
            return tokens

    def _translate_param_combination(self, expression: str, kind: str):
            """
            Rewrite a Fusion expression combining registered same-kind user
            parameters via +, -, *, /, and () into the equivalent Python
            expression  Returns None unless the whole
            expression can be proven dimensionally safe to translate.
            """
            if not expression:
                return None

            tokens = self._tokenize_param_expression(expression)
            if not tokens:
                return None

            pos = [0]

            def peek() -> Optional[str]:
                return tokens[pos[0]] if pos[0] < len(tokens) else None

            def advance() -> str:
                token = tokens[pos[0]]
                pos[0] += 1
                return token

            def parse_primary() -> Tuple[str, int]:
                token = peek()
                if token == "(":
                    advance()
                    text, degree = parse_expr()
                    if peek() != ")":
                        raise ValueError("expected )")
                    advance()
                    return f"({text})", degree
                if token is None:
                    raise ValueError("unexpected end of expression")
                if self._IDENTIFIER_RE.match(token):
                    var_name = self.parameter_vars.get(token)
                    if var_name is None or self.parameter_kinds.get(token) != kind:
                        raise ValueError(f"unregistered or mismatched-kind identifier: {token}")
                    advance()
                    return var_name, 1
                if self._NUMBER_RE.match(token):
                    advance()
                    return token, 0
                raise ValueError(f"unexpected token: {token}")

            def parse_unary() -> Tuple[str, int]:
                if peek() in ("+", "-"):
                    sign = advance()
                    text, degree = parse_unary()
                    return f"{sign}{text}", degree
                return parse_primary()

            def parse_term() -> Tuple[str, int]:
                text, degree = parse_unary()
                while peek() in ("*", "/"):
                    op = advance()
                    rhs_text, rhs_degree = parse_unary()
                    text = f"{text} {op} {rhs_text}"
                    degree = degree + rhs_degree if op == "*" else degree - rhs_degree
                return text, degree

            def parse_expr() -> Tuple[str, int]:
                text, degree = parse_term()
                while peek() in ("+", "-"):
                    op = advance()
                    rhs_text, rhs_degree = parse_term()
                    if rhs_degree != degree:
                        raise ValueError("dimensionally inconsistent +/-")
                    text = f"{text} {op} {rhs_text}"
                return text, degree

            try:
                result_text, result_degree = parse_expr()
            except (ValueError, IndexError):
                return None

            if pos[0] != len(tokens):
                return None
            if result_degree != 1:
                return None

            return result_text

    def _param_expr(self, parameter, kind: str = "length") -> Tuple[str, str, bool]:
            """Resolve a Fusion dimension parameter to output text.

            Returns (expr, comment, is_variable). If the parameter's expression
            exactly matches a registered shared user parameter of the same kind,
            expr is that variable's name (kept in sync at the top of the script)
            and comment is empty. If it's a dimensionally-safe combination of
            registered same-kind parameters via +, -, *, /, and () (see
            _translate_param_combination), expr is the equivalent Python
            expression referencing those variables. Otherwise expr is a
            formatted literal and comment documents the original Fusion
            expression, as before.
            """
            if parameter is None:
                return Utils._fmt(0.0), "", False

            model_parameter = adsk.fusion.ModelParameter.cast(parameter) or parameter

            expression = (Utils._safe_getattr(model_parameter, "expression", "") or "").strip()
            var_name = self.parameter_vars.get(expression)
            if var_name is not None and self.parameter_kinds.get(expression) == kind:
                return var_name, "", True

            combined_expr = self._translate_param_combination(expression, kind)
            if combined_expr is not None:
                return combined_expr, "", True

            if kind == "length":
                value_fn = Utils._param_value_mm
            elif kind == "angle":
                value_fn = Utils._param_value_degrees
            else:
                value_fn = Utils._param_value_number

            try:
                raw_value = value_fn(model_parameter)
            except Exception:
                self.unsupported.append(
                    f"A feature dimension (expression: {expression or '?'}) had a non-numeric value "
                    "and was exported as 0; review and fix this value manually."
                )
                raw_value = 0.0

            return Utils._fmt(raw_value), Utils._parameter_comment(model_parameter), False

    def _expr_numeric_value(self, expr: str) -> Optional[float]:
            """Evaluate an exporter-generated parameter expression numerically."""

            try:
                return float(eval(expr, {"__builtins__": {}}, self.parameter_values))
            except Exception:
                return None

    def _angle_expr_preserving_sign(self, parameter) -> Tuple[str, str, bool]:
            """Return an angle expression whose sign matches Fusion's value.

            Fusion can keep a positive user-parameter expression on a one-sided
            revolve while storing the reversed direction in the ModelParameter's
            signed value. _param_expr quite reasonably emits the reusable positive
            variable in that case, so compensate here where the sign controls the
            revolve direction.
            """

            expr, comment, is_var = self._param_expr(parameter, "angle")
            if not is_var:
                return expr, comment, is_var

            model_parameter = adsk.fusion.ModelParameter.cast(parameter) or parameter
            try:
                fusion_value = Utils._param_value_degrees(model_parameter)
            except Exception:
                return expr, comment, is_var

            expr_value = self._expr_numeric_value(expr)
            if expr_value is None or abs(expr_value) < 1e-9 or abs(fusion_value) < 1e-9:
                return expr, comment, is_var

            if expr_value * fusion_value < 0:
                expr = f"-({expr})"
            return expr, comment, is_var

    def _negated_expr(self, expr: str) -> str:
            """Return a readable negation for an emitted numeric expression."""

            stripped = expr.strip()
            if stripped.startswith("-(") and stripped.endswith(")"):
                return stripped[2:-1]
            if stripped.startswith("-") and self._NUMBER_RE.match(stripped[1:]):
                return stripped[1:]
            if self._NUMBER_RE.match(stripped):
                return Utils._fmt(-float(stripped))
            return f"-({stripped})"

    def _sketch_dimensions(self, sketch) -> list:
            if sketch is None:
                return []
            key = id(sketch)
            cached = self._sketch_dimension_cache.get(key)
            if cached is None:
                cached = Utils._iter_fusion_collection(Utils._safe_getattr(sketch, "sketchDimensions", None))
                self._sketch_dimension_cache[key] = cached
            return cached

    @staticmethod
    def _dimension_class_types(class_names: Tuple[str, ...]) -> set:
            class_types = set()
            for name in class_names:
                cls = getattr(adsk.fusion, name, None)
                if cls is None:
                    continue
                try:
                    class_types.add(cls.classType())
                except Exception:
                    continue
            return class_types

    def _entity_dimension_var(
            self,
            sketch,
            entity,
            dimension_class_names: Tuple[str, ...],
            halve: bool = False,
        ) -> Optional[str]:
            """Shared-variable expression for a dimension whose `.entity` is `entity`
            (e.g. a SketchCircle/SketchEllipse dimensioned by a SketchRadialDimension,
            SketchDiameterDimension, or SketchEllipse*RadiusDimension).
            """
            token = Utils._safe_getattr(entity, "entityToken", None)
            if token is None:
                return None

            class_types = self._dimension_class_types(dimension_class_names)
            if not class_types:
                return None

            for dim in self._sketch_dimensions(sketch):
                if Utils._safe_getattr(dim, "objectType", None) not in class_types:
                    continue
                dim_entity = Utils._safe_getattr(dim, "entity", None)
                if Utils._safe_getattr(dim_entity, "entityToken", None) != token:
                    continue

                parameter = adsk.fusion.ModelParameter.cast(Utils._safe_getattr(dim, "parameter", None))
                if parameter is None:
                    continue

                expression = (Utils._safe_getattr(parameter, "expression", "") or "").strip()
                var_name = self.parameter_vars.get(expression)
                if var_name is not None and self.parameter_kinds.get(expression) == "length":
                    return f"{var_name} / 2" if halve else var_name

            return None

    def _circle_radius_dimension_var(self, sketch, circle_entity) -> Optional[str]:
            return self._entity_dimension_var(
                sketch, circle_entity, ("SketchRadialDimension",)
            ) or self._entity_dimension_var(
                sketch, circle_entity, ("SketchDiameterDimension",), halve=True
            )

    def _ellipse_radius_dimension_vars(self, sketch, ellipse_entity) -> Tuple[Optional[str], Optional[str]]:
            major = self._entity_dimension_var(sketch, ellipse_entity, ("SketchEllipseMajorRadiusDimension",))
            minor = self._entity_dimension_var(sketch, ellipse_entity, ("SketchEllipseMinorRadiusDimension",))
            return major, minor

    def _line_length_dimension_var(self, sketch, line_entity, opposite_line_entity=None) -> Optional[str]:
            """Shared-variable expression for a SketchLinearDimension that measures
            either this line's own length (dimensioned between its two endpoints,
            the usual way of dimensioning a single edge) or the distance between
            this line and the parallel opposite edge of a rectangle (the usual
            way of dimensioning a rectangle's overall width/height).
            """
            line_token = Utils._safe_getattr(line_entity, "entityToken", None)
            if line_token is None:
                return None

            start_token = Utils._safe_getattr(Utils._safe_getattr(line_entity, "startSketchPoint", None), "entityToken", None)
            end_token = Utils._safe_getattr(Utils._safe_getattr(line_entity, "endSketchPoint", None), "entityToken", None)
            opposite_token = Utils._safe_getattr(opposite_line_entity, "entityToken", None)

            class_types = self._dimension_class_types(("SketchLinearDimension",))
            if not class_types:
                return None

            for dim in self._sketch_dimensions(sketch):
                if Utils._safe_getattr(dim, "objectType", None) not in class_types:
                    continue

                t1 = Utils._safe_getattr(Utils._safe_getattr(dim, "entityOne", None), "entityToken", None)
                t2 = Utils._safe_getattr(Utils._safe_getattr(dim, "entityTwo", None), "entityToken", None)
                tokens = {t1, t2}

                is_self_length = start_token is not None and end_token is not None and tokens == {start_token, end_token}
                is_edge_distance = opposite_token is not None and tokens == {line_token, opposite_token}
                if not (is_self_length or is_edge_distance):
                    continue

                parameter = adsk.fusion.ModelParameter.cast(Utils._safe_getattr(dim, "parameter", None))
                if parameter is None:
                    continue

                expression = (Utils._safe_getattr(parameter, "expression", "") or "").strip()
                var_name = self.parameter_vars.get(expression)
                if var_name is not None and self.parameter_kinds.get(expression) == "length":
                    return var_name

            return None
