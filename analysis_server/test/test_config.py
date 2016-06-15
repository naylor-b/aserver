
from __future__ import print_function

import os
import sys
import unittest
import ConfigParser

from analysis_server.cfg_wrapper import _ConfigWrapper, _CONFIG_DEFAULTS

STARTDIR = os.getcwd()
TESTDIR =  os.path.dirname(os.path.abspath(__file__))

class TestCase(unittest.TestCase):
    """ Test AnalysisServer emulation. """


    def test_read_config(self):
        path = os.path.join(TESTDIR, "TestCompProblem.cfg")
        config = ConfigParser.SafeConfigParser(_CONFIG_DEFAULTS)
        config.optionxform = str  # Preserve case.
        files = config.read(path)
        if not files:
            raise RuntimeError("Can't read %r" % path)

        sections = list(config.sections())
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0], 'AnalysisServer')



if __name__ == '__main__':
    unittest.main()
