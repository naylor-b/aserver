
from __future__ import print_function

import os
import sys
import unittest
import tempfile
import shutil
import platform
import getpass

from openmdao.util.file_util import build_directory

from analysis_server.server import start_server, stop_server
from analysis_server.client import Client

STARTDIR = os.getcwd()

class TestCase(unittest.TestCase):
    """ Test AnalysisServer emulation. """

    def setUp(self):
        self.testdir = os.path.dirname(os.path.abspath(__file__))
        self.tempdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tempdir, 'd1'))
        os.makedirs(os.path.join(self.tempdir, 'd2/d3'))

        shutil.copyfile(os.path.join(self.testdir, 'ASTestComp.py'),
                       os.path.join(self.tempdir, 'd2', 'd3', 'ASTestComp.py'))
        shutil.copyfile(os.path.join(self.testdir, 'TestComponent.cfg'),
                       os.path.join(self.tempdir, 'd2', 'd3', 'TestComponent.cfg'))

        os.chdir(self.tempdir)

        self.server, self.port = start_server()
        self.client = Client(port=self.port)

    def tearDown(self):
        try:
            self.client.quit()
            stop_server(self.server)
        finally:
            os.chdir(STARTDIR)
            if not os.environ.get('OPENMDAO_KEEPDIRS'):
                try:
                    shutil.rmtree(self.tempdir)
                except OSError:
                    pass

    def send_recv(self, cmd, raw=False, count=None):
        """ Set request, process, return replies. """
        self.client.set_command(cmd, raw)
        self.handler.handle()
        replies = self.client.get_replies()
        if count is not None:
            retries = 0
            while len(replies) < count:
                retries += 1
                if retries >= 100:
                    break
                time.sleep(0.1)
            replies = self.client.get_replies()
        return replies

    def compare(self, reply, expected):
        reply_lines = reply.split('\n')
        expected_lines = expected.split('\n')
        for i, reply_line in enumerate(reply_lines):
            if i >= len(expected_lines):
                self.fail('%d reply lines, %d expected lines'
                      % (len(reply_lines), len(expected_lines)))
            expected_line = expected_lines[i]
            if reply_line.startswith('classURL'): # installation-specific
                if not expected_line.startswith('classURL'):
                    self.fail('Line %d: %r vs. %r'
                               % (i+1, reply_line, expected_line))
            else:
                if reply_line != expected_line:
                    self.fail('Line %d: %r vs. %r'
                               % (i+1, reply_line, expected_line))
        if len(reply_lines) != len(expected_lines):
            self.fail('%d reply lines, %d expected lines'
                      % (len(reply_lines), len(expected_lines)))

    def test_get_sys_info(self):
        expected = {
            'version': '7.0',
            'build': '42968',
            'num clients': '1',
            'num components': '0',
            'os name': platform.system(),
            'os arch': platform.processor(),
            'os version': platform.release(),
            'python version': platform.python_version(),
            'user name': getpass.getuser(),
        }
        result = self.client.get_sys_info()
        self.assertEqual(result, expected)

    def test_help(self):
        expected = [
            'Available Commands:',
            'listComponents,lc [category]',
            'listCategories,la [category]',
            'describe,d <category/component> [-xml]',
            'setServerAuthInfo <serverURL> <username> <password> (NOT IMPLEMENTED)',
            'start <category/component> <instanceName> [connector] [queue]',
            'end <object>',
            'execute,x <objectName>',
            'listProperties,list,ls,l [object]',
            'listGlobals,lg',
            'listValues,lv <object>',
            'listArrayValues,lav <object> (NOT IMPLEMENTED)',
            'get <object.property>',
            'set <object.property> = <value>',
            'move,rename,mv,rn <from> <to> (NOT IMPLEMENTED)',
            'getIcon <analysisComponent> (NOT IMPLEMENTED)',
            'getIcon2 <analysisComponent> (NOT IMPLEMENTED)',
            'getVersion',
            'getLicense',
            'getStatus',
            'help,h',
            'quit',
            'getSysInfo',
            'invoke <object.method()> [full]',
            'listMethods,lm <object> [full]',
            'addProxyClients <clientHost1>,<clientHost2>',
            'monitor start <object.property>, monitor stop <id>',
            'versions,v category/component',
            'ps <object>',
            'listMonitors,lo <objectName>',
            'heartbeat,hb [start|stop]',
            'listValuesURL,lvu <object>',
            'getDirectTransfer',
            'getByUrl <object.property> <url> (NOT IMPLEMENTED)',
            'setByUrl <object.property> = <url> (NOT IMPLEMENTED)',
            'setDictionary <xml dictionary string> (xml accepted, but not used)',
            'getHierarchy <object.property>',
            'setHierarchy <object.property> <xml>',
            'deleteRunShare <key> (NOT IMPLEMENTED)',
            'getBranchesAndTags (NOT IMPLEMENTED)',
            'getQueues <category/component> [full] (NOT IMPLEMENTED)',
            'setRunQueue <object> <connector> <queue> (NOT IMPLEMENTED)',
        ]
        result = self.client.help()
        self.assertEqual(result, expected)

if __name__ == '__main__':
    unittest.main()
