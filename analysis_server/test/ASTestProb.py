
from openmdao.core.problem import Problem
from openmdao.core.group import Group
from openmdao.components.exec_comp import ExecComp
from openmdao.components.indep_var_comp import IndepVarComp
from openmdao.drivers.array_case_driver import ArrayCaseDriver

import numpy


class TestParDOEProblem(Problem):
    def __init__(self, load_balance=False):
        super(TestParDOEProblem, self).__init__()
        self.driver = driver = ArrayCaseDriver(num_par_doe=4,
                                               load_balance=load_balance)

        root = self.root = Group()
        root.add('indep_var', IndepVarComp([('a', 0.5),('b',0.75),('c',0.9)]))
        root.add('comp', ExecComp(["x=a*2.0","y=b*3.0","z=c*1.5"]))

        root.connect('indep_var.a', 'comp.a')
        root.connect('indep_var.b', 'comp.b')
        root.connect('indep_var.c', 'comp.c')

        ncases = 30
        driver.desvar_array = numpy.arange(ncases*3,
                                           dtype=float).reshape(ncases, 3)

        driver.add_desvar('indep_var.a')
        driver.add_desvar('indep_var.b')
        driver.add_desvar('indep_var.c')

        driver.add_response(driver._desvars)
        driver.add_response(['comp.x', 'comp.y', 'comp.z'])



class TestParDOEProblemLB(TestParDOEProblem):
    """Load balanced version of TestParDOEProblem"""
    def __init__(self):
        super(TestParDOEProblemLB, self).__init__(load_balance=True)
