

from analysis_server.varwrapper import VarWrapper, _register


class BoolWrapper(VarWrapper):
    """
    Wrapper for `Bool` providing ``PHXBoolean`` interface.

    """

    @property
    def phx_type(self):
        """ AnalysisServer type string for value. """
        return 'com.phoenix_int.aserver.types.PHXBoolean'

    def get(self, attr, path):
        """
        Return attribute corresponding to `attr`.

        attr: string
            Name of property.

        path: string
            External reference to property.
        """
        if attr == self._name or attr == 'value' or attr == 'valueStr':
            return 'true' if self._sysproxy.get(self._name) else 'false'
        else:
            return super(BoolWrapper, self).get(attr, path)

    def get_as_xml(self, gzipped):
        """
        Return info in XML form.

        gzipped: bool
            If True, file data is gzipped and then base64 encoded.
        """
        return '<Variable name="%s" type="boolean" io="%s" format=""' \
               ' description=%s>%s</Variable>' \
               % (self._ext_path, self._io, self._xml_desc(),
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
            if valstr == 'true':
                self._sysproxy.set(self._name, True)
            elif valstr == 'false':
                self._sysproxy.set(self._name, False)
            else:
                raise RuntimeError('invalid boolean value %r for <%s>'
                                   % (valstr, path))
        elif attr in ('valueStr', 'description'):
            raise RuntimeError('cannot set <%s>.' % path)
        else:
            raise RuntimeError('no such property <%s>.' % path)

    def list_properties(self):
        """ Return lines listing properties. """
        return ('description (type=java.lang.String) (access=g)',
                'value (type=boolean) (access=%s)' % self._access,
                'valueStr (type=boolean) (access=g)')

_register(bool, BoolWrapper)
