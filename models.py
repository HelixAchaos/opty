# Like a Linked List Stack.
from collections import deque
from typing import Optional, Any
from ast import Assign, AnnAssign, AugAssign, NamedExpr, NodeVisitor, AST, parse, Name, Tuple, Starred, ClassDef, FunctionDef, AsyncFunctionDef, DictComp, \
    ListComp, SetComp, Global, Nonlocal, comprehension, GeneratorExp, List

import typeshed_client


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


class Scope:
    def __init__(self, meat: Optional[AST] = None, parent_scope: Optional['Scope'] = None, is_comp_gen: bool = False) -> None:
        if meat is None and parent_scope is None:
            self.state = typeshed_client.parser.get_stub_names('builtins')
            self.locals = set(self.state.keys())
            self.globals = self.nonlocals = set()  # same identically, but doesn't matter.
            self.parent_scope = None
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

    def load(self, identifier):
        if identifier in self.locals:
            return self.state[identifier]
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
                map(str, (
                    (a, a := a.parent_scope)[0] for _ in iter(lambda: a is None, True))
                    )
            )
                            )

    def store(self, identifier, value):
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

    def delete(self, identifier):
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

    def _import(self, module_name: str):
        self.locals.add(module_name)

        self.store(module_name, typeshed_client.parser.get_stub_names(module_name))

    def _from_import(self, _from: str, module_name: str):
        self.locals.add(module_name)

        name = '.'.join((_from, module_name))
        self.store(module_name, typeshed_client.parser.get_stub_names(name))

    def get_full_name(self, identifier):

