from __future__ import print_function

import sys
import logging
import numpy
from six import iteritems

from analysis_server.mixin import ASMixin

from openmdao.api import Problem, Group, Component, FileRef

class VariableTree(object):
    """A class to make it easier to port over old vartrees
    from classic OpenMDAO.
    """
    def __init__(self, name):
        self.variables = {}
        self.name = name

    def add(self, name, val, **kwargs):
        self.variables[name] = (val, kwargs)

    def iter_vars(self, local=False):
        if not local and self.name:
            for k, v in iteritems(self.variables):
                yield (':'.join((self.name, k)), v[0], v[1])
        else:
            for k, v in iteritems(self.variables):
                yield (k, v[0], v[1])

    def add_to(self, parent, iotype=None):
        if isinstance(parent, VariableTree):
            if isinstance(parent, Container):
                addfunc = parent.add
            else: # a VT that's not a Container
                if iotype is not None:
                    raise RuntimeError("Can't add VariableTree '%s' to "
                                       "VariableTree '%s' with an iotype of '%s'"
                                       % (self.name, parent.name, iotype))
                addfunc = parent.add
        elif iotype == 'in':
            addfunc = parent.add_param
        elif iotype == 'out':
            addfunc = parent.add_output
        else:
            raise RuntimeError("bad iotype: '%s'" % iotype)

        for k, val, kwargs in self.iter_vars():
            if iotype is not None:
                kwargs = kwargs.copy()
                kwargs['iotype'] = iotype

            addfunc(k, val, **kwargs)

        setattr(parent, self.name, self)

    def update_parent_unknowns(self, parent, src_vartree):
        """Using the names in this VariableTree and the source
        VariableTree, copy values from the params vec to the
        unknowns vec (both in the parent).
        """
        for k, val, kwargs in src_vartree.iter_vars():
            if k in self.variables:
                oldval, oldkwargs = self.variables[k]
                self.variables[k] = (val, oldkwargs)


class Container(VariableTree):
    """A class to make it easier to port over old subcontainers from
    classic OpenMDAO. A Container can contain variables with different
    iotypes.
    """

    def iter_params(self, local=False):
        for k, val, kwargs in self.iter_vars(local):
            if kwargs.get('iotype') == 'in':
                yield k, val, kwargs

    def iter_unknowns(self, local=False):
        for k, val, kwargs in self.iter_vars(local):
            if kwargs.get('iotype') == 'out':
                yield k, val, kwargs

    def add_to(self, parent):
        for k, val, kwargs in self.iter_params():
            parent.add_param(k, val, **kwargs)

        for k, val, kwargs in self.iter_unknowns():
            if kwargs.get('state'):
                parent.add_state(k, val, **kwargs)
            else:
                parent.add_output(k, val, **kwargs)

        setattr(parent, self.name, self)


class SubObj(VariableTree):
    """ Sub-object under TopObject. """

    def __init__(self, name):
        super(SubObj, self).__init__(name)

        self.add('sob', False)
        self.add('sof', 0.284, units='lb/inch**3')
        self.add('soi', 3)
        self.add('sos', 'World')


class TopObj(VariableTree):
    """ Top-level object variable. """

    def __init__(self, name):
        super(TopObj, self).__init__(name)

        self.add('tob', True)
        self.add('tof', 0.5, units='inch')
        self.add('toi', 42)
        self.add('tos', 'Hello')
        self.add('tofe', 2.781828, values=(2.781828, 3.14159),
                    aliases=('e', 'pi'), desc='Float enum', units='m')
        self.add('toie', 9, values=(9, 8, 7, 1), desc='Int enum')
        self.add('tose', 'cold', values=('cold', 'hot', 'nice'), desc='Str enum')

        self.add('tof1d',
                 numpy.array([1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5]),
                 desc='1D float array', units='cm', low=0., high=10.)

        self.add('tof2d', numpy.array([ [1.5, 2.5, 3.5, 4.5],
                                        [5.5, 6.5, 7.5, 8.5] ]),
                 desc='2D float array', units='mm')

        self.add('tof3d',
                 numpy.array([ [  [1.5, 2.5, 3.5],
                                  [4.5, 5.5, 6.5],
                                  [7.5, 8.5, 9.5] ],
                                [ [10.5, 20.5, 30.5],
                                  [40.5, 50.5, 60.5],
                                  [70.5, 80.5, 90.5] ] ]),
                 desc='3D float array')

        self.add('toi1d', numpy.array([1, 2, 3, 4, 5, 6, 7, 8, 9], dtype=int),
                 desc='1D int array')

        self.add('tos1d', ['Hello', 'from', 'TestComponent.tos1d'],
                 desc='1D string array')

        self.add('toflst', [], desc='Float list', element_type=float)
        self.add('toilst', [], desc='Int list', element_type=int)

        SubObj('sobobj').add_to(self)


class SubGroup(Container):

    def __init__(self, name):
        super(SubGroup, self).__init__(name)

        self.add('b', True, iotype='in', desc='A boolean')
        self.add('f', 0.5, iotype='in', desc='A float')
        self.add('i', 7, iotype='in', desc='An int')
        self.add('s', 'Hello World!  ( & < > )', iotype='in', desc='A string')

        self.add('fe', 2.781828, values=(2.781828, 3.14159),
                   aliases=('e', 'pi'), iotype='in', desc='Float enum', units='m')
        self.add('ie', 9, values=(9, 8, 7, 1), iotype='in', desc='Int enum')
        self.add('se', 'cold', values=('cold', 'hot', 'nice'), iotype='in', desc='Str enum')

        self.add('f1d',
                 numpy.array([1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5]),
                 desc='1D float array', iotype='in', units='cm', low=0., high=10.)

        self.add('f2d',
                 numpy.array([ [1.5, 2.5, 3.5, 4.5],
                               [5.5, 6.5, 7.5, 8.5] ]), iotype='in',
                 desc='2D float array', units='mm')

        self.add('f3d', numpy.array([ [ [1.5, 2.5, 3.5],
                          [4.5, 5.5, 6.5],
                          [7.5, 8.5, 9.5] ],
                        [ [10.5, 20.5, 30.5],
                          [40.5, 50.5, 60.5],
                          [70.5, 80.5, 90.5] ] ]), iotype='in',
                 desc='3D float array')

        self.add('i1d', numpy.array([1, 2, 3, 4, 5, 6, 7, 8, 9], dtype=int),
                 iotype='in', desc='1D int array')

        self.add('s1d', numpy.array(['Hello', 'from', 'TestComponent.SubGroup'],
                                    dtype=str),
                 iotype='in', desc='1D string array')

        self.add('flst', [], iotype='in', desc='List of floats', element_type=float)
        self.add('ilst', [], iotype='in', desc='List of ints', element_type=int)


class Bogus(object):
    """ To test instantiation. """

    def __init__(self, need_one_argument):
        self._arg = need_one_argument


class TestComponent(Component, ASMixin):
    """ Just something to test with. """

    def __init__(self):
        super(TestComponent, self).__init__()
        self.add_param('x', 2.0, desc='X input')
        self.add_param('y', 3.0, desc='Y input', low=-10, high=10, units='ft')
        self.add_output('z', 0.0, desc='Z output', units='ft')
        self.add_output('exe_count', 0, pass_by_obj=True, desc='Execution count')
        self.add_output('exe_dir', '', pass_by_obj=True,
                         desc='Execution directory')

        self.add_param('in_file', FileRef('inFile.data'), desc='Input file')
        self.add_output('out_file', FileRef('outFile.data'), desc='Output file')

        TopObj('obj_input').add_to(self, iotype='in')
        TopObj('obj_output').add_to(self, iotype='out')

        SubGroup('sub_group').add_to(self)

    def solve_nonlinear(self, params, unknowns, resids):
        x = params['x']
        y = params['y']

        if x < 0:
            raise RuntimeError('x %s is < 0' % x)

        unknowns['z'] = z = x * y
        unknowns['exe_count'] += 1
        unknowns['exe_dir'] = self._sysdata.absdir

        with params['in_file'].open('r') as inp:
            with unknowns['out_file'].open('w') as out:
                out.write(inp.read())

        logging.info('    %s %s %s', x, y, z)
        sys.stdout.write('stdout: %s %s %s\n' % (x, y, z))
        sys.stdout.flush()

        # Copy input object to output object.
        self.obj_output.update_parent_unknowns(self, self.obj_input)

    def cause_exception(self):
        self.raise_exception("It's your own fault...", RuntimeError)

    def float_method(self):
        return self.x + self.y

    def int_method(self):
        return self.exe_count

    def null_method(self):
        return

    def str_method(self):
        msg = 'current state: x %r, y %r, z %r, exe_count %r' \
              % (self.params['x'], self.params['y'], self.unknowns['z'],
                 self.unknowns['exe_count'])
        return msg


if __name__ == '__main__':
    p = Problem(root=Group())
    top = p.root
    comp = top.add('comp', TestComponent())
    comp._init_params_dict['in_file']['val'].fname = 'ASTestComp-0.1.cfg'
    p.setup()
    p.run()
    for path in ('x', 'y', 'z', 'exe_count',
                 'sub_group:b', 'sub_group:f', 'sub_group:i', 'sub_group:s',
                 'sub_group:fe', 'sub_group:ie', 'sub_group:se',
                 'sub_group:f1d', 'sub_group:i1d', 'sub_group:s1d'):
        print('%s: %s' % (path, p['.'.join(('comp',path))]))
