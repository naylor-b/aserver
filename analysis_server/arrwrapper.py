
import logging
import numpy
from analysis_server.varwrapper import VarWrapper, _register

def array2str(value, fmt='%.16g'):
    """
    Return a string representation of the given numpy array.

    Args
    ----

    fmt: str
        Format string for entries. Default of '%.16g' assumes float
        entries.
    """
    return 'bounds[%s] {%s}' % (
             ', '.join(['%d' % dim for dim in value.shape]),
             ', '.join([fmt % val for val in value.flat]))

def str2array(s, dtype=float):
    """
    Args
    ----
    s : str
        A a string of the form 'bounds[2,3] {1.0,2.0,3.0,4.0,5.0,6.0}'.

    Returns
    -------
    A numpy array.

    """
    shape = tuple(int(v) for v in s.split(']', 1)[0].split('[',1)[1].split(','))
    vals = [dtype(v) for v in s.split('{',1)[1].split('}',1)[0].split(',')]
    logging.info("shape: %s" % str(shape))
    logging.info("vals: %s" % vals)
    return numpy.array(vals, dtype=dtype).reshape(shape)

class ArrayBase(VarWrapper):
    """
    Base for wrappers providing double[], long[], or String[] interface.

    sysproxy: proxy
        Proxy to remote parent System.

    name: string
        Name of variable.

    ext_path: string
        External reference to variable.

    logger: :class:`logging.Logger`
        Used for progress, errors, etc.

    typ: Python type
        Element type.

    is_array: bool
        If True, numpy ndarray, else List.
    """

    def __init__(self, sysproxy, name, ext_path, cfg, typ, is_array):
        super(ArrayBase, self).__init__(sysproxy, name, ext_path, cfg)
        self.typ = typ
        if typ is float:
            self._typstr = 'double'
        elif typ is int:
            self._typstr = 'long'
        elif typ is str:
            self._typstr = 'string'
        self._is_array = is_array

    @property
    def phx_type(self):
        """ AnalysisServer type string for value. """
        value = self._sysproxy.get(self._name)
        if self._is_array:
            dims = '[%s]' % ']['.join(['%d' % dim for dim in value.shape])
            if self.typ == float:
                return 'double%s' % dims
            elif self.typ == int:
                return 'long%s' % dims
            else:
                return 'java.lang.String%s' % dims
        else:
            if self.typ == float:
                return 'double[%d]' % len(value)
            elif self.typ == int:
                return 'long[%d]' % len(value)
            else:
                return 'java.lang.String[%d]' % len(value)

    def get(self, attr, path):
        """
        Return attribute corresponding to `attr`.

        attr: string
            Name of property.

        path: string
            External reference to property.
        """
        if attr == self._name or attr == 'value':
            value = self._sysproxy.get(self._name)
            if self.typ == float:
                fmt = '%.16g'
            elif self.typ == int:
                fmt = '%d'
            else:
                fmt = '"%s"'
            if self._is_array and len(value.shape) > 1:
                valstr = 'bounds[%s] {%s}' % (
                         ', '.join(['%d' % dim for dim in value.shape]),
                         ', '.join([fmt % val for val in value.flat]))
            else:
                valstr = ', '.join([fmt % val for val in value])
            if self.typ == str:
                valstr = valstr.encode('string_escape')
            return valstr
        elif attr == 'componentType':
            return self._typstr
        elif attr == 'dimensions':
            value = self._sysproxy.get(self._name)
            if self._is_array:
                return ', '.join(['"%d"' % dim for dim in value.shape])
            else:
                return '"%d"' % len(value)
        elif attr in ('enumAliases', 'enumValues'):
            return ''
        elif attr == 'first':
            value = self._sysproxy.get(self._name)
            if len(value):
                if self._is_array and len(value.shape) > 1:
                    first = '%s' % value.flat[0]
                else:
                    first = '%s' % value[0]
                if self.typ == str:
                    first = first.encode('string_escape')
            else:
                first = ''
            return first
        elif attr == 'length':
            value = self._sysproxy.get(self._name)
            if self._is_array:
                return '%d' % value.shape[0]
            else:
                return '%d' % len(value)
        elif attr == 'lockResize':
            return 'true' if self._is_array else 'false'
        elif attr == 'numDimensions':
            if self._is_array:
                value = self._sysproxy.get(self._name)
                return '%d' % len(value.shape)
            else:
                return '1'
        else:
            return super(ArrayBase, self).get(attr, path)

    def get_as_xml(self, gzipped):
        """
        Return info in XML form.

        gzipped: bool
            If True, file data is gzipped and then base64 encoded.
        """
        return '<Variable name="%s" type="%s[]" io="%s" format=""' \
               ' description=%s units="%s">%s</Variable>' \
               % (self._ext_path, self._typstr, self._io, self._xml_desc(),
                  self.get('units', self._ext_path),
                  self.escape(self.get('value', self._ext_path)))

    def set(self, attr, path, valstr, gzipped):
        """
        Set attribute corresponding to `attr` to `valstr`.

        attr: string
            Name of property.

        path: string
            External reference to property.

        valstr: string
            Value to be set, in string form.

        gzipped: bool
            If True, file data is gzipped and then base64 encoded.
        """
        if attr == self._name or attr == 'value':
            if self.typ == str:
                valstr = valstr.decode('string_escape')
            if self._is_array:
                if valstr.startswith('bounds['):
                    dims, _, rest = valstr[7:].partition(']')
                    dims = [int(val.strip(' "')) for val in dims.split(',')]
                    junk, _, rest = rest.partition('{')
                    data, _, rest = rest.partition('}')
                    value = numpy.array([self.typ(val.strip(' "'))
                                         for val in data.split(',')]).reshape(dims)
                else:
                    value = numpy.array([self.typ(val.strip(' "'))
                                         for val in valstr.split(',')])
            else:
                if valstr:
                    value = [self.typ(val.strip(' "'))
                             for val in valstr.split(',')]
                else:
                    value = []
            self._sysproxy.set(self._name, value)
        elif attr in ('componentType', 'description', 'dimensions',
                      'enumAliases', 'enumValues', 'first', 'format',
                      'hasLowerBound', 'lowerBound',
                      'hasUpperBound', 'upperBound',
                      'length', 'lockResize', 'numDimensions', 'units'):
            raise RuntimeError('cannot set <%s>.' % path)
        else:
            raise RuntimeError('no such property <%s>.' % path)

    def list_properties(self):
        """ Return lines listing properties. """
        if self.typ == float:
            typstr = 'double'
        elif self.typ == int:
            typstr = 'long'
        else:
            typstr = 'java.lang.String'

        lines = ['componentType (type=java.lang.Class) (access=g)',
                 'description (type=java.lang.String) (access=g)',
                 'dimensions (type=int[1]) (access=g)',
                 'enumAliases (type=java.lang.String[0]) (access=g)',
                 'enumValues (type=%s[0]) (access=g)' % typstr,
                 'first (type=java.lang.Object) (access=g)',
                 'length (type=int) (access=g)',
                 'lockResize (type=boolean) (access=g)',
                 'numDimensions (type=int) (access=g)',
                 'units (type=java.lang.String) (access=g)']

        if self.typ != str:
            lines.extend(['format (type=java.lang.String) (access=g)',
                          'hasLowerBound (type=boolean) (access=g)',
                          'hasUpperBound (type=boolean) (access=g)',
                          'lowerBound (type=%s) (access=g)' % typstr,
                          'upperBound (type=%s) (access=g)' % typstr])

        return sorted(lines)


class ArrayWrapper(ArrayBase):
    """
    Wrapper for `Array` providing double[], long[], or String[] interface.

    sysproxy: proxy
        Proxy to remote parent System.

    name: string
        Name of variable.

    ext_path: string
        External reference to variable.

    logger: :class:`logging.Logger`
        Used for progress, errors, etc.
    """

    # Map from numpy dtype.kind to scalar converter.
    _converters = {'f':float, 'i':int, 'S':str}

    def __init__(self, sysproxy, name, ext_path, cfg):
        value = sysproxy.get(name)
        kind = value.dtype.kind
        try:
            typ = self._converters[kind]
        except KeyError:
            raise RuntimeError('Unsupported dtype for %s.%s: %r (%r)'
                               % (sysproxy.get_pathname(), name,
                                  value.dtype, kind))

        super(ArrayWrapper, self).__init__(sysproxy, name, ext_path, cfg,
                                           typ, is_array=True)

_register(numpy.ndarray, ArrayWrapper)
