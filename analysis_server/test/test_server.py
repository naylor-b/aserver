
from __future__ import print_function

import os
import sys
import unittest
import tempfile
import shutil
import platform
import getpass
import time
import glob

from analysis_server.server import start_server, stop_server
from analysis_server.client import Client

STARTDIR = os.getcwd()

class TestCase(unittest.TestCase):
    """ Test AnalysisServer emulation. """

    def setUp(self):
        self.testdir = os.path.dirname(os.path.abspath(__file__))
        self.tempdir = tempfile.mkdtemp(prefix='aserver-')

        os.makedirs(os.path.join(self.tempdir, 'd1'))
        os.makedirs(os.path.join(self.tempdir, 'd2/d3'))

        shutil.copy(os.path.join(self.testdir, 'ASTestComp.py'),
                    os.path.join(self.tempdir, 'd2', 'd3'))
        shutil.copy(os.path.join(self.testdir, 'TestComponents.cfg'),
                    os.path.join(self.tempdir, 'd2', 'd3'))

        os.chdir(self.tempdir)

        try:
            self.server, self.port = start_server(args=['-c', 'd2/d3/TestComponents.cfg'])
            self.client = Client(port=self.port)
        except:
            os.chdir(STARTDIR)
            raise

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

    def test_describe(self):
        expected = {
            'Version': '0.2',
            'Author': 'anonymous  ( & < > )',
            'hasIcon': 'false',
            'Description': 'Component for testing AnalysisServer functionality.\nAn additional description line.  ( & < > )',
            'Help URL': '',
            'Keywords': '',
            'Driver': 'false',
            'Time Stamp': '',
            'Requirements': '',
            'HasVersionInfo': 'false',
            'Checksum': '0',
        }
        files = glob.glob('d2/d3/TestComponents.cfg')
        if len(files) < 1:
            self.fail("Couldn't find TestComponents.cfg file.")

        expected['Time Stamp'] = \
            time.ctime(os.path.getmtime(files[0]))

        result = self.client.describe('TestComponent')

        for key, val in expected.items():
            try:
                self.assertEqual("%s: %s" % (key,val), "%s: %s" % (key,result[key]))
            except KeyError:
                self.fail("Key '%s' not found in results." % key)

    def test_end(self):
        self.client.start('TestComponent', 'comp')
        reply = self.client.end('comp')
        self.assertEqual(reply, 'comp completed.\nObject comp ended.')

        try:
            self.client.end('froboz')
        except Exception as err:
            self.assertEqual(str(err),
                         'no such object: <froboz>')
        else:
            self.fail("Exception expected")

        try:
            self.client._send_recv('end')
        except Exception as err:
            self.assertEqual(str(err),
                             'invalid syntax. Proper syntax:\n'
                             'end <object>')
        else:
            self.fail("Exception expected")

    def test_execute(self):
        self.client.start('TestComponent', 'comp')
        self.client.set('comp.in_file', 'Hello world!')
        self.client.execute('comp')
        self.client.execute('comp', background=True)

    def test_get(self):
        self.client.start('TestComponent', 'comp')
        result = self.client.get('comp.x')
        self.assertEqual(result, '2')

    def test_get_branches(self):
        result = self.client.get_branches_and_tags()
        self.assertEqual(result, '')

    def test_get_direct(self):
        result = self.client.get_direct_transfer()
        self.assertFalse(result)

    # def test_get_hierarchy(self):
    #     self.client.start('TestComponent', 'comp')
    #     result = self.client.get_hierarchy('comp')
    #
    def test_get_status(self):
        expected = {'comp': 'ready'}
        self.client.start('TestComponent', 'comp')
        result = self.client.get_status()
        self.assertEqual(result, expected)

    def test_get_sys_info(self):
        expected = {
            'version': '7.0',
            'build': '42968',
            'num clients': '1',
            'num components': '2',
            'os name': platform.system(),
            'os arch': platform.processor(),
            'os version': platform.release(),
            'python version': platform.python_version(),
            'user name': getpass.getuser(),
        }
        result = self.client.get_sys_info()
        self.assertEqual(result, expected)

    def test_get_version(self):
        expected = """\
OpenMDAO Analysis Server 0.1
Use at your own risk!
Attempting to support Phoenix Integration, Inc.
version: 7.0, build: 42968"""
        result = self.client.get_version()
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

    def test_list_components(self):
        result = self.client.list_components()


        self.assertEqual(sorted(result),
                         ['TestComponent',
                          'openmdao.components.exec_comp.ExecComp'])

#     def test_set_hierarchy(self):
#         # Grab value of obj_input (big XML string).
#         reply = self.client.start('TestComponent', 'comp')
#         reply = self.client.get('comp.obj_input')
#         obj_input = reply[:-3]
#
#         xml = """\
# <?xml version='1.0' encoding='utf-8'?>
# <Group>
# <Variable name="in_file">test setHierarchy</Variable>
# <Variable name="obj_input">%s</Variable>
# <Variable name="sub_group.b">false</Variable>
# <Variable name="sub_group.f">-0.5</Variable>
# <Variable name="sub_group.f1d">5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9</Variable>
# <Variable name="sub_group.f2d">bounds[2, 4] {.1, .2, .3, .4, .5, .6, .7, .8}</Variable>
# <Variable name="sub_group.f3d">bounds[2, 3, 3] {0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9</Variable>
# <Variable name="sub_group.fe">3.14159</Variable>
# <Variable name="sub_group.i">-7</Variable>
# <Variable name="sub_group.i1d">-1, -2, -3, -4, -5, -6, -7, -8, -9</Variable>
# <Variable name="sub_group.ie">9</Variable>
# <Variable name="sub_group.s">Cruel world :-(</Variable>
# <Variable name="sub_group.se">hot</Variable>
# <Variable name="x">6</Variable>
# <Variable name="y">7</Variable>
# </Group>""" % escape(obj_input)
#
#         self.client.set_mode_raw()
#         reply = self.client.set_hierarchy('comp', xml)
#         expected = 'values set'
#         self.assertEqual(reply, '2\r\nformat: string\r\n%d\r\n%s'
#                                       % (len(expected), expected))
    def test_move(self):
        try:
            self.client.move('from', 'to')
        except Exception as err:
            self.assertEqual(str(err), "Exception: NotImplementedError('move',)")
        else:
            self.fail("Exception expected")

    def test_ps(self):
        expected = [{
            'PID': 0,
            'ParentPID': 0,
            'PercentCPU': 0.,
            'Memory': 0,
            'Time': 0.,
            'WallTime': 0.,
            'Command': os.path.basename(sys.executable),
        }]
        self.client.start('TestComponent', 'comp')
        process_info = self.client.ps('comp')
        self.assertEqual(process_info, expected)

    def test_set(self):
        self.client.start('TestComponent', 'comp')
        self.client.set('comp.x', '42')
        self.assertEqual(self.client.get('comp.x'), '42')

    def test_set_mode(self):
        self.client.set_mode_raw()
        result = self.client.list_components()
        self.assertEqual(result, ['TestComponent',
                                  'openmdao.components.exec_comp.ExecComp'])

        self.assertTrue(self.client._stream.raw)

        try:
            self.client._stream.raw = False
        except Exception as err:
            self.assertEqual("Can only transition from 'cooked' to 'raw'",
                             str(err))
        else:
            self.fail("Exception expected")

    def test_start(self):
        reply = self.client.start('TestComponent', 'comp')
        self.assertEqual("Object comp started.", reply)

    def test_versions(self):

        reply = self.client.versions('TestComponent')
        self.assertEqual(reply, ['0.2'])

        try:
            reply = self.client._send_recv('versions')
        except Exception as err:
            self.assertEqual(str(err),
                            'invalid syntax. Proper syntax:\n'
                            'versions,v category/component')
        else:
            self.fail("Exception expected")

        try:
            reply = self.client._send_recv('versions NoSuchComp')
        except Exception as err:
            self.assertEqual(str(err),
                  "component </NoSuchComp> does not match a known component")
        else:
            self.fail("Exception expected")

if __name__ == '__main__':
    unittest.main()
