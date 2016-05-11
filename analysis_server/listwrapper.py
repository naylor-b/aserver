
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

        if lst:
            types = set()
            for l in lst:
                types.add(type(l))

            allowed = set((float, int, str))

            for t in types:
                if t not in allowed:
                    raise TypeError('%s.%s: unsupported List element type %r'
                                     % (sysproxy.get_pathname(), name, t))
        else:
            raise TypeError('%s.%s: undefined List element type'
                            % (sysproxy.get_pathname(), name))

        super(ListWrapper, self).__init__(sysproxy, name, ext_path, cfg,
                                          typ, is_array=False)

_register(list, ListWrapper)
