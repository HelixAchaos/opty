# Like a Linked List Stack.
import ast
import importlib
from collections import deque
from types import FunctionType
from typing import Optional, Any
from ast import Assign, AnnAssign, AugAssign, NamedExpr, NodeVisitor, AST, parse, Name, Tuple, Starred, ClassDef, FunctionDef, AsyncFunctionDef, DictComp, \
    ListComp, SetComp, Global, Nonlocal, comprehension, GeneratorExp, List

from pathlib import Path

import typed_ast
import typeshed_client
import typing
from typeshed_client import NameInfo, ImportedName

from errors import ErrorDuringImport

modules = {}
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

    def generic_visit(self, node: AST) -> Any:
        NodeVisitor.generic_visit(self, node)

    def visit_Assign(self, node: Assign) -> Any:
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

    def visit_AnnAssign(self, node: AnnAssign) -> Any:
        if self.is_comp_gen:
            return None
        self.locals.add(node.target.id)
        self.visit(node.value)

    def visit_AugAssign(self, node: AugAssign) -> Any:
        if self.is_comp_gen:
            return None
        self.locals.add(node.target.id)
        self.visit(node.value)

    def visit_NamedExpr(self, node: NamedExpr) -> Any:
        self.locals.add(node.target.id)
        self.visit(node.value)

    def visit_ClassDef(self, node: ClassDef) -> Any:
        # class, so do nothing
        return None

    def visit_FunctionDef(self, node: FunctionDef) -> Any:
        # func, so do nothing
        return None

    def visit_AsyncFunctionDef(self, node: AsyncFunctionDef) -> Any:
        # func, so do nothing
        return None

    def visit_ListComp(self, node: ListComp) -> Any:
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

    def visit_SetComp(self, node: SetComp) -> Any:
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

    def visit_GeneratorExp(self, node: GeneratorExp) -> Any:
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

    def visit_DictComp(self, node: DictComp) -> Any:
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

    def generic_visit(self, node: AST) -> Any:
        NodeVisitor.generic_visit(self, node)

    def visit_Global(self, node: Global) -> Any:
        self.globals.update(node.names)

    def visit_Nonlocal(self, node: Nonlocal) -> Any:
        self.nonlocals.update(node.names)

    def visit_ClassDef(self, node: ClassDef) -> Any:
        # class, so do nothing
        return None

    def visit_FunctionDef(self, node: FunctionDef) -> Any:
        # func, so do nothing
        return None

    def visit_AsyncFunctionDef(self, node: AsyncFunctionDef) -> Any:
        # func, so do nothing
        return None


NotFound = typing.TypeVar("NotFound")


class TypeObject:
    def __init__(self, name: str, bases: tuple[str]) -> None:
        self.name = name
        self.data = {}
        self.bases: set[str] = set(bases)  # not dict because the bases' definitions may be dependent on self.
        types[self.name] = self

    def __getitem__(self, item: str) -> typing.Union['TypeObject', 'BaseObject', '_Union']:
        return self.data[item]

    def __setitem__(self, key: str, value: typing.Union['TypeObject', 'BaseObject', '_Union']) -> None:
        self.data[key] = value

    def __lt__(self, superclass: typing.Union['TypeObject', '_Union']) -> bool:
        if isinstance(superclass, _Union):
            return any(self < arg for arg in superclass.args)
        elif isinstance(superclass, TypeObject):
            return any(types[base] < superclass for base in self.bases)

    def __eq__(self, other: typing.Union['TypeObject', '_Union']) -> bool:
        if isinstance(other, _Union):
            return False
        return self is other

    def __le__(self, other: typing.Union['TypeObject', '_Union']) -> bool:
        return self == other or self < other

    def __or__(self, other: typing.Union['TypeObject', '_Union']) -> typing.Union['TypeObject', '_Union']:
        if isinstance(other, TypeObject):
            if self == other:
                return self
            else:
                shared_names = self.data.keys() & other.data.keys()
                data = {name: self[name] | other[name] for name in shared_names}
                return _Union(self, other, data=data)
        elif isinstance(other, _Union):
            shared_names = self.data.keys() & other.data.keys()
            data = {name: self[name] | other[name] for name in shared_names}
            return _Union(self, other, data=data)


def onion(args: tuple[TypeObject]) -> typing.Union[TypeObject, '_Union']:
    if len(args) == 1:
        return args[0]
    else:
        return _Union(*args)


class _Union:
    def __init__(self, *args: TypeObject, data: Optional[dict] = None):
        self.args = args

        if data is None:
            names = set.intersection(*(set(arg.data.keys()) for arg in self.args))
            data = {name: [] for name in names}
            for name, ah in self.data.items():
                for arg in self.args:
                    ah.append(arg[name])

            self.data = {name: _Union(*args) for name, args in data.items()}

        else:
            self.data = data


    def __getitem__(self, item: str) -> typing.Union['TypeObject', 'BaseObject', '_Union']:
        return self.data[item]

    def __setitem__(self, key: str, value: typing.Union['TypeObject', 'BaseObject', '_Union']) -> None:
        self.data[key] = value

    def __lt__(self, superclass: typing.Union[TypeObject, '_Union']) -> bool:
        return all(arg < superclass for arg in self.args)
        # if isinstance(superclass, _Union):
        #     return all(arg < superclass for arg in self.args)
        # elif isinstance(superclass, TypeObject):
        #     return all(arg < superclass for arg in self.args)

    def __eq__(self, other: typing.Union[TypeObject, '_Union']) -> bool:
        if isinstance(other, _Union):
            return False
        return self is other

    def __le__(self, other: typing.Union[TypeObject, '_Union']) -> bool:
        return self == other or self < other

    def __or__(self, other: typing.Union[TypeObject, '_Union']) -> '_Union':
        if self == other:
            return self
        if isinstance(other, TypeObject):
            if other in self.args:
                return self
            else:
                shared_names = self.data.keys() & other.data.keys()
                data = {name: self[name] | other[name] for name in shared_names}
                return _Union(*self.args, other, data=data)
        elif isinstance(other, _Union):
            shared_names = self.data.keys() & other.data.keys()
            data = {name: self[name] | other[name] for name in shared_names}
            args = set(self.args) | set(other.args)  # make sure TypeObjects are unique as possible, by design
            return _Union(*args, data=data)


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


class Function(BaseObject):
    def __init__(self, ast: ...):
        super().__init__('types.FunctionType')
        self.overloaded_funcs: list[dict[str, type]] = []
        print(ast)

    def returns(self, args: tuple = None, kwargs: dict = None):
        raise NotImplementedError
        # should handle overloaded functions. search through to see the most specific generics that match args,
        #        then return the return_type


def takein_module(module_nm: str) -> dict:
    st = typeshed_client.parser.get_stub_names(module_nm)

    def helper(node: ast.AST) -> dict:
        ...

    for identifier, data in st.items():
        print(1, identifier, data)
        if identifier in modules:
            st[identifier] = modules[identifier]
        if isinstance(data.ast, ImportedName):
            mod_nm, nm = data.ast.module_name, data.ast.name
            print(mod_nm, nm)
        elif isinstance(data.ast, typed_ast._ast3.Assign):
            print(data.ast.__dict__)
            exit(19)


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
                    exit(19)

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
