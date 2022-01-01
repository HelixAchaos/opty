# Like a Linked List Stack.
import ast
import dataclasses
import importlib
import inspect
import os
from collections import deque, defaultdict
from copy import deepcopy
from types import FunctionType
from typing import Optional
from ast import Assign, AnnAssign, AugAssign, NamedExpr, NodeVisitor, AST, parse, Name, Tuple, Starred, ClassDef, FunctionDef, AsyncFunctionDef, DictComp, \
    ListComp, SetComp, Global, Nonlocal, comprehension, GeneratorExp, List

from pathlib import Path

import setuptools.errors
import typed_ast
import typeshed_client
import typing
from typeshed_client import NameInfo, ImportedName

from errors import ErrorDuringImport, TypeVarImmutabilityViolation

types = {}



class AssignSniffer(NodeVisitor):
    """
    visit should receive the body of a function, class, generatorexp/comprehension, etc.

    FunctionDef.body, comprehension

    for modules? doesn't matter.
    """

    def __init__(self, locals: set, is_comp_gen: bool = False):
        super(AssignSniffer, self).__init__()
        self.locals = locals
        self.is_comp_gen = is_comp_gen

    def generic_visit(self, node: AST) -> typing.Any:
        NodeVisitor.generic_visit(self, node)

    def visit_Assign(self, node: Assign) -> typing.Any:
        if self.is_comp_gen:
            return None
        for target in node.targets:
            if isinstance(target, Name):
                self.locals.add(target.id)
            elif isinstance(target, Tuple):
                queue = deque(target.elts)
                while queue:
                    elt = queue.popleft()
                    if isinstance(elt, Name):
                        self.locals.add(elt.id)
                    elif isinstance(elt, Starred):
                        self.locals.add(elt.value.id)
                    elif isinstance(elt, Tuple):
                        queue.extend(elt.elts)
        self.visit(node.value)

    def visit_AnnAssign(self, node: AnnAssign) -> typing.Any:
        if self.is_comp_gen:
            return None
        self.locals.add(node.target.id)
        self.visit(node.value)

    def visit_AugAssign(self, node: AugAssign) -> typing.Any:
        if self.is_comp_gen:
            return None
        self.locals.add(node.target.id)
        self.visit(node.value)

    def visit_NamedExpr(self, node: NamedExpr) -> typing.Any:
        self.locals.add(node.target.id)
        self.visit(node.value)

    def visit_ClassDef(self, node: ClassDef) -> typing.Any:
        # class, so do nothing
        return None

    def visit_FunctionDef(self, node: FunctionDef) -> typing.Any:
        # func, so do nothing
        return None

    def visit_AsyncFunctionDef(self, node: AsyncFunctionDef) -> typing.Any:
        # func, so do nothing
        return None

    def visit_ListComp(self, node: ListComp) -> typing.Any:
        # walrus
        self.visit(node.elt)

        if self.is_comp_gen:
            self.is_comp_gen = False
            for comp in node.generators:
                queue = deque([comp.target])
                while queue:
                    elt = queue.popleft()
                    if isinstance(elt, Name):
                        self.locals.add(elt.id)
                    elif isinstance(elt, Starred):
                        queue.append(elt.value)
                    elif isinstance(elt, (Tuple, List)):
                        queue.extend(elt.elts)

    def visit_SetComp(self, node: SetComp) -> typing.Any:
        # walrus
        self.visit(node.elt)

        if self.is_comp_gen:
            self.is_comp_gen = False
            for comp in node.generators:
                queue = deque([comp.target])
                while queue:
                    elt = queue.popleft()
                    if isinstance(elt, Name):
                        self.locals.add(elt.id)
                    elif isinstance(elt, Starred):
                        queue.append(elt.value)
                    elif isinstance(elt, (Tuple, List)):
                        queue.extend(elt.elts)

    def visit_GeneratorExp(self, node: GeneratorExp) -> typing.Any:
        # walrus
        self.visit(node.elt)

        if self.is_comp_gen:
            self.is_comp_gen = False
            for comp in node.generators:
                queue = deque([comp.target])
                while queue:
                    elt = queue.popleft()
                    if isinstance(elt, Name):
                        self.locals.add(elt.id)
                    elif isinstance(elt, Starred):
                        queue.append(elt.value)
                    elif isinstance(elt, (Tuple, List)):
                        queue.extend(elt.elts)

    def visit_DictComp(self, node: DictComp) -> typing.Any:
        # walrus
        # walrus
        self.visit(node.key)
        self.visit(node.value)

        if self.is_comp_gen:
            self.is_comp_gen = False
            for comp in node.generators:
                queue = deque([comp.target])
                while queue:
                    elt = queue.popleft()
                    if isinstance(elt, Name):
                        self.locals.add(elt.id)
                    elif isinstance(elt, Starred):
                        queue.append(elt.value)
                    elif isinstance(elt, (Tuple, List)):
                        queue.extend(elt.elts)


class GlobalAndNonlocalSniffer(NodeVisitor):
    """
    visit should receive the body of a function, class, generatorexp/comprehension, etc.
    for modules? doesn't matter.
    """

    def __init__(self, globals: set, nonlocals: set):
        super(GlobalAndNonlocalSniffer, self).__init__()
        self.globals = globals
        self.nonlocals = nonlocals

    def generic_visit(self, node: AST) -> typing.Any:
        NodeVisitor.generic_visit(self, node)

    def visit_Global(self, node: Global) -> typing.Any:
        self.globals.update(node.names)

    def visit_Nonlocal(self, node: Nonlocal) -> typing.Any:
        self.nonlocals.update(node.names)

    def visit_ClassDef(self, node: ClassDef) -> typing.Any:
        # class, so do nothing
        return None

    def visit_FunctionDef(self, node: FunctionDef) -> typing.Any:
        # func, so do nothing
        return None

    def visit_AsyncFunctionDef(self, node: AsyncFunctionDef) -> typing.Any:
        # func, so do nothing
        return None


NotFound = typing.TypeVar("NotFound")


class TypeObject:
    def __init__(self, name: Optional[str], bases: set[str], args: tuple['TypeObject'] = None) -> None:
        self.name = name
        self.data = {}
        self.bases: set[str] = bases  # not dict because the bases' definitions may be dependent on self.
        self.args = (ANY, ) if args is None else args
        types[self.name] = self

    def __getitem__(self, item: str) -> typing.Union['TypeObject', 'BaseObject']:
        return self.data[item]

    def __setitem__(self, key: str, value: typing.Union['TypeObject', 'BaseObject']) -> None:
        self.data[key] = value

    def __lt__(self, superclass: 'TypeObject') -> bool:
        if isinstance(superclass, _Any):
            return True
        if isinstance(superclass, _Union):
            return any(self < arg for arg in superclass.args)
        elif isinstance(superclass, TypeObject):
            if all(a <= superclass for a in self.args):
                return any(types[base] <= superclass for base in self.bases)
            return False

    def __eq__(self, other: 'TypeObject') -> bool:
        if isinstance(other, (_Union, _Any)):
            return False
        if self is other:
            return True

        return self.name == other.name  # would rather this not be relied on as types should be singletons.

    def __le__(self, other: 'TypeObject') -> bool:
        return self == other or self < other

    def __or__(self, other: 'TypeObject') -> 'TypeObject':
        if isinstance(other, _Any):
            return ANY

        if isinstance(other, _Union):
            shared_names = self.data.keys() & other.data.keys()
            data = {name: self[name] | other[name] for name in shared_names}
            return _Union(self, other, data=data)
        elif isinstance(other, TypeObject):
            if self == other:
                return self
            else:
                shared_names = self.data.keys() & other.data.keys()
                data = {name: self[name] | other[name] for name in shared_names}
                return _Union(self, other, data=data)


class _Any(TypeObject):
    def __lt__(self, other):
        return False

ANY = _Any('Any', set(), ())  # third arg is to avoid circular


def onion(args: tuple[TypeObject]) -> TypeObject:
    if len(args) == 1:
        return args[0]
    else:
        return _Union(*args)


class _Union(TypeObject):
    def __init__(self, *args: TypeObject, data: Optional[dict] = None):
        self.args = args
        super().__init__(name=None, bases=set.intersection(*(arg.bases for arg in self.args)))

        if data is None:
            names = set.intersection(*(set(arg.data.keys()) for arg in self.args))
            data = {name: [] for name in names}
            for name, ah in self.data.items():
                for arg in self.args:
                    ah.append(arg[name])

            self.data = {name: _Union(*args) for name, args in data.items()}

        else:
            self.data = data

    def __getitem__(self, item: str) -> typing.Union['TypeObject', 'BaseObject']:
        return self.data[item]

    def __setitem__(self, key: str, value: typing.Union['TypeObject', 'BaseObject']) -> None:
        self.data[key] = value

    def __lt__(self, superclass: TypeObject) -> bool:
        if isinstance(superclass, _Any):
            return True
        return all(arg < superclass for arg in self.args)
        # if isinstance(superclass, _Union):
        #     return all(arg < superclass for arg in self.args)
        # elif isinstance(superclass, TypeObject):
        #     return all(arg < superclass for arg in self.args)

    def __eq__(self, other: TypeObject) -> bool:
        if isinstance(other, (_Union, _Any)):
            return False
        return self is other

    def __le__(self, other: TypeObject) -> bool:
        return self == other or self < other

    def __or__(self, other: TypeObject) -> '_Union':
        if isinstance(other, _Any):
            return ANY

        if self == other:
            return self

        if isinstance(other, _Union):
            shared_names = self.data.keys() & other.data.keys()
            data = {name: self[name] | other[name] for name in shared_names}
            args = set(self.args) | set(other.args)  # make sure TypeObjects are unique as possible, by design
            return _Union(*args, data=data)
        elif isinstance(other, TypeObject):
            if other in self.args:
                return self
            else:
                shared_names = self.data.keys() & other.data.keys()
                data = {name: self[name] | other[name] for name in shared_names}
                return _Union(*self.args, other, data=data)


class TypeV(TypeObject):
    def __init__(self, name: str, *constraints, bound=None, covariant: bool = False, contravariant: bool = False) -> None:
        super().__init__(name, set())
        # todo: consider handling covariants and contravariants? rn, only treated as free-variables.

    def __setitem__(self, key, value):
        raise TypeVarImmutabilityViolation(f"Attempted to assign ({value=}) to TypeVar({self.name})'s ({key=})")

    def __getitem__(self, item):
        raise TypeVarImmutabilityViolation(f"Attempted to access TypeVar({self.name})'s ({item=})")

    def __eq__(self, other):
        if isinstance(other, TypeV):
            return self.name == other.name
        return False

    def __lt__(self, other):  # either == or !=. covariant, contravariant, etc. handling will change this, but not rn.
        return False


class BaseObject:
    def __init__(self, typ_name: str) -> None:
        self._typ: str = typ_name
        self.data: dict[str, typing.Union[TypeObject, 'BaseObject']] = {}

    def __getitem__(self, item) -> typing.Union[TypeObject, 'BaseObject']:
        if item in self.data:
            return self.data[item]
        else:
            return self.typ[item]

    def __setitem__(self, key: str, value: typing.Union[TypeObject, 'BaseObject']) -> None:
        self.data[key] = value

    @property
    def typ(self) -> TypeObject:
        return types[self._typ]

    def __eq__(self, other):
        # doesn't care about type equality
        return self.data == other.data


class Literal(TypeObject):
    def __init__(self, name: str, vals: tuple[BaseObject]) -> None:
        super().__init__(name, set())
        self.vals = vals
        self._val_types: set[TypeObject] = {val.typ for val in self.vals}

    def __lt__(self, other: TypeObject) -> bool:
        if self == other:
            return False

        if isinstance(other, Literal):
            o_vals = set(other.vals)
            return all(val in o_vals for val in self.vals)
        else:
            return all(t <= other for t in self._val_types)  # type check

    def __eq__(self, other: TypeObject) -> bool:
        if isinstance(other, Literal):
            if len(self.vals) != other.vals:
                return False
            return all(a._typ == b._typ and a == b for a, b in zip(self.vals, other.vals))
        return False

    def __le__(self, other: TypeObject) -> bool:
        return self == other or self < other


@dataclasses.dataclass
class argument:
    name: str
    _type: TypeObject


@dataclasses.dataclass
class arguments:
    # posonlyargs  # not needed rn.
    args: tuple[argument] = dataclasses.field(default_factory=tuple)
    varargs: Optional[argument] = dataclasses.field(default_factory=None)
    kwonlyargs: tuple[argument] = dataclasses.field(default_factory=tuple)
    kwonlydefaults: tuple[TypeObject] = dataclasses.field(default_factory=tuple)
    varkw: Optional[argument] = dataclasses.field(default_factory=None)
    defaults: tuple[TypeObject] = dataclasses.field(default_factory=tuple)

    def __init__(self, args: tuple[argument], varargs: argument, kwonlyargs: tuple[argument], kwonlydefaults: tuple[TypeObject], varkw: argument,
                 defaults: tuple[TypeObject]) -> None:
        self.args = () if args is None else tuple(args)
        self.varargs = varargs
        self.kwonlyargs = () if args is None else kwonlyargs
        self.kwonlydefaults = () if args is None else kwonlydefaults
        self.varkw = varkw
        self.defaults = () if args is None else defaults

    def __iter__(self):
        for field in dataclasses.fields(self):
            yield getattr(self, field.name)


class Function(BaseObject):
    def __init__(self, decorator_list: list[str], annotations: list[tuple[arguments, TypeObject]]) -> None:
        super().__init__('types.FunctionType')
        self.decorator_list = decorator_list
        self.is_overloaded = 'overload' in self.decorator_list
        self.annotations: list[tuple[arguments, TypeObject]] = annotations  # is a list bc possibly overloaded

    def returns(self, argumes: tuple[TypeObject] = (), keygumes: dict[str, TypeObject] = None):
        """inspect.getfullargspec(func)
        Get the names and default values of a Python function’s arguments. A named tuple is returned:
        FullArgSpec(args, varargs, varkw, defaults, kwonlyargs, kwonlydefaults,
                    annotations)
        - args is a list of the argument names.
        - varargs and varkw are the names of the * and ** arguments or None
        - defaults is an n-tuple of the default values of the last n arguments, or None if there are no default arguments.
        - kwonlyargs is a list of keyword-only argument names.
        - kwonlydefaults is a dictionary mapping names from kwonlyargs to defaults.
        - annotations is a dictionary mapping argument names to annotations."""

        """ at least some are: Optional[list]
        {'args': [<typed_ast._ast3.arg obj],       # args
        'vararg': <typed_ast._ast3.arg object>,    # varargs
        'kwonlyargs': [],                          # kwonlyargs
        'kw_defaults': [],                         # kwonlydefaults      # unnecessary for now
        'kwarg': <typed_ast._ast3.arg object>,     # varkw
        'defaults': []}                            # defaults            # unnecessary for now
        """

        """
        >>> f = lambda func:inspect.getfullargspec(func)
        >>> def g(a, b, *c, d, e=1, **f):...
        >>> f(g)
        FullArgSpec(args=['a', 'b'], varargs='c', varkw='f', defaults=None, kwonlyargs=['d', 'e'], kwonlydefaults={'e': 1}, annotations={})
        >>> def h(a=3):...
        >>> f(h)
        FullArgSpec(args=['a'], varargs=None, varkw=None, defaults=(3,), kwonlyargs=[], kwonlydefaults=None, annotations={})
        """
        keygumes = {} if keygumes is None else keygumes

        if self.is_overloaded:
            for overloaded_func_candidate in self.annotations:  # the more specific args_annotations should be first
                (args, varargs, kwonlyargs, kwonlydefaults, varkw, defaults), ret = overloaded_func_candidate
                # posonly may be supported later, but typeshed doesn't really use them.

                a_list = [arg.name for arg in args[:len(args) - len(defaults)]]
                for a, d in zip(args[len(args) - len(defaults):], defaults):
                    a_list.append(f"{a}={d}")
                if varargs is not None:
                    a_list.append(f"*{varargs.name}")

                k_list = [kwa.name for kwa in kwonlyargs[:len(kwonlyargs) - len(kwonlydefaults)]]
                for ka, kd in zip(kwonlyargs[len(kwonlyargs) - len(kwonlydefaults):], kwonlydefaults):
                    k_list.append(f"{ka}={kd}")
                if varkw is not None:
                    k_list.append(f"**{varkw.name}")

                names = [arg.name for arg in args] + ([] if varargs is None else [varargs]) + [kwa.name for kwa in kwonlyargs] + ([] if varkw is None else
                                                                                                                                  [varkw])
                func_code = "lambda " + ','.join(a_list + k_list) + ':' + ' and '.join(f"name._type < {name._type}" for name in names)
                print(func_code)

                func = eval(func_code)
                try:
                    type_check = func(*argumes, **keygumes)
                except TypeError:
                    continue
                else:
                    if type_check:
                       return ret
                    else:
                        continue

            if len(self.annotations) == 0:
                return Exception(f"Overloaded function has an empty `annotations` field ")
            else:
                return Exception(f"args/kwargs don't match any overloaded annotations")
        else:
            return self.annotations[0][1]


class Module(BaseObject):
    def __init__(self, name: str) -> None:
        super().__init__('types.ModuleType')
        self.name = name
        self.is_imported = False

    def _import(self):
        self.data = takein_module(self.name)
        self.is_loaded = True

    def __getitem__(self, item: str) -> TypeObject | BaseObject:
        if not self.is_imported:
            self._import()

        # consider `__init__.pyi` too.
        return super().__getitem__(item)

modules: [str, Module] = {}
ts_base_path = Path(inspect.getfile(typeshed_client)).parent / 'typeshed'


def is_mod(name: str) -> bool:
    """
    :param name:
    :return: True if module. False if object inside module
    """
    names = name.split('.')
    path = ts_base_path
    for name in names:
        path /= name
        # assumes all directories have `__init__.py`
        if not (os.path.exists(path) or os.path.exists(path.with_suffix('.pyi'))):
            return False
    return True


def takein_module(module_nm: str) -> dict:
    print(2, module_nm, modules)
    st = typeshed_client.parser.get_stub_names(module_nm)
    result = {}

    # why deepcopy? a shallow copy could work, but might as well make it deep tbh.
    defaults = {'types.FunctionType': TypeObject('types.FunctionType', set()),
                'types.ModuleType': TypeObject('types.ModuleType', set())}
    _aliases: dict[str, TypeObject | Module] = defaults | {}  # sure, they could do `collections.Counter = list` later on, but we assume the
    # stubs are in good faith.
    # this is
    # necessary because they cause circular imports otherwise :sadgecry:

    def get(x):
        if x in result:
            return result[x]
        elif x in _aliases:
            a = _aliases[x]
            if is_mod(nm:='.'.join(a)):
                modules[nm] = Module(nm)
                return modules[nm]
            else:
                modules[a[0]] = Module(a[0])
                return modules[a[0]][a[1]]

    def helper(c: ast.AST) -> TypeObject:
        if isinstance(c, typed_ast._ast3.Name):
            return helper(c.id)
        elif isinstance(c, typed_ast._ast3.Subscript):
            print(7, a:=helper(c.value.id))
            return a[helper(c.slice.value)]
        elif isinstance(c, typed_ast._ast3.Tuple):
            return tuple(helper(elt) for elt in c.elts)
        elif isinstance(c, typed_ast._ast3.BinOp):
            return helper(c.left) | helper(c.right)
        elif isinstance(c, typed_ast._ast3.Num):
            return c.n
        elif isinstance(c, str):
            return get(c)
        elif isinstance(c, tuple):
            return get(c)
        print(c)

    # no need to handle nested classes and functions. should only handle top-level classes, top-level functions, and functions inside classes. anything else
    # is just smelly.

    for identifier, data in st.items():
        print(1, identifier, data)
        if isinstance(data.ast, ImportedName):
            # note that `a = email; from a import charset` is illegal. thus, the following way is totes valid.
            mod_nm = '.'.join(data.ast.module_name)
            if mod_nm in modules:  # cache
                pass
                # module = modules[mod_nm]
            else:
                modules[mod_nm] = Module(mod_nm)
            # not storing in `result` bc of circular imports. also, importing an imported variable is just a code smell. if this later causes an issue,
            # it'd be better to just write my own typeshed at that point. continue the `studs` project. ('studs' from 'stubs' but more pleasant to look at and
            # handle)
            if data.ast.name is None:
                _aliases[data.ast.module_name[0]] = (mod_nm, '')
            else:
                if is_mod(new_nm := f'{mod_nm}.{data.ast.name}'):
                    _aliases[data.ast.name] = (new_nm, '')
                else:
                    _aliases[data.ast.name] = (mod_nm, data.ast.name)

        elif isinstance(data.ast, typed_ast._ast3.Assign):
            # print(type(data.ast.value), data.ast.value.__dict__)

            if isinstance(data.ast.value, typed_ast._ast3.Subscript):
                val = helper(data.ast.value)
                for target in data.ast.targets:
                    result[target] = val
                print(data.ast.__dict__)
            elif isinstance(data.ast.value, typed_ast._ast3.Call):
                if data.ast.value.func.id == 'TypeVar':
                    for target in data.ast.targets:
                        _aliases[target.id] = TypeV(data.ast.value.args[0].s)
                else:
                    print(3, data.ast.targets[0].id)
                    raise Exception(f"Expected `TypeVar`, but got another function ({data.ast.value.func.id}) call in an assignment.")
            elif isinstance(data.ast.value, typed_ast._ast3.Name):
                pass
            # for target in data.ast.targets:
            #     _aliases[target] = val
        # print(3, data.ast.value.func.__dict__)
        # exit(19)

    # print(f"{imported_aliases=}")


# takein_module('email.charset')
takein_module('builtins')


class Scope:
    def __init__(self, meat: Optional[AST] = None, parent_scope: Optional['Scope'] = None, is_comp_gen: bool = False) -> None:
        if meat is None and parent_scope is None:
            self.locals = set()
            self.nonlocals = set()
            self.globals = self.nonlocals = set()  # same identically, but doesn't matter.
            self.parent_scope = None
            self.state = {}

            self._import(None)
        elif meat is not None and parent_scope is not None:
            self.parent_scope = parent_scope
            self.globals = set()  # global declaration doesn't affect child scopes.
            self.nonlocals = set()  # ^ ditto
            self.locals = set()
            AssignSniffer(self.locals, is_comp_gen=is_comp_gen).visit(meat)
            GlobalAndNonlocalSniffer(self.globals, self.nonlocals).visit(meat)

            self.state = {}

        else:
            raise Exception(f"Noneness isn't all false or all true. {meat=} and {parent_scope=}")

        # todo: globals(), locals()? <- relative (self.globals, self.nonlocals, self.locals) and absolutes (global_scope.state, self.state).
        """
        >>> def a():
            a=1
            def g():
                nonlocal a
                print(locals())
            g()
        
        >>> a()
        {'a': 1}
        """

    def load(self, identifier: str) -> type | BaseObject:
        if identifier in self.locals:
            val = self.state[identifier]
            if isinstance(val, type):
                return val
            elif isinstance(val, BaseObject):
                return val['typ']  # consider changing to `return val`. maybe handle `a.b` elsewhere?
        elif identifier in self.nonlocals:
            return self.parent_scope.load(identifier)
        elif identifier in self.globals:
            a, b = self, self.parent_scope
            while b.parent_scope is not None:
                a, b = b, b.parent_scope
            return a.load(identifier)
        elif identifier in self.globals:
            a, b = self, self.parent_scope
            while b is not None:
                a, b = b, b.parent_scope
            return a.load(identifier)
        else:
            a = self
            raise Exception(f"identifier `{identifier}` was not binded. \n" + '\n\t'.join(
                map(str,
                    ((a, a := a.parent_scope)[0] for _ in iter(lambda: a is None, True))
                    )
            )
                            )

    def store(self, identifier: str, value: type | BaseObject) -> None:
        # can store to __builtins__.__dict__, but that's better handled outside
        if identifier in self.globals:
            a, b = self, self.parent_scope
            while b.parent_scope is not None:
                a, b = b, b.parent_scope
            return a.store(identifier, value)
        elif identifier in self.nonlocals:
            self.parent_scope.store(identifier, value)
        elif identifier in self.locals:
            self.state[identifier] = value

    def delete(self, identifier: str) -> None:
        # can delete identifier in  __builtins__.__dict__, but that's better handled outside
        if identifier in self.globals:
            a, b = self, self.parent_scope
            while b.parent_scope is not None:
                a, b = b, b.parent_scope
            return a.delete(identifier)
        elif identifier in self.nonlocals:
            self.parent_scope.delete(identifier)
        elif identifier in self.locals:
            if identifier in self.state:
                del self.state[identifier]
            else:
                raise Exception(f"identifier {identifier} ain't in state {self.state}. Trying to delete an unbound variable??")

    def _import(self, module_name: Optional[str]) -> None:
        if module_name is not None:
            self.locals.add(module_name)
            mod = typeshed_client.parser.get_stub_names(module_name)
            if mod is None:
                raise ErrorDuringImport(f"Can't find {module_name}")
            self.store(module_name, mod)
        else:
            st = typeshed_client.parser.get_stub_names('builtins')
            for identifier, data in st.items():
                if isinstance(data.ast, ImportedName):
                    mod_nm, nm = data.ast.module_name, data.ast.name
                    print(mod_nm, nm)
                elif isinstance(data.ast, typed_ast._ast3.Assign):
                    print(data.ast.__dict__)


    def _from_import(self, _from: str, module_name: str) -> None:
        self.locals.add(module_name)

        name = '.'.join((_from, module_name))
        mod = typeshed_client.parser.get_stub_names(name)
        if mod is None:
            raise ErrorDuringImport(f"Can't find {name}")
        self.store(module_name, mod)

    # def get_full_name(self, identifier):
    #     # probably won't need this bc referencing

# b = Scope()
