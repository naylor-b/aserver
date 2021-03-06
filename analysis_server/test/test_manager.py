from __future__ import print_function

import os
import sys
import unittest

from openmdao.components.exec_comp import ExecComp

from analysis_server.proxy import ProblemProxy, SysManager

from analysis_server.server import start_server, stop_server
from analysis_server.client import Client


class ManagerTestCase(unittest.TestCase):

    def test_manager(self):
        manager = SysManager()
        manager.start()

        sw = manager.ProblemProxy()
        sw.init('analysis_server.test.ASTestComp.ExecCompProblem', 'comp', args=['y=2.0*x'])

        expected = list(x for x in ProblemProxy.__dict__ if not x.startswith('_'))
        self.assertEqual(len(expected), len(sw._exposed_))
        for e in expected:
            self.assertTrue(e in sw._exposed_, "%s was not found in the proxy" % e)

        self.assertEqual(sw.get('y'), 0.0)
        sw.set('x', 3.0)
        sw.run()
        self.assertEqual(sw.get('y'), 6.0)


if __name__ == '__main__':
    unittest.main()
