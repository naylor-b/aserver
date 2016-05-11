
from analysis_server.varwrapper import VarWrapper, _register, _float2str

class FloatWrapper(VarWrapper):
    """
    Wrapper for `Float` providing ``PHXDouble`` interface.
    """

    @property
    def phx_type(self):
        """ AnalysisServer type string for value. """
        return 'com.phoenix_int.aserver.types.PHXDouble'

    def get(self, attr, path):
        """
        Return attribute corresponding to `attr`.

        attr: string
            Name of property.

        path: string
            External reference to property.
        """
        if attr == 'value' or attr == 'valueStr':
            return _float2str(self._sysproxy.get(self._name))
        else:
            return super(FloatWrapper, self).get(attr, path)

    def get_as_xml(self, gzipped):
        """
        Return info in XML form.

        gzipped: bool
            If True, file data is gzipped and then base64 encoded.
        """
        return '<Variable name="%s" type="double" io="%s" format=""' \
               ' description=%s units="%s">%s</Variable>' \
               % (self._ext_name, self._io, self._xml_desc(),
                  self.get('units', self._ext_path),
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
        if attr == 'value':
            self._sysproxy.set(self._name, float(valstr))
        elif attr in ('valueStr', 'description', 'enumAliases', 'enumValues'
                      'format', 'hasLowerBound', 'lowerBound',
                      'hasUpperBound', 'upperBound', 'units'):
            raise RuntimeError('cannot set <%s>.' % path)
        else:
            raise RuntimeError('no such property <%s>.' % path)

    def list_properties(self):
        """ Return lines listing properties. """
        return ('description (type=java.lang.String) (access=g)',
                'enumAliases (type=java.lang.String[0]) (access=g)',
                'enumValues (type=double[0]) (access=g)',
                'format (type=java.lang.String) (access=g)',
                'hasLowerBound (type=boolean) (access=g)',
                'hasUpperBound (type=boolean) (access=g)',
                'lowerBound (type=double) (access=g)',
                'units (type=java.lang.String) (access=g)',
                'upperBound (type=double) (access=g)',
                'value (type=double) (access=%s)' % self._access,
                'valueStr (type=java.lang.String) (access=g)')

_register(float, FloatWrapper)
