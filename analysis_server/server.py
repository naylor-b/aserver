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
import argparse
import platform
import shutil
import signal
import SocketServer
import socket
import threading
import time
import traceback

from xml.sax.saxutils import escape

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
from analysis_server.compwrapper import ComponentWrapper
from analysis_server.monitor import Heartbeat

# from analysis_server.filexfer import filexfer
from analysis_server.proxy import SystemWrapper, SysManager

ERROR_PREFIX = 'ERROR: '

# Our version.
_VERSION = '0.1'

# The implementation level we approximate.
_AS_VERSION = '7.0'
_AS_BUILD = '42968'

# Maps from command string to command handler.
_COMMANDS = {}

_DISABLE_HEARTBEAT = False  # If True, no heartbeat replies are sent.

_DBG_LEN = 10000  # Max length of debug log message.

def get_open_address():
    """Return an open address to use for a multiprocessing manager."""
    if sys.platform == 'win32':
        return arbitrary_address("AF_PIPE")
    else:
        s = socket.socket(socket.AF_INET)
        s.bind(('localhost', 0))
        addr = s.getsockname()
        s.close()
        return addr

#DEFAULT_PORT = 1835
DEFAULT_PORT = get_open_address()[1]

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

    def __init__(self, host='localhost', port=DEFAULT_PORT, allowed_hosts=None,
                 available_systems=(), config_files=()):
        count = 0
        while count < 10:
            try:
                SocketServer.TCPServer.__init__(self, (host, port), _Handler)
            except socket.error as err:
                if 'already in use' in str(err):
                    port += 1
                    count += 1
            else:
                break

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
        #self._read_comp_configurations()
        for f in config_files:
            print("reading config:", f)
            self.read_config(f)

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

    def read_config(self, path):
        """
        Read component configuration file.

        path: string
            Path to config file.

        """
        path = os.path.abspath(path)

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
                for section in config.sections():
                    self._process_config(config, section, path)
            finally:
                os.chdir(orig)

    def _process_config(self, config, section, path):
        """
        Process data read into `config` from `path`.

        config: :class:`ConfigParser.ConfigParser`
            Configuration data.

        section: str
            The section in the config file, which corresponds to
            the data for a particular class.

        path: string
            Path to config file.

        """
        cwd = os.getcwd()

        # Create wrapper configuration object.
        cfg_path = os.path.join(cwd, os.path.basename(path))
        try:
            cfg = _ConfigWrapper(config, section,
                                 time.ctime(os.path.getmtime(cfg_path))
)
        except Exception as exc:
            logging.error(traceback.format_exc())
            raise RuntimeError("Bad configuration in %r: %s" % (cfg_path, exc))

        logging.debug('    registering %s', section)
        with self.components as comps:
            comps[section.replace('.', '/')] = (cfg, cfg.directory)


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
            self._end([name])

    def _get_component(self, typ):
        """
        Return '(cls, cfg)' for `typ`.

        typ: string
            Component path.
        """
        typ = typ.strip('"').lstrip('/')
        name, _, version = typ.partition('?')
        try:
            with self.server.components as comps:
                logging.error("KEYS: %s" % comps.keys())
                return comps[name]
        except KeyError:
            logging.error("KEYERROR: %s" % name)
            pass

        if not '/' in typ:  # Just to match real AnalysisServer.
            typ = '/'+typ
        self._send_error('component <%s> does not match a known component'
                         % typ)
        return None, None

    def _get_proxy(self, name, background=False):
        """
        Return (proxy, worker) for component `name`.
        If `background` and the request is not backgrounded, wait for
        the normal worker to complete before returning the background
        worker. This currently only occurs in the rare case of
        ``execute comp &``.

        name: string
            Name of instance.

        background: bool
            Special background processing flag.
        """
        try:
            wrapper, sync_worker = self._instance_map[name]
        except KeyError:
            self._send_error('no such object: <%s>' % name)
            return (None, None)

        if self._background:
            worker = WorkerPool.get(one_shot=True)
        else:
            worker = sync_worker
            if background:
                worker.join()
                worker = WorkerPool.get(one_shot=True)
        return (wrapper, worker)

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

    def _describe(self, args):
        """
        Describes a published component.

        args: list[string]
            Arguments for the command.
        """
        if len(args) < 1 or len(args) > 2:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'describe,d <category/component> [-xml]')
            return

        comp = self._get_component(args[0])
        if comp is None:
            return

        cfg, directory = comp
        has_version_info = 'false'

        if len(args) > 1 and args[1] == '-xml':
            self._send_reply("""\
<Description>
 <Version>%s</Version>
 <Author>%s</Author>
 <Description>%s</Description>
 <HelpURL>%s</HelpURL>
 <Keywords>%s</Keywords>
 <TimeStamp>%s</TimeStamp>
 <Checksum>%s</Checksum>
 <Requirements>%s</Requirements>
 <hasIcon>%s</hasIcon>
 <HasVersionInfo>%s</HasVersionInfo>
</Description>""" % (cfg.version, escape(cfg.author), escape(cfg.description),
                     cfg.help_url, ' '.join(cfg.keywords), cfg.timestamp,
                     cfg.checksum, escape(' '.join(cfg.requirements)),
                     str(cfg.has_icon).lower(), has_version_info))
        else:
            self._send_reply("""\
Version: %s
Author: %s
hasIcon: %s
Description: %s
Help URL: %s
Keywords: %s
Driver: false
Time Stamp: %s
Requirements: %s
HasVersionInfo: %s
Checksum: %s""" % (cfg.version, cfg.author, str(cfg.has_icon).lower(),
                   cfg.description, cfg.help_url, ' '.join(cfg.keywords),
                   cfg.timestamp, ' '.join(cfg.requirements),
                   has_version_info, cfg.checksum))

    def _end(self, args):
        """
        Unloads a component instance.

        args: list[string]
            Arguments for the command.
        """
        if len(args) != 1:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'end <object>')
            return

        name = args[0]
        try:
            self._logger.info('End %r', name)
            wrapper, worker = self._instance_map.pop(name)
            wrapper.pre_delete()
            WorkerPool.release(worker)
            if wrapper._manager is not None:  # pragma no cover
                wrapper._manager.shutdown()
        except KeyError:
            self._send_error('no such object: <%s>' % name)
        else:
            self._send_reply("%s completed.\nObject %s ended.""" % (name, name))

    def _execute(self, args):
        """
        Runs a component instance.

        args: list[string]
            Arguments for the command.
        """
        if len(args) < 1 or len(args) > 2:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'execute,x <objectName>[&]')
            return

        name = args[0]
        if name.endswith('&'):
            background = True
            name = name[:-1]
        elif len(args) > 1 and args[1] == '&':
            background = True
        else:
            background = False

        proxy, worker = self._get_proxy(name, background)
        if proxy is not None:
            worker.put((proxy.run, (self._req_id,), {}, None))

    def _get(self, args):
        """
        Gets the value of a variable.

        args: list[string]
            Arguments for the command.
        """
        if len(args) != 1:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'get <object.property>')
            return

        name, _, path = args[0].partition('.')
        proxy, worker = self._get_proxy(name)
        if proxy is not None:
            worker.put((proxy.get, (path, self._req_id), {}, None))

    def _get_branches(self, args):
        """
        Handler for ``getBranchesAndTags``.

        args: list[string]
            Arguments for the command.
        """
        if len(args) != 0:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'getBranchesAndTags')
            return

        self._send_reply('')  # Not supported.

    def _get_direct_transfer(self, args):
        """
        Return 'true' if we support direct file transfers.

        args: list[string]
            Arguments for the command.
        """
        if len(args) != 0:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'getDirectTransfer')
            return

        self._send_reply('false')

    # def _get_hierarchy(self, args):
    #     """
    #     Get hierarchy of values in component.
    #
    #     args: list[string]
    #         Arguments for the command.
    #     """
    #     if len(args) < 1 or len(args) > 2:
    #         self._send_error('invalid syntax. Proper syntax:\n'
    #                          'getHierarchy <object> [gzipData]')
    #         return
    #
    #     if len(args) == 2:
    #         if args[1] == 'gzipData':
    #             gzip = True
    #         else:
    #             self._send_error('invalid syntax. Proper syntax:\n'
    #                              'getHierarchy <object> [gzipData]')
    #             return
    #     else:
    #         gzip = False
    #
    #     wrapper, worker = self._get_proxy(args[0])
    #     if wrapper is not None:
    #         worker.put((wrapper.get_hierarchy, (self._req_id, gzip), {}, None))

    def _get_icon(self, args):
        """
        Gets the icon data for the published component.

        args: list[string]
            Arguments for the command.
        """
        if len(args) != 1:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'getIcon <analysisComponent>')
            return

        cfg, _ = self._get_component(args[0])
        if cfg is None:
            return

        raise NotImplementedError('getIcon')

    def _get_license(self, args):
        """
        Retrieves Analysis Server's license agreement.

        args: list[string]
            Arguments for the command.
        """
        if len(args) != 0:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'getLicense')
            return

        self._send_reply('Use at your own risk!')

    def _get_status(self, args):
        """
        Lists the run status of all component instances.

        args: list[string]
            Arguments for the command.
        """
        if len(args) != 0:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'getStatus')
            return

        lines = []
        for name in sorted(self._instance_map.keys()):
            lines.append('%s: ready' % name)
        self._send_reply('\n'.join(lines))

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

    def _heartbeat(self, args):
        """
        Starts up socket heartbeating in order to keep sockets alive through
        firewalls with timeouts.

        args: list[string]
            Arguments for the command.
        """
        if len(args) != 1 or args[0] not in ('start', 'stop'):
            self._send_error('invalid syntax. Proper syntax:\n'
                             'heartbeat,hb [start|stop]')
            return

        if args[0] == 'start':
            if not _DISABLE_HEARTBEAT:
                if self._hb is not None:  # Ensure only one.
                    self._hb.stop()
                self._hb = Heartbeat(self._req_id, self._send_reply)
                self._hb.start()
            self._send_reply('Heartbeating started')
        else:
            if self._hb is not None:
                self._hb.stop()
            self._send_reply('Heartbeating stopped')

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

    def _invoke(self, args):
        """
        Invokes a method on a component instance.

        args: list[string]
            Arguments for the command.
        """
        if len(args) < 1 or len(args) > 2:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'invoke <object.method()> [full]')
            return

        name, _, method = args[0].partition('.')
        method = method[:-2]
        full = len(args) == 2 and args[1] == 'full'
        proxy, worker = self._get_proxy(name)
        if proxy is not None:
            worker.put((proxy.invoke, (method, full, self._req_id), {}, None))

    def _list_array_values(self, args):
        """
        Lists all the values of an array variable.

        args: list[string]
            Arguments for the command.
        """
        if len(args) != 1:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'listArrayValues,lav <object>')
            return

        name, _, path = args[0].partition('.')
        wrapper, worker = self._get_proxy(name)
        if wrapper is not None:
            worker.put((wrapper.list_array_values,
                        (path, self._req_id), {}, None))

    def _list_categories(self, args):
        """
        Lists all the sub-categories available in a category.

        args: list[string]
            Arguments for the command.
        """
        if len(args) > 1:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'listCategories,la [category]')
            return

        if args:
            category = args[0].strip('"').strip('/') + '/' # Ensure trailing '/'
            if category == '/':
                category = ''
        else:
            category = ''

        lines = set()
        with self.server.components as comps:
            for name in sorted(comps.keys()):
                if name.startswith(category):
                    name = name[len(category):]
                    slash = name.find('/')
                    if slash > 0:
                        name = name[:slash]
                        lines.add(name)

        lines = ['%d categories found:' % len(lines)] + list(lines)
        self._send_reply('\n'.join(lines))

    def _list_globals(self, args):
        """
        Lists all component instances in the global namespace.

        args: list[string]
            Arguments for the command.
        """
        if len(args) != 0:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'listGlobals,lg')
            return

        self._send_reply('0 global objects started:')  # Not supported.

    def _list_methods(self, args):
        """
        Lists all methods available on a component instance.

        args: list[string]
            Arguments for the command.
        """
        if len(args) < 1 or len(args) > 2:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'listMethods,lm <object> [full]')
            return

        name = args[0]
        full = len(args) == 2 and args[1] == 'full'
        wrapper, worker = self._get_proxy(name)
        if wrapper is not None:
            worker.put((wrapper.list_methods, (full, self._req_id), {}, None))

    def _list_monitors(self, args):
        """
        Lists all available monitorable items on a component instance.

        args: list[string]
            Arguments for the command.
        """
        if len(args) != 1:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'listMonitors,lo <objectName>')
            return

        name = args[0]
        wrapper, worker = self._get_proxy(name)
        if wrapper is not None:
            worker.put((wrapper.list_monitors, (self._req_id,), {}, None))

    def _list_properties(self, args):
        """
        Lists all available variables and their sub-properties on a component
        instance or sub-variable.

        args: list[string]
            Arguments for the command.
        """
        if len(args) > 1:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'listProperties,list,ls,l [object]')
            return

        if len(args) == 0:  # List started components.
            names = sorted(self._instance_map.keys())
            lines = ['%d objects started:' % len(names)]
            lines.extend(names)
            self._send_reply('\n'.join(lines))
        else:  # List component properties.
            name, _, path = args[0].partition('.')
            wrapper, worker = self._get_proxy(name)
            if wrapper is not None:
                worker.put((wrapper.list_properties,
                            (path, self._req_id), {}, None))

    def _list_values(self, args):
        """
        Lists all available variables and their sub-properties on a component
        instance or sub-variable.

        args: list[string]
            Arguments for the command.
        """
        if len(args) > 1:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'listValues,lv [object]')
            return

        name, _, path = args[0].partition('.')
        wrapper, worker = self._get_proxy(name)
        if wrapper is not None:
            worker.put((wrapper.list_values, (path, self._req_id), {}, None))

    def _list_values_url(self, args):
        """
        Lists all available variables and their sub-properties on a component
        instance or sub-variable. This version supplies a URL for file data
        if DirectFileTransfer is supported.

        args: list[string]
            Arguments for the command.
        """
        if len(args) > 1:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'listValuesURL,lvu [object]')
            return

        name, _, path = args[0].partition('.')
        wrapper, worker = self._get_proxy(name)
        if wrapper is not None:
            worker.put((wrapper.list_values_url,
                        (path, self._req_id), {}, None))

    def _monitor(self, args):
        """
        Starts/stops a monitor on a raw output file or available monitor.

        args: list[string]
            Arguments for the command.
        """
        if len(args) != 2 or args[0] not in ('start', 'stop'):
            self._send_error('invalid syntax. Proper syntax:\n'
                             'monitor start <object.property>, '
                             'monitor stop <id>')
            return

        if args[0] == 'start':
            name, _, path = args[1].partition('.')
            wrapper, worker = self._get_proxy(name)
            if wrapper is not None:
                worker.put((wrapper.start_monitor,
                            (path, self._req_id), {}, None))
                self._monitors[str(self._req_id)] = name
        else:
            try:
                name = self._monitors.pop(args[1])
            except KeyError:
                self._send_error('No monitor registered for %r' % args[1])
            else:
                wrapper, worker = self._get_proxy(name)
                worker.put((wrapper.stop_monitor,
                            (args[1], self._req_id), {}, None))

    def _move(self, args):
        """
        Moves or renames a component instance.

        args: list[string]
            Arguments for the command.
        """
        if len(args) != 2:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'move,rename,mv,rn <from> <to>')
            return

        raise NotImplementedError('move')

    def _ps(self, args):
        """
        Lists all running processes for a component instance.

        args: list[string]
            Arguments for the command.
        """
        if len(args) != 1:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'ps <object>')
            return

        name = args[0].strip('"')
        proxy, worker = self._get_proxy(name)
        if proxy is not None:
            worker.put((proxy.ps, (self._req_id,), {}, None))

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

    def _set(self, args):
        """
        Sets the value of a variable.

        args: list[string]
            Arguments for the command.
        """
        cmd, _, assignment = self._req.partition(' ')
        lhs, _, rhs = assignment.partition('=')
        name, _, path = lhs.strip().partition('.')
        wrapper, worker = self._get_proxy(name)
        if wrapper is not None:
            worker.put((wrapper.set,
                        (path, rhs.strip(), self._req_id), {}, None))

    # def _set_hierarchy(self, args):
    #     """
    #     Set hierarchy of variable values in component.
    #
    #     args: list[string]
    #         Arguments for the command.
    #     """
    #     cmd, _, rest = self._req.partition(' ')
    #     name, _, xml = rest.partition(' ')
    #     wrapper, worker = self._get_proxy(name)
    #     if wrapper is not None:
    #         worker.put((wrapper.set_hierarchy, (xml, self._req_id), {}, None))
    #
    def _set_mode(self, args):
        """
        Sets the connection into 'raw' mode.

        args: list[string]
            Arguments for the command.
        """
        if len(args) != 1 or args[0] != 'raw':
            self._send_error('invalid syntax. Proper syntax:\n'
                             'setMode raw')
            return

        self._raw = True
        self._stream.raw = True

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

        cfg, directory = self._get_component(args[0])
        if cfg is None:
            return

        classname = args[0]
        name = args[1]

        if name in self._instance_map:
            self._send_error('Name already in use: "%s"' % name)
            return

        self._logger.info('Starting %r, directory %r',
                          name, directory)

        # Create component instance.
        with self.server.dir_lock:
            manager = SysManager()
            manager.start()
            proxy = manager.SystemWrapper()
            proxy.init(classname, name, cfg.filename, directory=directory)

        # Create wrapper for component.
        wrapper = ComponentWrapper(name, proxy, cfg, manager, self._send_reply,
                                   self._send_exc)
        self._instance_map[name] = (wrapper, WorkerPool.get())
        self._send_reply('Object %s started.' % name)

    def _versions(self, args):
        """
        Lists the version history of a component.

        args: list[string]
            Arguments for the command.
        """
        if len(args) != 1:
            self._send_error('invalid syntax. Proper syntax:\n'
                             'versions,v category/component')
            return

        cfg, directory = self._get_component(args[0])
        if cfg is None:
            return

        xml = ["<Branch name='HEAD'>"]
        xml.append(" <Version name='%s'>" % cfg.version)
        xml.append("  <author>%s</author>" % escape(cfg.author))
        xml.append("  <date>%s</date>" % cfg.timestamp)
        xml.append("  <description>%s</description>" % escape(cfg.comment))
        xml.append(" </Version>")
        xml.append("</Branch>")
        self._send_reply('\n'.join(xml))


    ########################################
    # Telnet API command to method mapping
    ########################################

    # _COMMANDS['addProxyClients'] = _add_proxy_clients
    _COMMANDS['d'] = _describe
    _COMMANDS['describe'] = _describe
    _COMMANDS['end'] = _end
    _COMMANDS['execute'] = _execute
    _COMMANDS['getBranchesAndTags'] = _get_branches
    _COMMANDS['getDirectTransfer'] = _get_direct_transfer
    _COMMANDS['get'] = _get
    #_COMMANDS['getHierarchy'] = _get_hierarchy
    # _COMMANDS['getIcon2'] = _get_icon2
    _COMMANDS['getIcon'] = _get_icon
    _COMMANDS['getLicense'] = _get_license
    # _COMMANDS['getQueues'] = _get_queues
    _COMMANDS['getStatus'] = _get_status
    _COMMANDS['getSysInfo'] = _get_sys_info
    _COMMANDS['getVersion'] = _get_version
    _COMMANDS['hb'] = _heartbeat
    _COMMANDS['heartbeat'] = _heartbeat
    _COMMANDS['help'] = _help
    _COMMANDS['h'] = _help
    _COMMANDS['invoke'] = _invoke
    _COMMANDS['la'] = _list_categories
    _COMMANDS['lav'] = _list_array_values
    _COMMANDS['lc'] = _list_components
    _COMMANDS['lg'] = _list_globals
    _COMMANDS['listArrayValues'] = _list_array_values
    _COMMANDS['listCategories'] = _list_categories
    _COMMANDS['listComponents'] = _list_components
    _COMMANDS['listGlobals'] = _list_globals
    _COMMANDS['listMethods'] = _list_methods
    _COMMANDS['lm'] = _list_methods
    _COMMANDS['listMonitors'] = _list_monitors
    _COMMANDS['lo'] = _list_monitors
    _COMMANDS['l'] = _list_properties
    _COMMANDS['list'] = _list_properties
    _COMMANDS['ls'] = _list_properties
    _COMMANDS['listProperties'] = _list_properties
    _COMMANDS['listValues'] = _list_values
    _COMMANDS['lv'] = _list_values
    _COMMANDS['listValuesURL'] = _list_values_url
    _COMMANDS['lvu'] = _list_values_url
    _COMMANDS['monitor'] = _monitor
    _COMMANDS['move'] = _move
    _COMMANDS['mv'] = _move
    _COMMANDS['rename'] = _move
    _COMMANDS['rn'] = _move
    _COMMANDS['ps'] = _ps
    _COMMANDS['quit'] = _quit
    # _COMMANDS['setDictionary'] = _set_dictionary
    #_COMMANDS['setHierarchy'] = _set_hierarchy
    _COMMANDS['setMode'] = _set_mode
    # _COMMANDS['setRunQueue'] = _set_run_queue
    # _COMMANDS['setServerAuthInfo'] = _set_auth_info
    _COMMANDS['set'] = _set
    _COMMANDS['start'] = _start
    _COMMANDS['versions'] = _versions
    _COMMANDS['v'] = _versions
    _COMMANDS['x'] = _execute







def start_server(address='localhost', port=None, allowed_hosts=None,
                 debug=False, args=()):
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

    args: iter of str
        Other command line args to pass to server.
    """
    if port is None:
        port = get_open_address()[1]

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
    args = [sys.executable, server_path, '-d',
            '--address', address, '--port', '%d' % port, '--up', server_up] + args
    if debug:
        args.append('--debug')

    #print("starting ShellProc:",args)
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

    --up: string
        Filename written once server is initialized. Typically used for
        programmatic startup during testing.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('--hosts', type=str, default='hosts.allow',
                        help='filename for allowed hosts')
    parser.add_argument('-a', '--address', type=str, default='localhost',
                        help='network address to serve.')
    parser.add_argument('-p', '--port', type=int,
                        default=DEFAULT_PORT, help='port to listen on')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Set logging level to DEBUG')
    parser.add_argument('--no-heartbeat', action='store_true',
                        help='Do not send heartbeat replies')
    parser.add_argument('--up', default='',
                       help="if non-null, file written when server is 'up'")

    parser.add_argument('-c', '--config', type=str, nargs="*", default=[],
                        help='config file(s) containing info about systems that '
                        'will be available in this server.')
    parser.add_argument('-s', '--system', type=str, nargs="*", default=[],
                        help='classnames of importable systems that will be '
                        'available in this server.')

    options = parser.parse_args()

    level = logging.DEBUG if options.debug else logging.INFO
    logging.getLogger().setLevel(level)

    global _DISABLE_HEARTBEAT
    _DISABLE_HEARTBEAT = options.no_heartbeat

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
    server = Server(host, options.port, allowed_hosts,
                    config_files=options.config,
                    available_systems=options.system)
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
