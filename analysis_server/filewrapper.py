
import base64
import cStringIO
import gzip
import mimetypes
from multiprocessing.managers import RemoteError

from openmdao.core.fileref import FileRef
from analysis_server.varwrapper import VarWrapper, _register

class FileWrapper(VarWrapper):
    """
    Wrapper for `File` providing ``PHXRawFile`` interface.

    sysproxy: proxy
        Proxy to remote parent System.

    name: string
        Name of variable.

    ext_path: string
        External reference to variable.

    """

    def __init__(self, sysproxy, name, ext_path, cfg):
        super(FileWrapper, self).__init__(sysproxy, name, ext_path, cfg)
        self._proxy = None

    @property
    def binary(self):
        """ True if this file is binary. """
        file_ref = self._sysproxy.get(self._name)
        if file_ref is not None:
            return file_ref.meta.get('binary', False)
        return False

    @property
    def filename(self):
        """ Name of file """
        file_ref = self._sysproxy.get(self._name)
        return file_ref._abspath()
        return name

    @property
    def phx_type(self):
        """ AnalysisServer type string for value. """
        return 'com.phoenix_int.aserver.types.PHXRawFile'

    def set_proxy(self, proxy):
        """
        Set proxy to `proxy` for file operations.

        proxy: proxy
            Proxy to the server hosting this file.
        """
        self._proxy = proxy

    def get(self, attr, path):
        """
        Return attribute corresponding to `attr`.

        attr: string
            Name of property.

        path: string
            External reference to property.
        """
        if attr == 'value':
            file_ref = self._sysproxy.get(self._name)
            if file_ref is None:
                return ''
            try:
                with file_ref.open('r') as inp:
                    data = inp.read()
            except IOError as exc:
                self._logger.warning('get %s.value: %r', path, exc)
                return ''
            except RemoteError as exc:
                if 'IOError' in str(exc):
                    self._logger.warning('get %s.value: %r', path, exc)
                    return ''
                else:
                    raise
            if file_ref.binary:
                return base64.b64encode(data)
            else:
                return data.encode('string_escape')
        elif attr == 'isBinary':
            return 'true' if self.binary else 'false'
        elif attr == 'mimeType':
            file_ref = self._sysproxy.get(self._name)
            if file_ref is None:
                return ''
            typ = mimetypes.guess_type(file_ref.path, strict=False)[0]
            if typ is not None:
                return typ
            elif file_ref.binary:
                return 'application/octet-stream'
            else:
                return 'text/plain'
        elif attr == 'name':
            return self.filename
        elif attr == 'nameCoded':
            return self.filename
        elif attr == 'url':
            return ''
        else:
            return super(FileWrapper, self).get(attr, path)

    def get_as_xml(self, gzipped):
        """
        Return info in XML form.

        gzipped: bool
            If True, file data is gzipped and then base64 encoded.
        """
        file_ref = self._sysproxy.get(self._name)
        filename = self.filename
        data = zipped = ''

        if gzipped:
            file_ref = self._sysproxy.get(self._name)
            if file_ref is not None:
                try:
                    with file_ref.open() as inp:
                        data = inp.read()
                except IOError as exc:
                    self._logger.warning('get %s.value: %r',
                                         self._ext_path, exc)
                except RemoteError as exc:
                    if 'IOError' in str(exc):
                        self._logger.warning('get %s.value: %r',
                                             self._ext_path, exc)
                    else:
                        raise
                else:
                    if not file_ref.binary:
                        gz_data = cStringIO.StringIO()
                        with gzip.GzipFile(mode='wb', fileobj=gz_data) as gz_file:
                            gz_file.write(data)
                        data = gz_data.getvalue()
                        zipped = ' gzipped="true"'
                data = base64.b64encode(data)
                chunks = []
                chunk = data[:76]
                while chunk:
                    chunks.append(chunk)
                    data = data[76:]
                    chunk = data[:76]
                chunks.append('')
                data = '\n'.join(chunks)
        else:
            data = self.escape(self.get('value', self._ext_path))

        return '<Variable name="%s" type="file" io="%s" description=%s' \
               ' isBinary="%s" fileName="%s"%s>%s</Variable>' \
               % (self._ext_name, self._io, self._xml_desc(),
                  self.get('isBinary', self._ext_path),
                  filename, zipped, data)

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
        if attr == 'value':
            if self._io != 'input':
                raise RuntimeError('cannot set output <%s>.' % path)
            file_ref = self._sysproxy.get(self._name)
            filename = file_ref._abspath()

            binary = self.binary
            if gzipped:
                valstr = self._decode(valstr)
                if not binary:
                    valstr = cStringIO.StringIO(valstr)
                    gz_file = gzip.GzipFile(mode='rb', fileobj=valstr)
                    valstr = gz_file.read()
            else:
                if binary:
                    valstr = self._decode(valstr)
                else:
                    valstr = valstr.strip('"').decode('string_escape')
            self._sysproxy.write(self._name, valstr)
        elif attr in ('description', 'isBinary', 'mimeType',
                      'name', 'nameCoded', 'url'):
            raise RuntimeError('cannot set <%s>.' % path)
        else:
            raise RuntimeError('no such property <%s>.' % path)

    @staticmethod
    def _decode(data):
        """
        At times we receive data with incorrect padding. This code will
        keep truncating the data until it decodes. We hope the (un)gzip
        process will catch any erroneous result.

        data: string
            Data to be decoded.
        """
        while data:
            try:
                data = base64.b64decode(data)
            except TypeError:
                data = data[:-1]
            else:
                break
        return data

    def list_properties(self):
        """ Return lines listing properties. """
        return ('description (type=java.lang.String) (access=g)',
                'isBinary (type=boolean) (access=g)',
                'mimeType (type=java.lang.String) (access=g)',
                'name (type=java.lang.String) (access=g)',
                'nameCoded (type=java.lang.String) (access=g)',
                'url (type=java.lang.String) (access=g)')

_register(FileRef, FileWrapper)
