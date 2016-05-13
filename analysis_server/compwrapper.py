"""
Component wrappers are created by the ``start`` command after the associated
component's server has been started.
"""
import os
import sys
import time
import logging

import xml.etree.cElementTree as ElementTree
from xml.sax.saxutils import escape

try:
    import resource
except ImportError:  # pragma no cover
    pass  # Not available on Windows.

from analysis_server.varwrapper import _find_var_wrapper, _float2str

# import var wrappers so they get registered
import analysis_server.floatwrapper
import analysis_server.intwrapper
import analysis_server.strwrapper
import analysis_server.boolwrapper
import analysis_server.enumwrapper
import analysis_server.arrwrapper
import analysis_server.objwrapper
import analysis_server.listwrapper
from analysis_server.filewrapper import FileWrapper

class ComponentWrapper(object):
    """
    Component wrapper providing a ModelCenter AnalysisServer interface,
    based on the protocol described in:
    http://www.phoenix-int.com/~AnalysisServer/commands/index.html

    Wraps component `comp`, named `name`, with configuraton `cfg` on `server`.
    `send_reply` and `send_exc` are used to communicate back to the client.

    name: string
        Instance name.

    proxy: proxy
        Proxy to remote component.

    cfg: :class:`server._WrapperConfig`
        Component configuration data.

    manager: proxy
        Proxy to remote manager hosting remote component.

    send_reply: callable
        Used to send a reply message back to client.

    send_exc: callable
        Used to send an exception message back to client.

    logger: :class:`logging.Logger`
        Used for progress, errors, etc.
    """

    def __init__(self, name, proxy, cfg, manager, send_reply, send_exc):
        self._name = name
        self._comp = proxy
        self._cfg = cfg
        self._manager = manager
        self._send_reply = send_reply
        self._send_exc = send_exc
        self._monitors = {}  # Maps from monitor_id to monitor.
        self._wrappers = {}  # Maps from internal var path to var wrapper.
        self._path_map = {}  # Maps from external path to (var wrapper, attr).
        self._start = None
        self._rusage = None  # For ps() on UNIX.
        self._logger = logging.getLogger(name)

    def _get_var_wrapper(self, ext_path):
        """
        Return '(wrapper, attr)' for `ext_path`.

        ext_path: string
            External reference for variable.
        """
        try:
            return self._path_map[ext_path]
        except KeyError:
            # Determine internal path to variable.
            ext_attr = None
            if ext_path in self._cfg.properties:
                int_path = self._cfg.properties[ext_path]
                epath = ext_path
            else:
                epath, _, ext_attr = ext_path.rpartition('.')
                if epath in self._cfg.properties:
                    int_path = self._cfg.properties[epath]
                else:
                    raise RuntimeError('no such property <%s>.' % ext_path)
            try:
                wrapper = self._wrappers[int_path]
            except KeyError:
                # Find variable.
                val = self._comp.get(int_path)
                wrapper_class = _find_var_wrapper(val)

                if wrapper_class is None:
                    raise RuntimeError('%s: unsupported variable type %r.'
                                       % (ext_path, type(val).__name__))
                # Wrap it.
                wrapper = wrapper_class(self._comp, int_path, epath, self._cfg)
                if wrapper_class is FileWrapper:
                    wrapper.set_manager(self._manager)
                self._wrappers[int_path] = wrapper

            attr = ext_attr or 'value'
            map_value = (wrapper, attr)
            self._path_map[ext_path] = map_value
            return map_value

    def pre_delete(self):
        """ Prepare for deletion. """
        for monitor in self._monitors.values():
            monitor.stop()
        self._comp.pre_delete()

    def run(self, req_id):
        """
        Runs a component instance.

        req_id: string
            'Raw' mode request identifier.
        """
        try:
            if sys.platform != 'win32':
                self._rusage = resource.getrusage(resource.RUSAGE_SELF)

            self._start = time.time()
            try:
                self._comp.run()
            except Exception as exc:
                self._logger.exception('run() failed:')
                raise RuntimeError('%s' % exc)
            else:
                self._send_reply('%s completed.' % self._name, req_id)
            finally:
                self._start = None
        except Exception as exc:
            self._send_exc(exc, req_id)

    def get(self, path, req_id):
        """
        Returns the value of a variable.

        path: string
            External variable reference.

        req_id: string
            'Raw' mode request identifier.
        """
        try:
            wrapper, attr = self._get_var_wrapper(path)
            self._send_reply(wrapper.get(attr, path), req_id)
        except Exception as exc:
            self._send_exc(exc, req_id)

    def get_hierarchy(self, req_id, gzipped):
        """
        Return all inputs & outputs as XML.

        req_id: string
            'Raw' mode request identifier.

        gzipped: bool
            If True, file data is gzipped and then base64 encoded.
        """
        try:
            group = ''
            lines = []
            lines.append("<?xml version='1.0' encoding='utf-8'?>")
            lines.append('<Group>')
            for path in sorted(self._cfg.properties.keys()):
                vwrapper, attr = self._get_var_wrapper(path)
                prefix, _, name = path.rpartition('.')
                if prefix != group:
                    while not prefix.startswith(group):  # Exit subgroups.
                        lines.append('</Group>')
                        group, _, name = group.rpartition('.')
                    name, _, rest = prefix.partition('.')
                    if name:
                        lines.append('<Group name="%s">' % name)
                    while rest:  # Enter subgroups.
                        name, _, rest = rest.partition('.')
                        lines.append('<Group name="%s">' % name)
                    group = prefix
                try:
                    lines.append(vwrapper.get_as_xml(gzipped))
                except Exception as exc:
                    raise type(exc)("Can't get %r: %s %s" % (path, vwrapper,exc))
            lines.append('</Group>')
            self._send_reply('\n'.join(lines), req_id)
        except Exception as exc:
            self._send_exc(exc, req_id)

    def invoke(self, method, full, req_id):
        """
        Invokes a method on a component instance.

        method: string
            External method reference.

        full: bool
            If True, return result as XML.

        req_id: string
            'Raw' mode request identifier.
        """
        try:
            try:
                attr = self._cfg.methods[method]
            except KeyError:
                raise RuntimeError('no such method <%s>.' % method)

            result = self._comp.invoke(attr)
            if result is None:
                reply = ''
            elif isinstance(result, float):
                reply = _float2str(result)
            elif isinstance(result, basestring):
                reply = result.encode('string_escape')
            else:
                reply = str(result)

            # Setting 'download' True since we have no idea about side-effects.
            if full:
                reply = """\
<?xml version="1.0" encoding="UTF-8" standalone="no" ?>\
<response>\
<version>100.0</version>\
<download>true</download>\
<string>%s</string>\
</response>""" % escape(reply)

            self._send_reply(reply, req_id)
        except Exception as exc:
            self._send_exc(exc, req_id)

    def list_array_values(self, path, req_id):
        """
        Lists all the values of an array variable.

        path: string
            External reference to array.

        req_id: string
            'Raw' mode request identifier.
        """
        try:
            raise NotImplementedError('listArrayValues')
        except Exception as exc:
            self._send_exc(exc, req_id)

    def list_methods(self, full, req_id):
        """
        Lists all methods available on a component instance.

        full: bool
            If True, include 'full/long' name.

        req_id: string
            'Raw' mode request identifier.
        """
        try:
            lines = ['']
            for name in sorted(self._cfg.methods):
                line = '%s()' % name
                if full:
                    line += ' fullName="%s/%s"' % (self._cfg.section, name)
                lines.append(line)

            lines[0] = '%d methods found:' % (len(lines)-1)
            self._send_reply('\n'.join(lines), req_id)
        except Exception as exc:
            self._send_exc(exc, req_id)

    def list_monitors(self, req_id):
        """
        Lists all available monitorable items on a component instance.

        req_id: string
            'Raw' mode request identifier.
        """
        try:
            root = self._comp.get_abs_directory()
            if self._manager is None:  # Used when testing.
                paths = os.listdir(root)
                paths = [path for path in paths
                              if not os.path.isdir(os.path.join(root, path))]
            else:  # pragma no cover
                paths = self._manager.listdir(root)
                paths = [path for path in paths
                            if not self._manager.isdir(os.path.join(root, path))]
            paths = [path for path in paths if not path.startswith('.')]
            text_files = []
            for path in paths:  # List only text files.
                if self._manager is None:  # Used when testing.
                    inp = open(os.path.join(root, path), 'rb')
                else:  # pragma no cover
                    inp = self._manager.open(os.path.join(root, path), 'rb')
                try:
                    data = inp.read(1 << 12)  # 4KB
                    if '\x00' not in data:
                        text_files.append(path)
                finally:
                    inp.close()
            lines = ['%d monitors:' % len(text_files)]
            lines.extend(sorted(text_files))
            self._send_reply('\n'.join(lines), req_id)
        except Exception as exc:
            self._send_exc(exc, req_id)

    def list_properties(self, path, req_id):
        """
        Lists all available variables and their sub-properties on a component
        instance or sub-variable.

        path: string
            External reference.

        req_id: string
            'Raw' mode request identifier.
        """
        try:
            self._send_reply(self._list_properties(path), req_id)
        except Exception as exc:
            self._send_exc(exc, req_id)

    def _list_properties(self, path):
        """
        Lists all available variables and their sub-properties on a component
        instance or sub-variable.

        path: string
            External reference.
        """
        lines = ['']
        try:
            wrapper, attr = self._get_var_wrapper(path)
        except RuntimeError:
            # Must be a subsystem.
            if path:
                path += '.'
            length = len(path)
            groups = set()
            for ext_path in sorted(self._cfg.properties.keys()):
                if path and not ext_path.startswith(path):
                    continue
                rest = ext_path[length:]
                name, _, rest = rest.partition('.')
                if rest:
                    if name in groups:
                        continue
                    groups.add(name)
                    typ = 'com.phoenix_int.aserver.PHXGroup'
                    access = 'sg'
                else:
                    wrapper, attr = self._get_var_wrapper(ext_path)
                    typ = wrapper.phx_type
                    access = wrapper.phx_access
                lines.append('%s (type=%s) (access=%s)' % (name, typ, access))
        else:
            lines.extend(wrapper.list_properties())
        lines[0] = '%d properties found:' % (len(lines)-1)
        return '\n'.join(lines)

    def list_values(self, path, req_id):
        """
        Lists all available variables and their sub-properties on a component
        instance or sub-variable.

        path: string
            External reference.

        req_id: string
            'Raw' mode request identifier.
        """
        try:
            lines = []
            # Get list of properties.
            props = self._list_properties(path).split('\n')
            lines.append(props[0])
            if path:
                path += '.'
            # Collect detailed property information.
            for line in props[1:]:
                name, typ, access = line.split()
                if typ == '(type=com.phoenix_int.aserver.PHXGroup)':
                    val = 'Group: %s' % name
                    lines.append('%s %s %s  vLen=%d  val=%s'
                                 % (name, typ, access, len(val), val))
                else:
                    ext_path = path + name
                    wrapper, attr = self._get_var_wrapper(ext_path)
                    val = wrapper.get('value', ext_path)
                    lines.append('%s %s %s  vLen=%d  val=%s'
                                 % (name, typ, access, len(val), val))
                    if path:
                        continue  # No sub_props.

                    sub_props = self._list_properties(ext_path).split('\n')
                    sub_props = sub_props[1:]
                    lines.append('   %d SubProps found:' % len(sub_props))
                    for line in sub_props:
                        name, typ, access = line.split()
                        if typ == '(type=com.phoenix_int.aserver.PHXGroup)':
                            val = 'Group: %s' % name
                            lines.append('%s %s %s  vLen=%d  val=%s'
                                         % (name, typ, access, len(val), val))
                        else:
                            val = wrapper.get(name, ext_path)
                            lines.append('%s %s %s  vLen=%d  val=%s'
                                         % (name, typ, access, len(val), val))
            self._send_reply('\n'.join(lines), req_id)
        except Exception as exc:
            self._send_exc(exc, req_id)

    def list_values_url(self, path, req_id):
        """
        Lists all available variables and their sub-properties on a component
        instance or sub-variable. This version supplies a URL for file data
        if DirectFileTransfer is supported.

        path: string
            External reference.

        req_id: string
            'Raw' mode request identifier.
        """
        self.list_values(path, req_id)

    def start_monitor(self, path, req_id):
        """
        Starts a monitor on a raw output file or available monitor.

        path: string
            Monitor reference.

        req_id: string
            'Raw' mode request identifier.
        """
        try:
            path = os.path.join(self._comp.get_abs_directory(), path)
            monitor = FileMonitor(self._manager, path, 'r',
                                  req_id, self._send_reply)
            monitor.start()
            self._monitors[str(req_id)] = monitor  # Monitor id is request id.
        except Exception as exc:
            self._send_exc(exc, req_id)

    def stop_monitor(self, monitor_id, req_id):
        """
        Stops a monitor on a raw output file or available monitor.

        monitor_id: string
            Monitor identifier.

        req_id: string
            'Raw' mode request identifier.
        """
        try:
            monitor = self._monitors.pop(monitor_id)
        # Invalid monitor_id intercepted by server.py
        except KeyError:  # pragma no cover
            raise RuntimeError('No registered monitor for %r' % monitor_id)
        else:
            monitor.stop()
            self._send_reply('', req_id)

    def ps(self, req_id):
        """
        Lists all running processes for a component instance.

        req_id: string
            'Raw' mode request identifier.
        """
        try:
            pid = os.getpid()
            command = os.path.basename(sys.executable)

            if self._start is None:  # Component not running.
                # Forcing PID to zero helps with testing.
                reply = """\
<Processes length='1'>
 <Process pid='0'>
  <ParentPID>0</ParentPID>
  <PercentCPU>0.0</PercentCPU>
  <Memory>0</Memory>
  <Time>0</Time>
  <WallTime>0</WallTime>
  <Command>%s</Command>
 </Process>
</Processes>""" % escape(command)

            else:
                now = time.time()
                walltime = now - self._start

                if sys.platform == 'win32':  # pragma no cover
                    reply = """\
<Processes length='1'>
 <Process pid='%d'>
  <ParentPID>0</ParentPID>
  <PercentCPU>0.0</PercentCPU>
  <Memory>0</Memory>
  <Time>0</Time>
  <WallTime>%.1f</WallTime>
  <Command>%s</Command>
 </Process>
</Processes>""" % (pid, walltime, escape(command))

                else:
                    rusage = resource.getrusage(resource.RUSAGE_SELF)
                    cputime = (rusage.ru_utime + rusage.ru_stime) \
                            - (self._rusage.ru_utime + self._rusage.ru_stime)
                    if walltime > 0:
                        percent_cpu = cputime / walltime
                    else:
                        percent_cpu = 0.
                    memory = rusage.maxrss * resource.getpagesize()

                    reply = """\
<Processes length='1'>
 <Process pid='%d'>
  <ParentPID>%d</ParentPID>
  <PercentCPU>%.1f</PercentCPU>
  <Memory>%d</Memory>
  <Time>%.1f</Time>
  <WallTime>%.1f</WallTime>
  <Command>%s</Command>
 </Process>
</Processes>""" % (pid, os.getppid(), percent_cpu, memory, cputime, walltime,
                   escape(command))

            self._send_reply(reply, req_id)
        except Exception as exc:
            self._send_exc(exc, req_id)

    def set(self, path, valstr, req_id):
        """
        Sets the value of `path` to `valstr`.

        path: string
            External reference to variable.

        valstr: string
            Value to set.

        req_id: string
            'Raw' mode request identifier.
        """
        # Quotes around the value are semi-optional.
        if valstr.startswith('"') and valstr.endswith('"'):
            valstr = valstr[1:-1]
        try:
            self._set(path, valstr)
            self._send_reply('value set for <%s>' % path, req_id)
        except Exception as exc:
            self._send_exc(exc, req_id)

    def _set(self, path, valstr, gzipped=False):
        """
        Sets the value of `path` to `valstr`.

        path: string
            External reference to variable.

        valstr: string
            Value to set.

        gzipped: bool
            If True, file data is gzipped and then base64 encoded.
        """
        wrapper, attr = self._get_var_wrapper(path)
        wrapper.set(attr, path, valstr, gzipped)

    def set_hierarchy(self, xml, req_id):
        """
        Set hierarchy of variable values from `xml`.

        xml: string
            XML describing values to be set.

        req_id: string
            'Raw' mode request identifier.
        """
        try:
            header, _, xml = xml.partition('\n')
            root = ElementTree.fromstring(xml)
            for var in root.findall('Variable'):
                valstr = var.text or ''
                if var.get('gzipped', 'false') == 'true':
                    gzipped = True
                else:
                    gzipped = False
                try:
                    self._set(var.attrib['name'], valstr, gzipped)
                except Exception as exc:
                    self._logger.exception("Can't set %r", var.attrib['name'])
                    raise type(exc)("Can't set %r from %r: %s"
                                    % (var.attrib['name'], valstr[:1000], exc))
            self._send_reply('values set', req_id)
        except Exception as exc:
            self._send_exc(exc, req_id)
