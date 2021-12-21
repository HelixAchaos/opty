import typeshed_client

from shared_state import modules, global_state



def get_dependencies(module_name: str) -> set[str]:
    """
    :param module_name: string that is the module name
    :return: the immediate dependencies. any lazy imports are to be handled later.
    """

    # discontinued bc I can just do `if module_name_aint_assigned_to_somethingelse: just use module_name_stub


def stub_from_import(_from: str, _import: str) -> dict:
    # consider import side-effects later
    """
    import email
    email.charset = 3
    from email import encoders
    email.charset == module
    """
    return typeshed_client.parser.get_stub_names(f"{_from}.{_import}")


def stub_import(_import: str) -> dict:
    return typeshed_client.parser.get_stub_names(_import)

