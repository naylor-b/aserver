
from analysis_server.varwrapper import VarWrapper, _register
from analysis_server.arrwrapper import ArrayBase


class ListWrapper(ArrayBase):
    """
    Wrapper for `List` providing double[], long[], or String[] interface.

    sysproxy: proxy
        Proxy to remote parent System.

    name: string
        Name of variable.

    ext_path: string
        External reference to variable.

    logger: :class:`logging.Logger`
        Used for progress, errors, etc.
    """

    def __init__(self, sysproxy, name, ext_path, cfg):
        lst = sysproxy.get(name)

        if lst is not None:
            types = set()
            for l in lst:
                types.add(type(l))

            if len(types) > 1:
                raise TypeError('%s.%s: only one List element type is allowed. '
                                'This list has types: %s'
                                 % (sysproxy.get_pathname(), name, list(types)))

            try:
                typ = types.pop()
            except KeyError:
                meta = sysproxy.get_metadata(name)
                if 'element_type' in meta:
                    typ = meta['element_type']
                else:
                    raise TypeError("%s.%s: list is empty. For empty lists, you "
                                    "must store 'element_type' in the list's "
                                    "metadata."
                                     % (sysproxy.get_pathname(), name))

            if typ not in (float, int, str):
                raise TypeError('%s.%s: unsupported List element type %s'
                                 % (sysproxy.get_pathname(), name, typ))
        else:
            raise TypeError('%s.%s: undefined List element type'
                            % (sysproxy.get_pathname(), name))

        super(ListWrapper, self).__init__(sysproxy, name, ext_path, cfg,
                                          typ, is_array=False)

_register(list, ListWrapper)
