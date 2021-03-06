
from analysis_server.varwrapper import VarWrapper, _register

class IntWrapper(VarWrapper):
    """
    Wrapper for `Int` providing ``PHXLong`` interface.
    """

    @property
    def phx_type(self):
        """ AnalysisServer type string for value. """
        return 'com.phoenix_int.aserver.types.PHXLong'

    def get(self, attr, path):
        """
        Return attribute corresponding to `attr`.

        attr: string
            Name of property.

        path: string
            External reference to property.
        """
        if attr == self._name or attr == 'value' or attr == 'valueStr':
            return str(self._sysproxy.get(self._name))
        else:
            return super(IntWrapper, self).get(attr, path)

    def get_as_xml(self, gzipped):
        """
        Return info in XML form.

        gzipped: bool
            If True, file data is gzipped and then base64 encoded.
        """
        return '<Variable name="%s" type="long" io="%s" format=""' \
               ' description=%s>%s</Variable>' \
               % (self._ext_name, self._io, self._xml_desc(),
                  self.get('value', self._ext_path))

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
        valstr = valstr.strip('"')
        if attr == self._name or attr == 'value':
            self._sysproxy.set(self._name, int(valstr))
        elif attr in ('valueStr', 'description', 'enumAliases', 'enumValues'
                      'hasLowerBound', 'lowerBound',
                      'hasUpperBound', 'upperBound', 'units'):
            raise RuntimeError('cannot set <%s>.' % path)
        else:
            raise RuntimeError('no such property <%s>.' % path)

    def list_properties(self):
        """ Return lines listing properties. """
        return ('description (type=java.lang.String) (access=g)',
                'enumAliases (type=java.lang.String[0]) (access=g)',
                'enumValues (type=long[0]) (access=g)',
                'hasLowerBound (type=boolean) (access=g)',
                'hasUpperBound (type=boolean) (access=g)',
                'lowerBound (type=long) (access=g)',
                'units (type=java.lang.String) (access=g)',
                'upperBound (type=long) (access=g)',
                'value (type=long) (access=%s)' % self._access,
                'valueStr (type=java.lang.String) (access=g)')

_register(int, IntWrapper)
