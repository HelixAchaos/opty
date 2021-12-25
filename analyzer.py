import ast
import collections
from collections import ChainMap
import sys
from types import FunctionType, ModuleType
from typing import Union, Iterator, get_origin, get_args, Optional, TypeVar
# from pydoc import safeimport, locate
from pprint import pprint

import typed_ast
import typing

import typeshed_client.parser
from typeshed_client import ImportedName

from shared_state import builtin
from models import Scope


def _print(a):
    print(ast.dump(a, indent=4))


def ast_to_type(c: ast.AST, state: Scope) -> type:  # | tuple[type]
    if isinstance(c, typed_ast._ast3.Name):
        return state.load(c.id)
    elif isinstance(c, typed_ast._ast3.Subscript):
        return ast_to_type(c.value.id)[ast_to_type(c.slice.value, state)]
    elif isinstance(c, typed_ast._ast3.Tuple):
        return tuple(ast_to_type(elt, state) for elt in c.elts)
    elif isinstance(c, typed_ast._ast3.BinOp):
        return ast_to_type(c.left, state) | ast_to_type(c.right, state)
    print(c)


# def resolve_generic_attr(cls: type, attr: str) -> type: ...
# def match_gen(gen: type, conc: type, state: dict) -> bool:
#     print(8, ast_to_type(gen, state), conc)


def lookup_call_result(typ: type | ModuleType, _func_name: str, args: tuple[type] | tuple[()], state: dict) -> type:
    _namespace = get_origin(typ) or typ  # get_origin(str) is None

    func = state[_namespace.__name__].child_nodes[_func_name].ast

    # todo: @overload
    # if isinstance(func, typeshed_client.parser.OverloadedName):
    #     defs = func.definitions
    #     for i, defin in enumerate(defs):
    #         if len(defin.args.args) != len(args):
    #             continue
    #
    #         print(i, len(defin.args.args), len(args), args, defin.args.args[0].annotation.__dict__)
    #         for a, b in zip((arg.annotation for arg in defin.args.args), args):
    #             match_gen(a, b, state)
    # print(vars(defin.args))
    ret = func.returns
    return ast_to_type(ret, state)


def lookup_call_args(typ: type | ModuleType, _func_name: str, state: dict) -> list[type]:
    # need to handle @overload.
    _namespace = get_origin(typ) or typ  # get_origin(str) is None
    args = state[_namespace.__name__].child_nodes[_func_name].ast.args.args
    return [ast_to_type(arg.annotation, state) for arg in args]


def resolve_generic_func(cls: type, func_name: str, args: tuple[type] | tuple[()], state: dict) -> type:
    bases = [ast_to_type(base, state) for base in state[cls.__name__].ast.bases]
    print(f"{bases=}")

    ret = lookup_call_result(cls, func_name, args, state)

    def find_gen(c):
        if isinstance(c, tuple):
            return any(map(find_gen, c))
        elif isinstance(c, typing.TypeVar):
            return True
        elif c is None:
            return False
        else:
            return any(map(find_gen, get_args(c)))

    if not find_gen(ret):
        # the function doesn't dependent on a generic
        return ret
    try:
        generic = next(filter(lambda b: get_origin(b) is typing.Generic, bases))
    except StopIteration:
        # no generic
        return ret
    else:
        gens = get_args(generic)
        args_ts = lookup_call_args(cls, func_name, state)
        decos = {name.id for name in state[(get_origin(cls) or cls).__name__].child_nodes[func_name].ast.decorator_list}

        gen_dict = {}

        def assign_gen(gen: type, conc: type) -> None:
            if isinstance(gen, typing.TypeVar):
                gen_dict[str(gen)] = conc
                return
            ar = get_args(gen)
            if ar is None:
                return
            else:
                co = get_args(conc)
                for a, c in zip(ar, co):
                    assign_gen(a, c)

        if 'classmethod' in decos:
            pass
            # args_ts[0] = cls
        elif 'staticmethod' in decos:
            pass
        else:
            if args_ts[0] is None:
                args_ts = [generic] + args_ts[1:]

        for a, b in zip(args_ts, args):
            assign_gen(a, b)

        def fill_gen(gen: type) -> type:
            if isinstance(gen, typing.TypeVar):
                return gen_dict[str(gen)]
            ar = get_args(gen)
            if not ar:
                return gen
            else:
                return get_origin(gen)[tuple(map(fill_gen, ar))]

        return fill_gen(ret)


def resolve_generic_init(construct_class: type, args: tuple[type], state: Scope) -> type:
    """
    todo: when @overload is supported, depecrate this. replace with:
        `resolve_generic_func(construct_class, '__init__'|'__new__', args, state)
    :param construct_class:
    :param args:
    :param state:
    :return:
    """

    cls = get_args(construct_class)

    #  resolve_generics(typing.Generator[~_T, ~_O, str], list[int]) -> typing.Iterator[int, ~_O, str]
    #     note: class list(MutableSequence[_T], Generic[_T]):
    if issubclass(cls, (list, tuple, set, frozenset)):
        # tuple(list[int | str]) -> we don't know if it's `tuple[int, str]` or whateva. lossy, so better to be general and right.
        if cls is get_args(args[0]):
            return construct_class
        return cls[get_args(resolve_generic_func(args[0], '__iter__', (args[0],), state))]
    elif issubclass(cls, dict):
        print(1, args[0])
        if issubclass(args[0], dict):
            return args[0]
        else:
            a = []
            b = []
            print(args[0])
            for i, c in enumerate(map(get_args, get_args(args[0]))):
                if len(c) == 0:
                    a.append(typing.Any)
                    b.append(typing.Any)
                elif len(c) == 1:
                    a.append(c[0])
                    b.append(c[0])
                elif len(c) == 2:
                    a.append(c[0])
                    b.append(c[1])
                else:
                    raise ValueError(f"dictionary update sequence element #{i} has length {len(c)}; 2 is required")
            return dict[Union[tuple(a)], Union[tuple(b)]]
        # return cls[get_args(resolve_generic_func(args[0], '__iter__', (args[0],), global_state))]
    elif issubclass(cls, enumerate):
        return enumerate[get_args(resolve_generic_func(args[0], '__iter__', (args[0],), state))]
    elif issubclass(cls, zip):
        return zip[tuple(get_args(resolve_generic_func(a, '__iter__', (a,), state)) for a in args)]
        # zip ain't tested
    else:
        raise NotImplementedError(f'{type(construct_class)=}')


def _next(typ: collections.abc.Iterator | collections.abc.Generator) -> type:
    if get_origin(typ) is collections.abc.Iterator:
        return get_args(typ)[0]
    elif get_origin(typ) is collections.abc.Generator:
        raise NotImplementedError("Didn't do generators yet")


def get_type(node: ast.expr | ast.stmt | ast.AST, state: Scope) -> Optional[type]:
    """

    :param node:
    :param _state:
    :return: `None` if statement.
    """
    # _locals was a parameter
    # if _locals is None:
    #     _locals = {}
    #
    # state = global_state | _locals

    _print(node)
    if isinstance(node, ast.Expr):
        return get_type(node.value, state)
    elif isinstance(node, ast.Constant):
        # handles numeric, string, and None
        return type(node.value)
    elif isinstance(node, ast.List):
        return list[Union[tuple(get_type(elt, state) for elt in node.elts)]]
    elif isinstance(node, ast.ListComp):
        locco = Scope(node, state, is_comp_gen=True)
        for gen in node.generators:
            locco.store(gen.target.id, _next(resolve_generic_func(b := get_type(gen.iter, state), '__iter__', (b,), state)))
        return get_type(node.elt, locco)
        # name, ctx = node.elt.id, node.elt.ctx
        # if isinstance(ctx, ast.Load):
        #     for gen in node.generators:
        #         if gen.target.id == name:
        #             # TODO: check if this should be using `get_full_name`
        #             return list[]
        #     # if the name ain't in the for-loops (ie. outside the list comprehension)
        #     return list[state[name]]
        # elif isinstance(ctx, ast.Store):
        #     return list[get_type(node.elt.value)]
    elif isinstance(node, ast.Tuple):
        # ignore positionals.
        return tuple[Union[tuple(get_type(elt, state) for elt in node.elts)]]
    elif isinstance(node, ast.Dict):
        return dict
    elif isinstance(node, ast.DictComp):
        # Scope(node, state, is_comp_gen=True)
        return dict
    elif isinstance(node, ast.Set):
        return set[Union[tuple(get_type(elt, state) for elt in node.elts)]]
    elif isinstance(node, ast.SetComp):
        locco = Scope(node, state, is_comp_gen=True)
        for gen in node.generators:
            locco.store(gen.target.id, _next(resolve_generic_func(b := get_type(gen.iter, state), '__iter__', (b,), state)))
        return get_type(node.elt, locco)
    elif isinstance(node, ast.Starred):
        # isinstance(node.ctx, ast.Assign) will be handled in isinstance(node, ast.Assign)
        b = get_type(node.value, state)  # walrus should be handled here. (e.g. "[*[a:=3]]")
        typ = resolve_generic_func(b, '__iter__', (b,), state)
        return _next(typ)
    elif isinstance(node, ast.NamedExpr):
        v = state.store(node.target.id, get_type(node.value, state))
        return v
    elif isinstance(node, ast.Name):
        if not isinstance(node.ctx, ast.Load):
            raise Exception(f"ast.Name {node.id=} ain't loading {node.ctx=}. Assignment and Del should've been handled earlier.")
        return state.load(node.id)
    elif isinstance(node, ast.Assign):
        value = get_type(node.value, state)
        for target in node.targets:
            if isinstance(target, ast.Name):
                state.store(target.id, value)
            elif isinstance(target, ast.Tuple):
                # todo: look at literals to store positionals.

                """
                >>> *a,b='123'
                # a == ['1', '2']
                # b == '3'
                >>> a,*b,c = '1234'
                # a == '1'
                # b == ['2', '3']
                # c ==  '4'
                >>> a,*b,*c = '12341546'
                SyntaxError: multiple starred expressions in assignment
                """

                def helper(target: ast.Tuple | ast.Name | ast.Starred, _state: Scope, value: type) -> None:
                    if isinstance(target, ast.Name):
                        _state[-1][target.id] = value
                    elif isinstance(target, ast.Tuple):
                        if get_origin(value) is Union:
                            n = Union[tuple(filter(None, (get_args(t) for t in get_args(value))))[0]]
                        else:
                            n = _next(resolve_generic_func(value, '__iter__', (value,), state))
                        for elt in target.elts:
                            helper(elt, _state, n)
                    elif isinstance(target, ast.Starred):
                        typ = list[value]
                        helper(target.value, _state, typ)

                # *a,(b, (d, *c)) = ['123', 1, ['abc', [1,2,3]]]
                helper(target, state, value)
        return None
    elif isinstance(node, (ast.Index, ast.ExtSlice, ast.Num, ast.Str, ast.Bytes, ast.NameConstant, ast.Ellipsis)):
        raise DeprecationWarning

    # del doesn't affect global by default.


"""
constant, list, listcomp, starred?,

tuple, dict, dictcomp, set, setcomp 
"""

code = ast.parse("[b:=(a, 2) for a in '123']")
_globals = Scope(meat=code, parent_scope=builtin)
_globals._import('random')
print(ast_to_type(_globals.load('random'), _globals))
# print(9, code, globals)
# print(globals.load('b'))

# print(9, get_type(ast.parse("c,*a,b='123'").body[0], st))
# print(9, get_type(ast.parse("*a,(b, (d, *c))=['123', 1, ['abc', [1,2,3]]]").body[0], st))

# print(1, get_type(ast.parse("emumerate([1,2,3,'a','s'])").body[0].value, st))
# print(1, get_type(ast.parse("[a for a, b in emumerate([1,2,3,'a','s'])]").body[0].value, st))  # tuple unpacking test


# print(1, get_type(ast.parse("[(a:=3, b:=a) for a in [1,2,3,'a']]").body[0].value, st))
# print(1, get_type(ast.parse("[1,2,3] + [1,2,'']").body[0].value))
# print(4, get_type(ast.parse("dict.fromkeys([1,2,3], 'foo')").body[0].value))  # dict[int, str]

"""
generator expressions/comps <- walrus operator assigns to outer scope
"""

# print(3, get_type(ast.parse("[*[1,3,4], *'asdf']").body[0].value, st))


"""
class tuple(Sequence[_T_co], Generic[_T_co]):
    def __new__(cls: Type[_T], __iterable: Iterable[_T_co] = ...) -> _T: ...
    @overload
    def __add__(self, __x: Tuple[_T_co, ...]) -> Tuple[_T_co, ...]: ..."""
