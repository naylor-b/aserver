
from analysis_server.varwrapper import VarWrapper, _register

#
# class ObjWrapper(VarWrapper):
#     """
#     Wrapper for a general object providing ``PHXScriptObject`` interface.
#
#     container: proxy
#         Proxy to remote parent container.
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
#     def __init__(self, container, name, ext_path, cfg):
#         super(ObjWrapper, self).__init__(container, name, ext_path, cfg)
#         obj = container.get(name)
#         self._cls = type(obj)
#         self._iotype = obj.iotype
#         self._access = 'sg' if obj.iotype == 'in' else 'g'
#         self._io = 'input' if obj.iotype == 'in' else 'output'
#
#     @property
#     def phx_type(self):
#         """ AnalysisServer type string for value. """
#         return 'com.phoenix_int.aserver.types.PHXScriptObject'
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
#         if attr == 'value':
#             obj = self._sysproxy.get(self._name)
#             xml = get_as_xml(obj)
#             return xml
#         elif attr == 'classURL':
#             path = sys.modules[self._cls.__module__].__file__
#             if path.endswith(('.pyc', '.pyo')):
#                 path = path[:-1]
#             path = os.path.abspath(path)
#             return '%s#%s' % (path, self._cls.__name__)
#         else:
#             return super(ObjWrapper, self).get(attr, path)
#
#     def get_as_xml(self, gzipped):
#         """
#         Return info in XML form.
#
#         gzipped: bool
#             If True, file data is gzipped and then base64 encoded.
#         """
#         return '<Variable name="%s" type="object" io="%s"' \
#                ' description=%s>%s</Variable>' \
#                % (self._ext_name, self._io, self._xml_desc(),
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
#         if attr == 'value':
#             obj = self._cls(iotype=self._iotype)
#             set_from_xml(obj, valstr.decode('string_escape'))
#             self._sysproxy.set(self._name, obj)
#         elif attr in ('classURL', 'description'):
#             raise RuntimeError('cannot set <%s>.' % path)
#         else:
#             raise RuntimeError('no such property <%s>.' % path)
#
#     def list_properties(self):
#         """ Return lines listing properties. """
#         return ('classURL (type=java.lang.String) (access=g)',
#                 'description (type=java.lang.String) (access=g)')
#
# _register(Container, ObjWrapper)
# _register(VarTree, ObjWrapper)
