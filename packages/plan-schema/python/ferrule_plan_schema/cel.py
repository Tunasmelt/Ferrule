from __future__ import annotations

import multiprocessing
from dataclasses import dataclass
from multiprocessing.connection import Connection

import celpy
from celpy.adapter import json_to_cel
from celpy.celtypes import MapType
from lark import Token, Tree

MAX_EVALUATION_SECONDS = 1.0
MAX_STARTUP_SECONDS = 10.0
_NAMESPACES = frozenset({"input", "response"})
_MACROS = frozenset({"all", "exists", "exists_one", "filter", "map"})


class CELCompileError(ValueError):
    """The CEL source is invalid for Ferrule's restricted environment."""


class CELEvaluationError(RuntimeError):
    """CEL evaluation failed or exceeded its limit."""


@dataclass(frozen=True)
class CompiledExpression:
    source: str


def _identifier(tree: Tree[Token]) -> str | None:
    identifiers = [
        str(node.children[0])
        for node in tree.iter_subtrees()
        if node.data == "ident"
    ]
    return identifiers[0] if len(identifiers) == 1 else None


def _validate_names(tree: Tree[Token], scope: frozenset[str]) -> None:
    if tree.data == "ident":
        name = str(tree.children[0])
        if name not in scope:
            raise CELCompileError(f"undeclared CEL variable {name!r}")
        return

    if tree.data == "member_dot_arg" and len(tree.children) == 3:
        receiver, function, arguments = tree.children
        if isinstance(receiver, Tree):
            _validate_names(receiver, scope)
        if str(function) in _MACROS and isinstance(arguments, Tree):
            expressions = [child for child in arguments.children if isinstance(child, Tree)]
            if expressions:
                local = _identifier(expressions[0])
                if local is not None:
                    for expression in expressions[1:]:
                        _validate_names(expression, scope | {local})
                    return
        if isinstance(arguments, Tree):
            _validate_names(arguments, scope)
        return

    for child in tree.children:
        if isinstance(child, Tree):
            _validate_names(child, scope)


def _environment() -> celpy.Environment:
    return celpy.Environment(annotations={"input": MapType, "response": MapType})


def compile_expression(source: str) -> CompiledExpression:
    """Parse CEL and reject names outside input/response and macro locals."""
    try:
        tree = _environment().compile(source)
        _validate_names(tree, _NAMESPACES)
    except CELCompileError:
        raise
    except Exception as error:
        raise CELCompileError(f"invalid CEL expression: {error}") from error
    return CompiledExpression(source)


def _run(
    source: str,
    input_value: dict[str, object],
    response_value: dict[str, object],
    connection: Connection,
) -> None:
    try:
        environment = _environment()
        program = environment.program(environment.compile(source))
        connection.send(("ready", None))
        result = program.evaluate(
            {
                "input": json_to_cel(input_value),
                "response": json_to_cel(response_value),
            }
        )
        connection.send(("ok", result))
    except BaseException as error:
        connection.send(("error", f"{type(error).__name__}: {error}"))
    finally:
        connection.close()


def evaluate(
    compiled: CompiledExpression,
    input: dict[str, object],
    response: dict[str, object],
) -> object:
    """Evaluate with only input/response, enforcing a killable wall-clock limit."""
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_run, args=(compiled.source, input, response, child))
    try:
        process.start()
        child.close()
        if not parent.poll(MAX_STARTUP_SECONDS):
            raise CELEvaluationError("CEL evaluation worker failed to start")
        state, value = parent.recv()
        if state == "error":
            raise CELEvaluationError(f"CEL evaluation failed: {value}")
        if not parent.poll(MAX_EVALUATION_SECONDS):
            process.terminate()
            process.join()
            raise CELEvaluationError(
                f"CEL cost limit exceeded ({MAX_EVALUATION_SECONDS:g}s wall clock)"
            )
        state, value = parent.recv()
        process.join()
    except CELEvaluationError:
        raise
    except Exception as error:
        if process.is_alive():
            process.terminate()
            process.join()
        raise CELEvaluationError(f"CEL evaluation failed: {error}") from error
    finally:
        parent.close()
        if process.is_alive():
            process.terminate()
            process.join()
    if state != "ok":
        raise CELEvaluationError(f"CEL evaluation failed: {value}")
    return value


def registered_functions() -> frozenset[str]:
    """Return the functions present in a normal celpy activation."""
    environment = _environment()
    runner = environment.program(environment.compile("true"))
    return frozenset(runner.new_activation().functions)
