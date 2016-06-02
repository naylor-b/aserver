
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
import logging
import fnmatch

from analysis_server.server import start_server, stop_server
from analysis_server.client import Client

STARTDIR = os.getcwd()
OPENMDAO_TMPDIR = os.environ.get('OPENMDAO_TMPDIR')
KEEPDIRS = os.environ.get('OPENMDAO_KEEPDIRS', False)

class TestCase(unittest.TestCase):
    """ Test AnalysisServer emulation. """

    def setUp(self):
        logging.info("---------------- Starting test %s" % self.id())

        self.testdir = os.path.dirname(os.path.abspath(__file__))
        if OPENMDAO_TMPDIR:
            self.tempdir = os.path.join(OPENMDAO_TMPDIR, self.id().split('.')[-1])
        else:
            self.tempdir = tempfile.mkdtemp(prefix=self.id().split('.')[-1]+'_')

        os.makedirs(os.path.join(self.tempdir, 'd1'))
        os.makedirs(os.path.join(self.tempdir, 'd2/d3'))

        shutil.copy(os.path.join(self.testdir, 'ASTestComp.py'),
                    os.path.join(self.tempdir, 'd2', 'd3'))
        shutil.copy(os.path.join(self.testdir, 'TestCompProblem.cfg'),
                    os.path.join(self.tempdir, 'd2', 'd3'))

        os.chdir(self.tempdir)

        try:
            self.server, self.port = start_server(args=['-c', self.tempdir])
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
            if not KEEPDIRS and not OPENMDAO_TMPDIR:
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
        files = glob.glob('d2/d3/TestCompProblem.cfg')
        if len(files) < 1:
            self.fail("Couldn't find TestCompProblem.cfg file.")

        expected['Time Stamp'] = \
            time.ctime(os.path.getmtime(files[0]))

        result = self.client.describe('d2/d3/TestCompProblem')

        for key, val in expected.items():
            try:
                self.assertEqual("%s: %s" % (key,val), "%s: %s" % (key,result[key]))
            except KeyError:
                self.fail("Key '%s' not found in results." % key)

    def test_end(self):
        self.client.start('d2/d3/TestCompProblem', 'comp')
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
        self.client.start('d2/d3/TestCompProblem', 'comp')
        self.client.set('comp.in_file', 'Hello world!')
        self.client.execute('comp')
        self.client.execute('comp', background=True)

    def test_get(self):
        self.client.start('d2/d3/TestCompProblem', 'comp')
        result = self.client.get('comp.x')
        self.assertEqual(result, '2')

    def test_get_branches(self):
        result = self.client.get_branches_and_tags()
        self.assertEqual(result, '')

    def test_get_direct(self):
        result = self.client.get_direct_transfer()
        self.assertFalse(result)

    # def test_get_hierarchy(self):
    #     self.client.start('d2/d3/TestCompProblem', 'comp')
    #     result = self.client.get_hierarchy('comp')
    #

    def test_get_icon(self):
        try:
            self.client.get_icon('d2/d3/TestCompProblem')
        except Exception as err:
            self.assertTrue('NotImplementedError' in str(err))
            self.assertTrue('getIcon' in str(err))
        else:
            self.fail("Exception expected")

    def test_get_license(self):
        result = self.client.get_license()
        self.assertEqual(result, 'Use at your own risk!')

    def test_get_status(self):
        expected = {'comp': 'ready'}
        self.client.start('d2/d3/TestCompProblem', 'comp')
        result = self.client.get_status()
        self.assertEqual(result, expected)

    def test_get_sys_info(self):
        expected = {
            'version': '7.0',
            'build': '42968',
            'num clients': '1',
            'num components': '1',
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

    def test_heartbeat(self):
        self.client.heartbeat(True)
        self.client.heartbeat(False)

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
            #'getHierarchy <object.property>',
            #'setHierarchy <object.property> <xml>',
            'deleteRunShare <key> (NOT IMPLEMENTED)',
            'getBranchesAndTags (NOT IMPLEMENTED)',
            'getQueues <category/component> [full] (NOT IMPLEMENTED)',
            'setRunQueue <object> <connector> <queue> (NOT IMPLEMENTED)',
        ]
        result = self.client.help()
        self.assertEqual(result, expected)

    def test_invoke(self):
        self.client.start('d2/d3/TestCompProblem', 'prob')
        result = self.client.invoke('prob.comp.reinitialize')
        self.assertEqual(result, '')
        result = self.client.invoke('prob.comp.float_method')
        self.assertEqual(result, '5')
        result = self.client.invoke('prob.comp.null_method')
        self.assertEqual(result, '')
        result = self.client.invoke('prob.comp.str_method')
        self.assertEqual(result,
                         'current state: x 2.0, y 3.0, z 0.0, exe_count 0')

    def test_list_array_values(self):
        self.client.start('d2/d3/TestCompProblem', 'comp')
        try:
            self.client.list_array_values('comp')
        except Exception as err:
            self.assertTrue('NotImplementedError' in str(err))
            self.assertTrue('listArrayValues' in str(err))

    def test_list_categories(self):
        result = self.client.list_categories('/')
        self.assertEqual(result, ['d2'])
        result = self.client.list_categories('/d2')
        self.assertEqual(result, ['d3'])

    def test_list_components(self):
        result = self.client.list_components()

        self.assertEqual(sorted(result),
                         ['d2/d3/TestCompProblem'])

    def test_list_globals(self):
        result = self.client.list_globals()
        self.assertEqual(result, [])

    def test_list_methods(self):
        self.client.start('d2/d3/TestCompProblem', 'comp')
        result = self.client.list_methods('comp')
        #logging.info("RESULT: %s" % result)
        self.assertTrue("comp.float_method" in result, "can't find float_method in 'comp'")
        self.assertTrue("comp.str_method" in result, "can't find str_method in 'comp'")
        self.assertTrue("comp.int_method" in result, "can't find int_method in 'comp'")

        result = self.client.list_methods('comp', full=True)
        #logging.info("RESULT: %s" % result)
        self.assertTrue(("comp.float_method", "TestCompProblem/comp.float_method") in result, "can't find float_method in 'comp'")
        self.assertTrue(("comp.str_method", "TestCompProblem/comp.str_method") in result, "can't find str_method in 'comp'")
        self.assertTrue(("comp.int_method", "TestCompProblem/comp.int_method") in result, "can't find int_method in 'comp'")

    def test_list_monitors(self):
        self.client.start('d2/d3/TestCompProblem', 'comp')
        result = sorted(self.client.list_monitors('comp'))
        self.assertEqual('hosts.allow', result[1])
        self.assertTrue(fnmatch.fnmatch(result[0], 'as-*.out'))

    def test_list_properties(self):
        self.client.start('d2/d3/TestCompProblem', 'comp')
        result = self.client.list_properties()
        self.assertEqual(result, ['comp'])

        expected = [
             ('exe_count', 'PHXLong', 'out'),
             ('exe_dir', 'PHXString', 'out'),
             ('in_file', 'PHXRawFile', 'in'),
             ('obj_input.sobobj.sob', 'PHXBoolean', 'in'),
             ('obj_input.sobobj.sof', 'PHXDouble', 'in'),
             ('obj_input.sobobj.soi', 'PHXLong', 'in'),
             ('obj_input.sobobj.sos', 'PHXString', 'in'),
             ('obj_input.tob', 'PHXBoolean', 'in'),
             ('obj_input.tof', 'PHXDouble', 'in'),
             ('obj_input.tof1d', 'double[9]', 'in'),
             ('obj_input.tof2d', 'double[2][4]', 'in'),
             ('obj_input.tof3d', 'double[2][3][3]', 'in'),
             ('obj_input.tofe', 'PHXDouble', 'in'),
             ('obj_input.toflst', 'double[0]', 'in'),
             ('obj_input.toi', 'PHXLong', 'in'),
             ('obj_input.toi1d', 'long[9]', 'in'),
             ('obj_input.toie', 'PHXLong', 'in'),
             ('obj_input.toilst', 'long[0]', 'in'),
             ('obj_input.tos', 'PHXString', 'in'),
             ('obj_input.tos1d', 'java.lang.String[3]', 'in'),
             ('obj_input.tose', 'PHXString', 'in'),
             ('obj_output.sobobj.sob', 'PHXBoolean', 'out'),
             ('obj_output.sobobj.sof', 'PHXDouble', 'out'),
             ('obj_output.sobobj.soi', 'PHXLong', 'out'),
             ('obj_output.sobobj.sos', 'PHXString', 'out'),
             ('obj_output.tob', 'PHXBoolean', 'out'),
             ('obj_output.tof', 'PHXDouble', 'out'),
             ('obj_output.tof1d', 'double[9]', 'out'),
             ('obj_output.tof2d', 'double[2][4]', 'out'),
             ('obj_output.tof3d', 'double[2][3][3]', 'out'),
             ('obj_output.tofe', 'PHXDouble', 'out'),
             ('obj_output.toflst', 'double[0]', 'out'),
             ('obj_output.toi', 'PHXLong', 'out'),
             ('obj_output.toi1d', 'long[9]', 'out'),
             ('obj_output.toie', 'PHXLong', 'out'),
             ('obj_output.toilst', 'long[0]', 'out'),
             ('obj_output.tos', 'PHXString', 'out'),
             ('obj_output.tos1d', 'java.lang.String[3]', 'out'),
             ('obj_output.tose', 'PHXString', 'out'),
             ('out_file', 'PHXRawFile', 'out'),
             ('sub_group.b', 'PHXBoolean', 'in'),
             ('sub_group.f', 'PHXDouble', 'in'),
             ('sub_group.f1d', 'double[9]', 'in'),
             ('sub_group.f2d', 'double[2][4]', 'in'),
             ('sub_group.f3d', 'double[2][3][3]', 'in'),
             ('sub_group.fe', 'PHXDouble', 'in'),
             ('sub_group.flst', 'double[0]', 'in'),
             ('sub_group.i', 'PHXLong', 'in'),
             ('sub_group.i1d', 'long[9]', 'in'),
             ('sub_group.ie', 'PHXLong', 'in'),
             ('sub_group.ilst', 'long[0]', 'in'),
             ('sub_group.s', 'PHXString', 'in'),
             ('sub_group.s1d', 'java.lang.String[3]', 'in'),
             ('sub_group.se', 'PHXString', 'in'),
             ('x', 'PHXDouble', 'in'),
             ('y', 'PHXDouble', 'in'),
             ('z', 'PHXDouble', 'out')
        ]
        result = self.client.list_properties('comp')
        self.assertEqual(result, expected)

    def test_monitor(self):
        self.client.start('d2/d3/TestCompProblem', 'comp')
        result, monitor_id = self.client.start_monitor('comp.d2/d3/TestCompProblem.cfg')
        expected = """\
[AnalysisServer]
version: 0.2
filename: ASTestComp.py
comment: Initial version.
author: anonymous  ( & < > )
description: Component for testing AnalysisServer functionality.
    An additional description line.  ( & < > )
in_vars: in_* x y obj_input:* sub_group:*
out_vars: out_* z exe_* obj_output:*
methods: comp.reinitialize
   comp.float_method
   comp.null_method
   comp.str_method
   comp.int_method
"""
        self.assertEqual(result[:len(expected)], expected)

        self.client.stop_monitor(monitor_id)

#     def test_set_hierarchy(self):
#         # Grab value of obj_input (big XML string).
#         reply = self.client.start('d2/d3/TestCompProblem', 'comp')
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
            self.assertTrue('NotImplementedError' in str(err))
            self.assertTrue('move' in str(err))

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
        self.client.start('d2/d3/TestCompProblem', 'comp')
        process_info = self.client.ps('comp')
        self.assertEqual(process_info, expected)

    def test_set(self):
        self.client.start('d2/d3/TestCompProblem', 'comp')
        self.client.set('comp.x', '42')
        self.assertEqual(self.client.get('comp.x'), '42')

    def test_set_mode(self):
        self.client.set_mode_raw()
        result = self.client.list_components()
        self.assertEqual(result, ['d2/d3/TestCompProblem'])

        self.assertTrue(self.client._stream.raw)

        try:
            self.client._stream.raw = False
        except Exception as err:
            self.assertEqual("Can only transition from 'cooked' to 'raw'",
                             str(err))
        else:
            self.fail("Exception expected")

    def test_start(self):
        reply = self.client.start('d2/d3/TestCompProblem', 'comp')
        self.assertEqual("Object comp started.", reply)

    def test_versions(self):

        reply = self.client.versions('d2/d3/TestCompProblem')
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
