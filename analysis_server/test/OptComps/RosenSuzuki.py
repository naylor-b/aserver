
import numpy

from openmdao.api import Component, ExternalCode

from analysis_server import ASMixin


class RosenSuzuki(Component, ASMixin):
    """ From the CONMIN User's Manual:
    EXAMPLE 1 - CONSTRAINED ROSEN-SUZUKI FUNCTION. NO GRADIENT INFORMATION.

         MINIMIZE OBJ = X(1)**2 - 5*X(1) + X(2)**2 - 5*X(2) +
                        2*X(3)**2 - 21*X(3) + X(4)**2 + 7*X(4) + 50

         Subject to:

              G(1) = X(1)**2 + X(1) + X(2)**2 - X(2) +
                     X(3)**2 + X(3) + X(4)**2 - X(4) - 8   .LE.0

              G(2) = X(1)**2 - X(1) + 2*X(2)**2 + X(3)**2 +
                     2*X(4)**2 - X(4) - 10                  .LE.0

              G(3) = 2*X(1)**2 + 2*X(1) + X(2)**2 - X(2) +
                     X(3)**2 - X(4) - 5                     .LE.0

    This problem is solved beginning with an initial X-vector of
         X = (1.0, 1.0, 1.0, 1.0)
    The optimum design is known to be
         OBJ = 6.000
    and the corresponding X-vector is
         X = (0.0, 1.0, 2.0, -1.0)
    """

    def __init__(self):
        self.add_param('x', numpy.array([1., 1., 1., 1.]), low=-10., high=99.)
        self.add_output('g', numpy.array([1., 1., 1.]))
        self.add_output('f', 0.0)

    def solve_nonlinear(self, params, unknowns, resids):
        """calculate the new objective and constraint values"""
        x = params['x']

        unknowns['f'] = (x[0]**2 - 5.*x[0] + x[1]**2 - 5.*x[1] +
                        2.*x[2]**2 - 21.*x[2] + x[3]**2 + 7.*x[3] + 50)

        g = numpy.empty(3, dtype=float)
        g[0] = (x[0]**2 + x[0] + x[1]**2 - x[1] +
                x[2]**2 + x[2] + x[3]**2 - x[3] - 8)
        g[1] = (x[0]**2 - x[0] + 2*x[1]**2 + x[2]**2 +
                2*x[3]**2 - x[3] - 10)
        g[2] = (2*x[0]**2 + 2*x[0] + x[1]**2 - x[1] +
                x[2]**2 - x[3] - 5)

        unknowns['g'] = g

    def linearize(self, params, unknowns, resids):
        """Analytical derivatives"""
        J = {}

        x = params['x']

        J[('f', 'x')] = np.array([
            [2*x[0]-5, 2*x[1]-5, 4*x[2]-21, 2*x[3]+7]
        ])

        J[('g', 'x')] = np.array([
            [2*x[0]+1, 2*x[1]-1, 2*x[2]+1, 2*x[3]-1],
            [2*x[0]-1, 4*x[1],   2*x[2],   4*x[3]-1],
            [4*x[0]+2, 2*x[1]-1, 2*x[2],   -1],
        ])

        return J

class PrintEnvironment(ExternalCode, ASMixin):

    def __init__(self):
        self.add_param('allocator', 'LocalHost')
        self.add_output('env_str', '')

    def solve_nonlinear(self, params, unknowns, resids):

        self.resources = dict(allocator=params['allocator'])
        self.command = ['printenv']
        self.stdout = 'printenv.out'
        with open('printenv.out', 'r') as inp:
            self.env_str = inp.read()
