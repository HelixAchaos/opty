import typeshed_client


from models import Scope

# class State:
#     def __init__(self, st: dict):
#         self._state = st
#
#     def __getitem__(self, item):
#         c = self._state
#         for nm in item.split('.'):
#             c = c[nm]
#         return c
#
#     def __setitem__(self, key, value):
#         c = self._state
#         for nm in key.split('.'):
#             c = c[nm]
#         c = value
#
#     def __or__(self, other):
#         if isinstance(other, dict):
#             return self._state | other
#         elif isinstance(other, State):
#             return self._state | other._state
#         else:
#             raise Exception(f"Invalid type {type(other)}")
#
#     def __ior__(self, other):
#         self._state = self | other



# global_state = State(typeshed_client.parser.get_stub_names('builtins'))
builtin = Scope()

# print(global_state['str'])
