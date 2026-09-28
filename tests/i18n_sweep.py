"""AST visitors that sweep a module's source for untranslated or positional-placeholder strings."""

import ast
import re

TRANSLATION_CALL_NAMES = {"_", "gettext_lazy", "ngettext_lazy"}
# A `%` not followed by `(` (a named placeholder) or `%` (an escaped percent) is
# positional.
POSITIONAL_PLACEHOLDER = re.compile(r"%(?!%|\()[-+ 0#]*\d*(?:\.\d+)?[a-zA-Z]")
FIELD_METADATA_KEYWORDS = {"help_text", "verbose_name", "verbose_name_plural"}
DIAGNOSTIC_MESSAGE_KEYWORDS = {"msg", "message", "hint"}


# ReportRenderer has already %-formatted a translated template by the time a line
# reaches a terminal, so the placeholder shape is only visible in the source, hence a
# static sweep.
class ManagementI18nVisitor(ast.NodeVisitor):
    """Record positional placeholders in translation calls and bare literals in output sinks.

    Sinks are `CommandError`, `self.stdout`/`self.stderr` writes, `add_argument(help=...)`,
    a command's own `help = ...` and yielded rendered lines.
    """

    def __init__(self) -> None:
        self.positional_placeholders: list[str] = []
        self.bare_literals: list[str] = []

    @staticmethod
    def call_name(node: ast.Call) -> str | None:
        """Return the name a call is made through, or None for anything else.

        Args:
            node: The call node.

        Returns:
            The bare name or the trailing attribute of the callee.
        """
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return None

    @staticmethod
    def str_constant(node: ast.expr) -> str | None:
        """Return the node's value when it is a string literal.

        Args:
            node: The expression node.

        Returns:
            The literal, or None when the node is not a string constant.
        """
        return (
            node.value
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            else None
        )

    def visit_Call(self, node: ast.Call) -> None:
        """Record placeholders and bare literals reaching this call."""
        name = self.call_name(node)
        if name in TRANSLATION_CALL_NAMES:
            for arg in node.args:
                literal = self.str_constant(arg)
                if literal is not None and POSITIONAL_PLACEHOLDER.search(literal):
                    self.positional_placeholders.append(literal)
        elif name == "CommandError":
            for arg in node.args:
                literal = self.str_constant(arg)
                if literal is not None:
                    self.bare_literals.append(literal)
        elif name == "write" and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if isinstance(owner, ast.Attribute) and owner.attr in {"stdout", "stderr"}:
                for arg in node.args:
                    literal = self.str_constant(arg)
                    if literal is not None:
                        self.bare_literals.append(literal)
        elif name == "add_argument":
            for kw in node.keywords:
                if kw.arg == "help":
                    literal = self.str_constant(kw.value)
                    if literal is not None:
                        self.bare_literals.append(literal)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Record a bare literal assigned to a command's `help` attribute."""
        if any(
            isinstance(target, ast.Name) and target.id == "help"
            for target in node.targets
        ):
            literal = self.str_constant(node.value)
            if literal is not None:
                self.bare_literals.append(literal)
        self.generic_visit(node)

    def visit_Yield(self, node: ast.Yield) -> None:
        """Record a bare literal yielded as a rendered line."""
        literal = self.str_constant(node.value) if node.value is not None else None
        if literal is not None:
            self.bare_literals.append(literal)
        self.generic_visit(node)


def visit_management_source(source: str) -> ManagementI18nVisitor:
    """Sweep a management module's source with `ManagementI18nVisitor`.

    Args:
        source: The Python source text.

    Returns:
        The visitor after walking the parsed source.
    """
    visitor = ManagementI18nVisitor()
    visitor.visit(ast.parse(source))
    return visitor


class FieldsChecksI18nVisitor(ast.NodeVisitor):
    """Record bare literals in field, check, view and form sinks and positional placeholders.

    Sinks are field `help_text`/`verbose_name` keywords and dict keys, `setdefault` defaults,
    `error_messages` dict values, `ValidationError`/`ImproperlyConfigured` arguments and
    `checks.Warning`/`checks.Error` messages and hints.
    """

    def __init__(self) -> None:
        self.bare_literals: list[str] = []
        self.positional_placeholders: list[str] = []

    @staticmethod
    def str_constant(node: ast.expr) -> str | None:
        """Return the message text under a node, unwrapping `%` interpolation and f-strings.

        Args:
            node: The expression node.

        Returns:
            The literal, the source text of an f-string, or None for anything else.
        """
        # Interpolated messages put a `%` BinOp where the literal would sit.
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            node = node.left
        if isinstance(node, ast.JoinedStr):
            return ast.unparse(node)
        return (
            node.value
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            else None
        )

    def visit_Call(self, node: ast.Call) -> None:
        """Record placeholders and bare literals reaching this call."""
        func = node.func
        is_validation_error = isinstance(func, ast.Name) and func.id in {
            "ValidationError",
            "ImproperlyConfigured",
        }
        is_checks_diagnostic = (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "checks"
            and func.attr in {"Warning", "Error"}
        )
        is_translation_call = (
            isinstance(func, ast.Name) and func.id in TRANSLATION_CALL_NAMES
        )
        if is_translation_call:
            for arg in node.args:
                literal = self.str_constant(arg)
                if literal is not None and POSITIONAL_PLACEHOLDER.search(literal):
                    self.positional_placeholders.append(literal)
        if is_validation_error or is_checks_diagnostic:
            for arg in node.args:
                literal = self.str_constant(arg)
                if literal is not None:
                    self.bare_literals.append(literal)
            for kw in node.keywords:
                if kw.arg in DIAGNOSTIC_MESSAGE_KEYWORDS:
                    literal = self.str_constant(kw.value)
                    if literal is not None:
                        self.bare_literals.append(literal)
        elif isinstance(func, ast.Attribute) and func.attr == "setdefault":
            if (
                len(node.args) == 2
                and self.str_constant(node.args[0]) in FIELD_METADATA_KEYWORDS
            ):
                literal = self.str_constant(node.args[1])
                if literal is not None:
                    self.bare_literals.append(literal)
        else:
            for kw in node.keywords:
                if kw.arg in FIELD_METADATA_KEYWORDS:
                    literal = self.str_constant(kw.value)
                    if literal is not None:
                        self.bare_literals.append(literal)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Record bare literals among the values of an `error_messages` dict."""
        names = {target.id for target in node.targets if isinstance(target, ast.Name)}
        if names & {"error_messages", "default_error_messages"} and isinstance(
            node.value, ast.Dict
        ):
            for value in node.value.values:
                literal = self.str_constant(value)
                if literal is not None:
                    self.bare_literals.append(literal)
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        """Record bare literals under field-metadata keys of any dict literal."""
        # ConceptsField builds its through model's Meta as `type("Meta", (), {...})`, so
        # the metadata sits in a positional dict a keyword check never sees.
        for key, value in zip(node.keys, node.values, strict=True):
            name = self.str_constant(key) if key is not None else None
            if name in FIELD_METADATA_KEYWORDS:
                literal = self.str_constant(value)
                if literal is not None:
                    self.bare_literals.append(literal)
        self.generic_visit(node)


def visit_fields_checks_source(source: str) -> FieldsChecksI18nVisitor:
    """Sweep a fields, checks, views or forms module's source with `FieldsChecksI18nVisitor`.

    Args:
        source: The Python source text.

    Returns:
        The visitor after walking the parsed source.
    """
    visitor = FieldsChecksI18nVisitor()
    visitor.visit(ast.parse(source))
    return visitor
