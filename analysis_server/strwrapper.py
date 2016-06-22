
from analysis_server.varwrapper import VarWrapper, _register

class StrWrapper(VarWrapper):
    """
    Wrapper for `Str` providing ``PHXString`` interface.

    """

    @property
    def phx_type(self):
        """ AnalysisServer type string for value. """
        return 'com.phoenix_int.aserver.types.PHXString'

    def get(self, attr, path):
        """
        Return attribute corresponding to `attr`.

        attr: string
            Name of property.

        path: string
            External reference to property.
        """
        if attr == self._name or attr == 'value' or attr == 'valueStr':
            return self._sysproxy.get(self._name).encode('string_escape')
        elif attr == 'enumValues':
            return ''
        elif attr == 'enumAliases':
            return ''
        else:
            return super(StrWrapper, self).get(attr, path)

    def get_as_xml(self, gzipped):
        """
        Return info in XML form.

        gzipped: bool
            If True, file data is gzipped and then base64 encoded.
        """
        return '<Variable name="%s" type="string" io="%s" format=""' \
               ' description=%s>%s</Variable>' \
               % (self._ext_path, self._io, self._xml_desc(),
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
            self._sysproxy.set(self._name,
                                valstr.decode('string_escape').strip('"'))
        elif attr in ('valueStr', 'description', 'enumAliases', 'enumValues'):
            raise RuntimeError('cannot set <%s>.' % path)
        else:
            raise RuntimeError('no such property <%s>.' % path)

    def list_properties(self):
        """ Return lines listing properties. """
        return ('description (type=java.lang.String) (access=g)',
                'enumAliases (type=java.lang.String[0]) (access=g)',
                'enumValues (type=java.lang.String[0]) (access=g)',
                'value (type=java.lang.String) (access=%s)' % self._access,
                'valueStr (type=java.lang.String) (access=g)')

_register(str, StrWrapper)
