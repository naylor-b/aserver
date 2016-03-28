"""
Server providing a ModelCenter AnalysisServer interface, based on the
protocol described in:
http://www.phoenix-int.com/~AnalysisServer/commands/index.html

Each client is serviced by a separate thread. Each client's components are
maintained in a separate namespace. Components are hosted by individual server
processes, each serviced by a separate wrapper thread.

Separate log files for each client connection are written to the ``logs``
directory. Log files are named ``<hostIP>_<port>.txt``.

Component types to be supported are described by ``<name>.cfg`` files parsed
by :class:`ConfigParser.SafeConfigParser`, for example::

    [AnalysisServer]
    version: 0.1
    author: anonymous
    filename: TestComponent.py
    directory: cart3d-sim
    description: Component for testing AnalysisServer functionality.
    help_url: unknown
    keywords:

The name in <name>.cfg is assumed to be the name of the class to be
instantiated in the given python file.
"""

from __future__ import print_function

import os
import sys
import ConfigParser
import getpass
import inspect
import logging
import optparse
import platform
import shutil
import signal
import SocketServer
import socket
import threading
import time
import traceback

if sys.platform != 'win32':
    import pwd

from openmdao.api import Component, Group, Problem

from openmdao.util.shell_proc import ShellProc, STDOUT
from openmdao.util.file_util import DirContext

from analysis_server.stream  import Stream
from analysis_server.wrkpool import WorkerPool
from analysis_server.publickey import make_private
from analysis_server.mp_util import read_allowed_hosts
from analysis_server.cfg_wrapper import _ConfigWrapper
# from analysis_server.wrapper import ComponentWrapper, _find_var_wrapper
# from analysis_server.filexfer import filexfer


DEFAULT_PORT = 1835
ERROR_PREFIX = 'ERROR: '

# Our version.
_VERSION = '0.1'

# The implementation level we approximate.
_AS_VERSION = '7.0'
_AS_BUILD = '42968'

# Maps from command string to command handler.
_COMMANDS = {}

_DBG_LEN = 10000  # Max length of debug log message.

class _ThreadedDictContextMgr(object):
    """ Share `dct` among multiple threads via the 'with' statement. """

    def __init__(self, dct):
        self._dct = dct
        self._lock = threading.Lock()

    def __enter__(self):
        self._lock.acquire()
        return self._dct

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._lock.release()


class Server(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
    """
    Server to process client requests. Reads all component configuration files
    found in the current directory and subdirectories.

    host: string
        Host name or IP address to use.

    port: int
        The port to use

    allowed_hosts: list[string]
        Allowed host or domain addresses (domain addresses must end in '.').
        If None, '127.0.0.1' is used (only the local host is allowed access).
    """

    allow_reuse_address = True

    def __init__(self, host='localhost', port=DEFAULT_PORT, allowed_hosts=None):
        SocketServer.TCPServer.__init__(self, (host, port), _Handler)

        self._allowed_hosts = allowed_hosts or ['127.0.0.1']
        self._num_clients = 0
        self._components = {}  # Maps from category/component to (cfg, egg_info)
        self._handlers = {}    # Maps from client address to handler.
        self._comp_ctx = _ThreadedDictContextMgr(self._components)
        self._hdlr_ctx = _ThreadedDictContextMgr(self._handlers)
        #self._credentials = get_credentials()  # For PublicKey servers.
        self._root = os.getcwd()
        self._dir_lock = threading.RLock()
        self._config_errors = 0
        self._read_comp_configurations()

        # Set False in test_server.py to avoid issues trying to clean up
        # the 'logs' directory under Windows.
        self.per_client_loggers = True

    @property
    def dir_lock(self):
        """ Lock for synchronizing file operations. """
        return self._dir_lock

    @property
    def num_clients(self):
        """ Number of clients. """
        return self._num_clients

    @property
    def handlers(self):
        """ Handler map context manager. """
        return self._hdlr_ctx

    @property
    def components(self):
        """ Component map context manager. """
        return self._comp_ctx

    @property
    def config_errors(self):
        """ Number of configuration errors detected. """
        return self._config_errors

    def _read_comp_configurations(self):
        """ Read component configuration files. """
        for dirpath, dirnames, filenames in os.walk('.'):
            for name in sorted(filenames):
                if name.endswith('.cfg'):
                    path = os.path.join(dirpath, name)
                    path = path.lstrip('.').lstrip(os.sep)
                    try:
                        self.read_config(path)
                    except Exception as exc:
                        print(str(exc) or repr(exc))
                        logging.error(str(exc) or repr(exc))
                        self._config_errors += 1

    def read_config(self, path):
        """
        Read component configuration file.

        path: string
            Path to config file.

        """
        logging.info('Reading config file %r', path)
        config = ConfigParser.SafeConfigParser()
        config.optionxform = str  # Preserve case.
        files = config.read(path)
        if not files:
            raise RuntimeError("Can't read %r" % path)

        directory = os.path.dirname(path)
        with self.dir_lock:
            orig = os.getcwd()
            if directory:
                os.chdir(directory)
            try:
                self._process_config(config, path)
            finally:
                os.chdir(orig)

    def _process_config(self, config, path):
        """
        Process data read into `config` from `path`.

        config: :class:`ConfigParser.ConfigParser`
            Configuration data.

        path: string
            Path to config file.

        """
        for sect in ('AnalysisServer',):
            if not config.has_section(sect):
                raise RuntimeError("No %s section in %r" % (sect, path))

        if config.has_option('AnalysisServer', 'version'):
            cfg_version = config.get('AnalysisServer', 'version')
        else:
            raise ValueError('No version metadata found in in %s file' %
                             path)

        cfg_dir = os.path.dirname(path)
        cfg_name = os.path.basename(path)
        name = os.path.splitext(cfg_name)[0]

        cwd = os.getcwd()
        cleanup = not os.path.exists(name)
        try:
            # Get Python class and create temporary instance.
            classname = name
            filename = config.get('AnalysisServer', 'filename')
            dirname = os.path.dirname(filename)
            modname = os.path.splitext(os.path.basename(filename))[0]  # drop '.py'
            if not os.path.isabs(dirname):
                if dirname:
                    dirname = os.path.join(cwd, dirname)
                else:
                    dirname = cwd

            if not dirname in sys.path:
                logging.info('    prepending %r to sys.path', dirname)
                sys.path.insert(0, dirname)
                prepended = True
            else:
                prepended = False
            try:
                __import__(modname)
            except ImportError as exc:
                raise RuntimeError("Can't import %r: %r" \
                                   % (modname, exc))
            finally:
                if prepended:
                    sys.path.pop(0)

            module = sys.modules[modname]
            try:
                cls = getattr(module, classname)
            except AttributeError as exc:
                raise RuntimeError("Can't get class %r in %r: %r"
                                   % (classname, modname, exc))

            with DirContext(dirname):
                try:
                    obj = cls()
                except Exception as exc:
                    logging.error(traceback.format_exc())
                    raise RuntimeError("Can't instantiate %s.%s: %r"
                                       % (modname, classname, exc))

                if isinstance(obj, Group):
                    root = obj
                else:
                    root = Group()

                p = Problem(root=root)
                if obj is not root:
                    root.add('comp', obj)

                p.setup(check=False)

            # Check for optional diectory path.
            directory = None
            if config.has_option('AnalysisServer', 'directory'):
                directory = config.get('AnalysisServer', 'directory')
                if os.path.isabs(directory) or directory.startswith('..'):
                    raise ValueError('directory %r must be a subdirectory'
                                     % directory)

            # Create wrapper configuration object.
            cfg_path = os.path.join(cwd, os.path.basename(path))
            try:
                cfg = _ConfigWrapper(config, obj, cfg_path)
            except Exception as exc:
                logging.error(traceback.format_exc())
                raise RuntimeError("Bad configuration in %r: %s" % (path, exc))

            # Register components in a flat structure.
            path = cfg.cfg_path[len(self._root)+1:-4]  # Drop prefix & '.cfg'
            path = path.replace('\\', '/')  # Always use '/'.
            logging.debug('    registering %s', path)
            with self.components as comps:
                comps[path.split('/')[-1]] = (cfg, None, None, directory)
            p.cleanup()
            if hasattr(obj, 'pre_delete'):
                obj.pre_delete()

        finally:
            if cleanup and os.path.exists(name):
                shutil.rmtree(name)

    # This will be exercised by client side tests.
    def finish_request(self, request, client_address):  # pragma no cover
        """
        Overrides superclass to track active clients and cleanup
        upon client disconnect.

        request: string
            Request message.

        client_address: ``(host, port)``
            Source of client request.
        """
        host, port = client_address
        logging.info('Connection from %s:%s', host, port)
        self._num_clients += 1
        try:
            SocketServer.TCPServer.finish_request(self, request, client_address)
        finally:
            logging.info('Disconnect %s:%s', host, port)
            self._num_clients -= 1
            with self.handlers as handlers:
                try:  # It seems handler.finish() isn't called on disconnect...
                    handlers[client_address].cleanup()
                except Exception, exc:
                    logging.warning('Exception during handler cleanup: %r', exc)


class _Handler(SocketServer.BaseRequestHandler):
    """ Handles requests from a single client. """

    def setup(self):
        """ Initialize before :meth:`handle` is invoked. """
        with self.server.handlers as handlers:
            handlers[self.client_address] = self
        self._stream = Stream(self.request)
        self._lock = threading.Lock()  # Synchronize access to reply stream.
        self._raw = False
        self._req = None
        self._req_id = None
        self._background = False
        self._hb = None
        self._monitors = {}      # Maps from req_id to name.
        self._instance_map = {}  # Maps from name to (wrapper, worker).
        self._servers = {}       # Maps from wrapper to server.
        #set_credentials(self.server.credentials)

        # Set up separate logger for each client.
        if self.server.per_client_loggers:  # pragma no cover
            self._logger = logging.getLogger('%s:%s' % self.client_address)
            self._logger.setLevel(logging.getLogger().getEffectiveLevel())
            self._logger.propagate = False
            formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s',
                                          '%b %d %H:%M:%S')
            filename = os.path.join('logs', '%s_%s.txt' % self.client_address)
            handler = logging.FileHandler(filename, mode='w')
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)
        else:
            self._logger = logging

        # Set False during some testing for coverage check.
        # Also avoids odd problems under nose suite test.
        self._server_per_obj = True

        self._centerlink_dict = {}  # Used for testing 'setDictionary'.

    def handle(self):
        """ Process any received requests. """
        self._send_reply("""\
Welcome to the OpenMDAO Analysis Server.
version: %s""" % _VERSION)

        self._logger.info('Serving client at %s:%s',
                          self.client_address[0], self.client_address[1])
        try:
            while self._req != 'quit':
                try:
                    # Get next request.
                    if self._raw:
                        self._logger.debug('Waiting for raw-mode request...')
                        req, req_id, background = self._stream.recv_request()
                        text, zero, rest = req.partition('\x00')
                        if zero:
                            self._logger.debug('Request: %r <+binary...> (id %s bg %s)',
                                               text[:_DBG_LEN],
                                               req_id, background)
                        else:
                            trunc = 'truncated ' if len(req) > _DBG_LEN else ''
                            self._logger.debug('Request: %r (%sid %s bg %s)',
                                               req[:_DBG_LEN],
                                               trunc, req_id, background)
                        self._req_id = req_id
                        self._background = background
                    else:
                        self._logger.debug('Waiting for request...')
                        req = self._stream.recv_request()
                        trunc = ' (truncated)' if len(req) > _DBG_LEN else ''
                        # Don't log password!
                        if not req.startswith('setDictionary'):
                            self._logger.debug('Request: %r%s',
                                               req[:_DBG_LEN], trunc)
                        self._req_id = None
                        self._background = False

                    # Just being defensive.
                    if not req:  # pragma no cover
                        continue

                    # Lookup request handler.
                    args = req.split()
                    self._req = req
                    try:
                        cmd = _COMMANDS[args[0]]
                    except KeyError:
                        self._send_error('command <%s> not recognized'
                                         % req.strip())
                        continue

                    # Process request.
                    try:
                        cmd(self, args[1:])
                    except Exception as exc:
                        self._send_exc(exc)

                except EOFError:
                    break
        finally:
            self.cleanup()

    def cleanup(self):
        """ 'end' all existing objects. """
        self._logger.info('Shutdown')
        if self._hb is not None:
            self._hb.stop()
        for name in self._instance_map.keys():
            self.__end(name)

    def _send_reply(self, reply, req_id=None):
        """
        Send reply to client, with optional logging.

        reply: string
            Reply message.

        req_id: string
            Request ID, if requested in 'raw' mode.
        """
        if self._raw:
            req_id = req_id or self._req_id
            text, zero, rest = reply.partition('\x00')
            if zero:
                self._logger.debug('(req_id %s)\n%s\n<+binary...>',
                                   req_id, text[:_DBG_LEN])
            else:
                trunc = ' truncated' if len(reply) > _DBG_LEN else ''
                self._logger.debug('(req_id %s%s)\n%s',
                                   req_id, trunc, reply[:_DBG_LEN])
        else:
            trunc = ' (truncated)' if len(reply) > _DBG_LEN else ''
            self._logger.debug('    %s%s', reply[:_DBG_LEN], trunc)
        with self._lock:
            self._stream.send_reply(reply, req_id)

    def _send_error(self, reply, req_id=None):
        """
        Send error reply to client, with optional logging.

        reply: string
            Reply message.

        req_id: string
            Request ID, if requested in 'raw' mode.
        """
        if self._raw:
            req_id = req_id or self._req_id
            self._logger.error('(req_id %s)\n%s', req_id, reply)
        else:
            self._logger.error('%s', reply)
        reply = ERROR_PREFIX+reply
        with self._lock:
            self._stream.send_reply(reply, req_id, 'error')

    def _send_exc(self, exc, req_id=None):
        """
        Send exception reply to client, with optional logging.

        exc: Exception
            Exception data.

        req_id: string
            Request ID, if requested in 'raw' mode.
        """
        self._send_error('Exception: %r' % exc, req_id)
        self._logger.error(traceback.format_exc())

    ######################################
    # TELNET API methods
    ######################################
    def _help(self, args):
        """
        Help on Analysis Server commands.

        args: list[string]
            Arguments for the command.
        """
        if len(args) != 0:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'help,h')
            return

        # As listed by Analysis Server version: 7.0, build: 42968.
        self._send_reply("""\
Available Commands:
   listComponents,lc [category]
   listCategories,la [category]
   describe,d <category/component> [-xml]
   setServerAuthInfo <serverURL> <username> <password> (NOT IMPLEMENTED)
   start <category/component> <instanceName> [connector] [queue]
   end <object>
   execute,x <objectName>
   listProperties,list,ls,l [object]
   listGlobals,lg
   listValues,lv <object>
   listArrayValues,lav <object> (NOT IMPLEMENTED)
   get <object.property>
   set <object.property> = <value>
   move,rename,mv,rn <from> <to> (NOT IMPLEMENTED)
   getIcon <analysisComponent> (NOT IMPLEMENTED)
   getIcon2 <analysisComponent> (NOT IMPLEMENTED)
   getVersion
   getLicense
   getStatus
   help,h
   quit
   getSysInfo
   invoke <object.method()> [full]
   listMethods,lm <object> [full]
   addProxyClients <clientHost1>,<clientHost2>
   monitor start <object.property>, monitor stop <id>
   versions,v category/component
   ps <object>
   listMonitors,lo <objectName>
   heartbeat,hb [start|stop]
   listValuesURL,lvu <object>
   getDirectTransfer
   getByUrl <object.property> <url> (NOT IMPLEMENTED)
   setByUrl <object.property> = <url> (NOT IMPLEMENTED)
   setDictionary <xml dictionary string> (xml accepted, but not used)
   getHierarchy <object.property>
   setHierarchy <object.property> <xml>
   deleteRunShare <key> (NOT IMPLEMENTED)
   getBranchesAndTags (NOT IMPLEMENTED)
   getQueues <category/component> [full] (NOT IMPLEMENTED)
   setRunQueue <object> <connector> <queue> (NOT IMPLEMENTED)""")

    def _get_sys_info(self, args):
        """
        Retrieves information about the server and the system it is on.

        args: list[string]
            Arguments for the command.
        """
        if len(args) != 0:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'getSysInfo')
            return

        with self.server.components as comps:
            num_comps = len(comps)

        self._send_reply("""\
version: %s
build: %s
num clients: %d
num components: %d
os name: %s
os arch: %s
os version: %s
python version: %s
user name: %s"""
             % (_AS_VERSION, _AS_BUILD, self.server.num_clients, num_comps,
                platform.system(), platform.processor(),
                platform.release(), platform.python_version(),
                getpass.getuser()))

    def _get_version(self, args):
        """
        Gets the version and build number for Analysis Server.

        args: list[string]
            Arguments for the command.
        """
        if len(args) != 0:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'getVersion')
            return

        self._send_reply("""\
OpenMDAO Analysis Server %s
Use at your own risk!
Attempting to support Phoenix Integration, Inc.
version: %s, build: %s""" % (_VERSION, _AS_VERSION, _AS_BUILD))

    def _list_components(self, args):
        """
        Lists all the components available.

        args: list[string]
            Arguments for the command.
        """
        if len(args) > 1:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'listComponents,lc')
            return

        with self.server.components as comps:
            lines = ['%d components found:' % len(comps)]
            lines.extend(sorted(comps.keys()))
        self._send_reply('\n'.join(lines))

    def _quit(self, args):
        """
        Close the connection.

        args: list[string]
            Arguments for the command.
        """
        if len(args) != 0:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'quit')
            return

        self._logger.info('Client quit')



    def _start(self, args):
        """
        Creates a new component instance.

        args: list[string]
            Arguments for the command.
        """
        if len(args) < 2 or len(args) > 4:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'start <component> <instanceName> [connector] [queue]')
            return

        if len(args) > 2:
            raise NotImplementedError('start, args > 2')

        comp = self._get_component(args[0])
        if comp is None:
            return
        cfg, _, _, directory = comp

        name = args[1]
        if name in self._instance_map:
            self._send_error('Name already in use: "%s"' % name)
            return

        self._logger.info('Starting %r, directory %r',
                          name, directory)

        # Create component instance.
        with self.server.dir_lock:
            if self._server_per_obj:  # pragma no cover
                # Allocate a server.
                server, server_info = RAM.allocate(resource_desc)
                if server is None:
                    raise RuntimeError('Server allocation failed :-(')

                obj = server.load_model(egg_name)
            else:  # Used for testing.
                server = None
                obj = Container.load_from_eggfile(egg_file, log=self._logger)
        obj.name = name

        # Create wrapper for component.
        wrapper = ComponentWrapper(name, obj, cfg, server, self._send_reply,
                                   self._send_exc, self._logger)
        self._instance_map[name] = (wrapper, WorkerPool.get())
        self._servers[wrapper] = server
        self._send_reply('Object %s started.' % name)




    # Telnet API
    # _COMMANDS['addProxyClients'] = _add_proxy_clients
    # _COMMANDS['d'] = _describe
    # _COMMANDS['describe'] = _describe
    # _COMMANDS['end'] = _end
    # _COMMANDS['execute'] = _execute
    # _COMMANDS['getBranchesAndTags'] = _get_branches
    # _COMMANDS['getDirectTransfer'] = _get_direct_transfer
    # _COMMANDS['get'] = _get
    # _COMMANDS['getHierarchy'] = _get_hierarchy
    # _COMMANDS['getIcon2'] = _get_icon2
    # _COMMANDS['getIcon'] = _get_icon
    # _COMMANDS['getLicense'] = _get_license
    # _COMMANDS['getQueues'] = _get_queues
    # _COMMANDS['getStatus'] = _get_status
    _COMMANDS['getSysInfo'] = _get_sys_info
    _COMMANDS['getVersion'] = _get_version
    # _COMMANDS['hb'] = _heartbeat
    # _COMMANDS['heartbeat'] = _heartbeat
    _COMMANDS['help'] = _help
    _COMMANDS['h'] = _help
    # _COMMANDS['invoke'] = _invoke
    # _COMMANDS['l'] = _list_properties
    # _COMMANDS['la'] = _list_categories
    # _COMMANDS['lav'] = _list_array_values
    # _COMMANDS['lc'] = _list_components
    # _COMMANDS['lg'] = _list_globals
    # _COMMANDS['listArrayValues'] = _list_array_values
    # _COMMANDS['listCategories'] = _list_categories
    _COMMANDS['listComponents'] = _list_components
    # _COMMANDS['listGlobals'] = _list_globals
    # _COMMANDS['list'] = _list_properties
    # _COMMANDS['listMethods'] = _list_methods
    # _COMMANDS['listMonitors'] = _list_monitors
    # _COMMANDS['listProperties'] = _list_properties
    # _COMMANDS['listValues'] = _list_values
    # _COMMANDS['listValuesURL'] = _list_values_url
    # _COMMANDS['lm'] = _list_methods
    # _COMMANDS['lo'] = _list_monitors
    # _COMMANDS['ls'] = _list_properties
    # _COMMANDS['lv'] = _list_values
    # _COMMANDS['lvu'] = _list_values_url
    # _COMMANDS['monitor'] = _monitor
    # _COMMANDS['move'] = _move
    # _COMMANDS['mv'] = _move
    # _COMMANDS['ps'] = _ps
    _COMMANDS['quit'] = _quit
    # _COMMANDS['rename'] = _move
    # _COMMANDS['rn'] = _move
    # _COMMANDS['setDictionary'] = _set_dictionary
    # _COMMANDS['setHierarchy'] = _set_hierarchy
    # _COMMANDS['setMode'] = _set_mode
    # _COMMANDS['setRunQueue'] = _set_run_queue
    # _COMMANDS['setServerAuthInfo'] = _set_auth_info
    # _COMMANDS['set'] = _set
    # _COMMANDS['start'] = _start
    # _COMMANDS['versions'] = _versions
    # _COMMANDS['v'] = _versions
    # _COMMANDS['x'] = _execute







def start_server(address='localhost', port=DEFAULT_PORT, allowed_hosts=None,
                 debug=False, resources=None):
    """
    Start server process at `address` and `port`.
    Returns ``(proc, port)``.

    address: string
        Server address to be used.

    port: int
        Server port to be used. Use zero for a system-selected port.

    allowed_hosts: list[string]
        Hosts to allow access.
        If None then ``['127.0.0.1', socket.gethostname()]`` is used.

    debug: bool
        Set logging level to ``DEBUG``, default is ``INFO``.

    resources: string
        Filename for resources to be configured.
    """
    if allowed_hosts is None:
        allowed_hosts = ['127.0.0.1', socket.gethostname()]
    with open('hosts.allow', 'w') as out:
        for pattern in allowed_hosts:
            out.write('%s\n' % pattern)
    if sys.platform != 'win32' or HAVE_PYWIN32:
        make_private('hosts.allow')

    server_path = os.path.splitext(os.path.abspath(__file__))[0]+'.py'

    server_out = 'as-%d.out' % port
    server_up = 'as-%d.up' % port
    if os.path.exists(server_up):
        os.remove(server_up)

    # Start process.
    args = ['python', server_path,
            '--address', address, '--port', '%d' % port, '--up', server_up]
    if debug:
        args.append('--debug')
    proc = ShellProc(args, stdout=server_out, stderr=STDOUT)

    # Wait for valid server_up file.
    timeout = 30  # Seconds.
    retry = 0
    while (not os.path.exists(server_up)) or \
          (os.path.getsize(server_up) == 0):
        return_code = proc.poll()
        if return_code:
            error_msg = proc.error_message(return_code)
            raise RuntimeError('Server startup failed: exit code %s (%s)'
                               % (return_code, error_msg))
        retry += 1
        if retry < 10*timeout:
            time.sleep(.1)
        # Hard to cause a startup timeout.
        else:  # pragma no cover
            proc.terminate(timeout)
            raise RuntimeError('Server startup timeout')

    # Read server information.
    with open(server_up, 'r') as inp:
        host = inp.readline().strip()
        port = int(inp.readline().strip())
        pid  = int(inp.readline().strip())

    os.remove(server_up)

    return (proc, port)


def stop_server(proc):
    """
    Stop server process.

    proc: ShellProc
        Process of server to stop.
    """
    return proc.terminate(timeout=10)


def main():  # pragma no cover
    """
    OpenMDAO AnalysisServer process.  Component types to be supported
    are described by ``name.cfg`` files in the current directory or
    subdirectories.  Subdirectory names are used for category names.

    Usage: python server.py [--hosts=filename][--address=address][--port=number][--debug][--no-heartbeat][--up=filename]

    --hosts: string
        Filename for allowed hosts specification. Default ``hosts.allow``.
        The file should contain IPv4 host addresses, IPv4 domain addresses,
        or hostnames, one per line. Blank lines are ignored, and '#' marks the
        start of a comment which continues to the end of the line.

    --address: string
        IPv4 address or hostname for server.
        Default is the host's default IPv4 address.

    --port: int
        Server port (default 1835).
        Note that ports below 1024 typically require special privileges.

    --debug:
        Set logging level to ``DEBUG``, default is ``INFO``.

    --no-heartbeat:
        Do not send heartbeat replies. Simplifies debugging.

    --up: string
        Filename written once server is initialized. Typically used for
        programmatic startup during testing.
    """
    parser = optparse.OptionParser()
    parser.add_option('--hosts', action='store', type='str',
                      default='hosts.allow', help='filename for allowed hosts')
    parser.add_option('--address', action='store', type='str',
                      default='localhost',
                      help='network address to serve.')
    parser.add_option('--port', action='store', type='int',
                      default=DEFAULT_PORT, help='port to listen on')
    parser.add_option('--debug', action='store_true',
                      help='Set logging level to DEBUG')
    parser.add_option('--no-heartbeat', action='store_true',
                      help='Do not send heartbeat replies')
    parser.add_option('--up', action='store', default='',
                      help="if non-null, file written when server is 'up'")

    options, arguments = parser.parse_args()
    if arguments:
        parser.print_help()
        sys.exit(1)

    level = logging.DEBUG if options.debug else logging.INFO
    logging.getLogger().setLevel(level)

    # Get allowed_hosts.
    if os.path.exists(options.hosts):
        try:
            allowed_hosts = read_allowed_hosts(options.hosts)
        except Exception as exc:
            print("Can't read allowed hosts file %r: %s" % (options.hosts, exc))
            sys.exit(1)
        if not allowed_hosts:
            print('No allowed hosts!?.')
            sys.exit(1)
    elif options.address == 'localhost':
        allowed_hosts = ['127.0.0.1']
    else:
        print('Allowed hosts file %r does not exist.' % options.hosts)
        sys.exit(1)

    if not os.path.exists('logs'):
        os.mkdir('logs')

    # Create server.
    host = options.address or socket.gethostname()
    server = Server(host, options.port, allowed_hosts)
    if server.config_errors:
        print('%d component configuration errors detected.'
               % server.config_errors)
        sys.exit(1)

    # Report server address and PID.
    port = server.server_address[1]
    pid = os.getpid()
    msg = 'Server started on %s:%d, pid %d.' % (host, port, pid)
    print(msg)
    logging.info(msg)
    if options.up:
        with open(options.up, 'w') as out:
            out.write('%s\n' % host)
            out.write('%d\n' % port)
            out.write('%d\n' % pid)

    # And away we go...
    signal.signal(signal.SIGINT,  _sigterm_handler)
    signal.signal(signal.SIGTERM, _sigterm_handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    sys.exit(0)


def _sigterm_handler(signum, frame):  #pragma no cover
    """
    Try to go down gracefully.

    signum: int
        Signal received.

    frame: stack frame
        Where signal was received.
    """
    logging.info('sigterm_handler invoked')
    print('sigterm_handler invoked')
    sys.stdout.flush()
    sys.exit(1)


if __name__ == '__main__':  # pragma no cover
    main()
