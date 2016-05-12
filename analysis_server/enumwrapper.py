

from analysis_server.varwrapper import VarWrapper, _register, _float2str

# class EnumWrapper(VarWrapper):
#     """
#     Wrapper for `Enum` providing ``PHXDouble``, ``PHXLong``, or ``PHXString``
#     interface.
#
#     sysproxy: proxy
#         Proxy to remote parent System.
#
#     name: string
#         Name of variable.
#
#     ext_path: string
#         External reference to variable.
#
#     logger: :class:`logging.Logger`
#         Used for progress, errors, etc.
#     """
#
#     def __init__(self, sysproxy, name, ext_path, cfg):
#         super(EnumWrapper, self).__init__(sysproxy, name, ext_path, cfg)
#         typ = type(self._trait.values[0])
#         for val in self._trait.values:
#             if type(val) != typ:
#                 raise RuntimeError('inconsistent value types for %s.%s'
#                                    % (sysproxy.get_pathname(), name))
#         if typ not in (float, int, str):
#             raise RuntimeError('unexpected value type for %s.%s: %r'
#                                % (sysproxy.get_pathname(), name, typ))
#         self._py_type = typ
#         if typ is float:
#             self._phx_type = 'com.phoenix_int.aserver.types.PHXDouble'
#             self._val_type = 'double'
#         elif typ is int:
#             self._phx_type = 'com.phoenix_int.aserver.types.PHXLong'
#             self._val_type = 'long'
#         else:
#             self._phx_type = 'com.phoenix_int.aserver.types.PHXString'
#             self._val_type = 'java.lang.String'
#
#     @property
#     def phx_type(self):
#         """ AnalysisServer type string for value. """
#         return self._phx_type
#
#     def get(self, attr, path):
#         """
#         Return attribute corresponding to `attr`.
#
#         attr: string
#             Name of property.
#
#         path: string
#             External reference to property.
#         """
#         if attr == 'value' or attr == 'valueStr':
#             if self._py_type == float:
#                 return _float2str(self._sysproxy.get(self._name))
#             else:
#                 return str(self._sysproxy.get(self._name))
#         elif attr == 'enumAliases':
#             if self._trait.aliases:
#                 return ', '.join(['"%s"' % alias
#                                   for alias in self._trait.aliases])
#             else:
#                 return ''
#         elif attr.startswith('enumAliases['):
#             i = int(attr[12:-1])
#             return self._trait.aliases[i]
#         elif attr == 'enumValues':
#             if self._py_type == float:
#                 return ', '.join([_float2str(value)
#                                   for value in self._trait.values])
#             elif self._py_type == int:
#                 return ', '.join(['%s' % value
#                                   for value in self._trait.values])
#             else:
#                 return ', '.join(['"%s"' % value
#                                   for value in self._trait.values])
#         elif attr.startswith('enumValues['):
#             i = int(attr[11:-1])
#             if self._py_type == float:
#                 return _float2str(self._trait.values[i])
#             else:
#                 return str(self._trait.values[i])
#         elif attr == 'format':
#             return 'null'
#         elif attr == 'hasLowerBound':
#             return 'false'
#         elif attr == 'lowerBound':
#             return ''
#         elif attr == 'hasUpperBound':
#             return 'false'
#         elif attr == 'upperBound':
#             return ''
#         elif attr == 'units':
#             if self._py_type == float:
#                 return self._trait.units or ''
#             else:
#                 return ''
#         else:
#             return super(EnumWrapper, self).get(attr, path)
#
#     def get_as_xml(self, gzipped):
#         """
#         Return info in XML form.
#
#         gzipped: bool
#             If True, file data is gzipped and then base64 encoded.
#         """
#         if self._py_type == float:
#             typstr = 'double'
#         elif self._py_type == int:
#             typstr = 'long'
#         else:
#             typstr = 'string'
#         return '<Variable name="%s" type="%s" io="%s" format=""' \
#                ' description=%s units="%s">%s</Variable>' \
#                % (self._ext_name, typstr, self._io, self._xml_desc(),
#                   self.get('units', self._ext_path),
#                   self.escape(self.get('value', self._ext_path)))
#
#     def set(self, attr, path, valstr, gzipped):
#         """
#         Set attribute corresponding to `attr` to `valstr`.
#
#         attr: string
#             Name of property.
#
#         path: string
#             External reference to property.
#
#         valstr: string
#             Value to be set, in string form.
#
#         gzipped: bool
#             If True, file data is gzipped and then base64 encoded.
#         """
#         valstr = valstr.strip('"')
#         if attr == 'value':
#             try:
#                 i = self._trait.aliases.index(valstr)
#             except (AttributeError, ValueError):
#                 self._sysproxy.set(self._name, self._py_type(valstr))
#             else:
#                 self._sysproxy.set(self._name, self._trait.values[i])
#         elif attr in ('valueStr', 'description', 'enumAliases', 'enumValues'
#                       'format', 'hasLowerBound', 'lowerBound', 'hasUpperBound',
#                       'upperBound', 'units'):
#             raise RuntimeError('cannot set <%s>.' % path)
#         else:
#             raise RuntimeError('no such property <%s>.' % path)
#
#     def list_properties(self):
#         """ Return lines listing properties. """
#         n_vals = len(self._trait.values)
#         n_alias = len(self._trait.aliases) if self._trait.aliases else 0
#
#         lines = ['description (type=java.lang.String) (access=g)',
#                  'enumAliases (type=java.lang.String[%d]) (access=g)' % n_alias,
#                  'enumValues (type=%s[%d]) (access=g)' % (self._val_type, n_vals)]
#         if self._py_type == float:
#             lines.append('format (type=java.lang.String) (access=g)')
#         if self._py_type == float or self._py_type == int:
#             lines.extend(['hasLowerBound (type=boolean) (access=g)',
#                           'hasUpperBound (type=boolean) (access=g)',
#                           'lowerBound (type=%s) (access=g)' % self._val_type,
#                           'units (type=java.lang.String) (access=g)',
#                           'upperBound (type=%s) (access=g)' % self._val_type])
#         lines.extend(['value (type=%s) (access=%s)' \
#                       % (self._val_type, self._access),
#                       'valueStr (type=java.lang.String) (access=g)'])
#         return lines
#
# _register(Enum, EnumWrapper)
#
