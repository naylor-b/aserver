
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

import numpy

from analysis_server.server import start_server, stop_server
from analysis_server.client import Client
from analysis_server.arrwrapper import array2str, str2array

STARTDIR = os.getcwd()


class DOETestCase(unittest.TestCase):
    """ Test AnalysisServer emulation for a model that uses MPI to run
    a DOE in parallel.
    """

    def setUp(self):
        logging.info("---------------- Starting test %s" % self.id())

        self.testdir = os.path.dirname(os.path.abspath(__file__))
        self.tempdir = tempfile.mkdtemp(prefix='aserver-')
        if not os.path.isdir(self.tempdir):
            os.mkdir(self.tempdir)

        shutil.copy(os.path.join(self.testdir, 'ASTestProb.py'),
                    os.path.join(self.tempdir))
        shutil.copy(os.path.join(self.testdir, 'TestParDOEProblem.cfg'),
                    os.path.join(self.tempdir))

        os.chdir(self.tempdir)

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

    def test_execute(self):
        try:
            self.server, self.port = start_server(args=['-c', 'TestParDOEProblem.cfg'])
            self.client = Client(port=self.port)
        except:
            os.chdir(STARTDIR)
            raise

        reply = self.client.start('TestParDOEProblem', 'p')

        # set some input cases [indep_var.a, indep_var.b, indep_var.c]
        ncases = 20
        cases = numpy.arange(3.0*ncases).reshape(ncases, 3)
        self.client.set('p.driver.desvar_array', array2str(cases))
        self.client.execute('p')
        results = str2array(self.client.get('p.driver.response_array'))

        for i in range(results.shape[0]):
            for j in range(i, results.shape[0]):
                if i!=j and results[i][0] == results[j][0]:
                    logging.info("*** indices %d and %d match" % (i,j))

        # test to make sure that the set/get array -> str -> array conversion
        # works.
        numpy.testing.assert_array_almost_equal(cases,
                           str2array(self.client.get('p.driver.desvar_array')),
                           decimal=9)

        # we registered our case inputs as responses (first 3 cols of results)
        # so make sure their values haven't changed, and are in the same
        # order as we sent them.
        numpy.testing.assert_array_almost_equal(cases, results[:,:3],
                                                decimal=9)

        mult = numpy.array([2.0, 3.0, 1.5])
        for i in range(cases.shape[0]):
            numpy.testing.assert_array_almost_equal(results[i,3:],
                                                    cases[i]*mult, decimal=9)


if __name__ == '__main__':
    unittest.main()
