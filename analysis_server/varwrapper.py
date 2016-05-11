"""
Variable wrappers are created on demand when a wrapped component's variable
is referenced.
"""

from xml.sax.saxutils import escape, quoteattr

# Mapping from OpenMDAO variable type to wrapper type.
_TYPE_MAP = {}

def _register(typ, wrapper):
    """
    Register `wrapper` for `typ`.

    typ: Python type
        Type to be registered.

    wrapper: Python type
        Wrapper class to associate with `typ`.
    """
    typename = '%s' % typ.__name__
    _TYPE_MAP[typename] = wrapper

def _find_var_wrapper(val):
    """
    Return wrapper for the type of the given value.

    val: object
        Python value to be checked.
    """
    typ = type(val)
    for klass in typ.mro():
        name = klass.__name__
        if name in _TYPE_MAP:
            return _TYPE_MAP[name]
    return None

def _float2str(val):
    """
    Return accurate string value for float.

    val: float
        Value to format.
    """
    return '%.16g' % val


class VarWrapper(object):
    """
    Base class for variable wrappers.

    sysproxy: proxy
        Proxy to remote parent System.

    name: string
        Name of variable.

    ext_path: string
        External reference to variable.

    """

    def __init__(self, sysproxy, name, ext_path, cfg):
        self._sysproxy = sysproxy
        self._name = name
        self._ext_path = ext_path
        self._ext_name = ext_path.rpartition('.')[2]
        self._access = 'sg' if name in cfg.inputs else 'g'
        self._io = 'input' if name in cfg.inputs  else 'output'
        self._meta = sysproxy.get_metadata(name)

    @property
    def phx_access(self):
        """ AnalysisServer access string. """
        return self._access

    def get(self, attr, path):
        """
        Return attribute corresponding to `attr`.

        attr: string
            Name of property.

        path: string
            External reference to property.
        """
        if attr == 'description':
            valstr = self._sysproxy.get_description(attr)
            return valstr.encode('string_escape')
        elif attr == 'hasUpperBound' and self.typ != str:
            return 'true' if 'upper' in self._meta else 'false'
        elif attr == 'upperBound' and self.typ != str:
            return str(self._meta.get('upper', 0))
        elif attr == 'hasLowerBound' and self.typ != str:
            return 'true' if 'lower' in self._meta else 'false'
        elif attr == 'lowerBound' and self.typ != str:
            return str(self._meta.get('lower', 0))
        elif attr == 'units':
            return self._meta.get('units', '')
        elif attr == 'format':
            return 'null'
        elif attr == 'enumAliases':
            return ''
        elif attr == 'enumValues':
            return ''
        else:
            raise RuntimeError('no such property <%s>.' % path)

    def _xml_desc(self):
        return quoteattr(self.get('description', self._ext_path))
