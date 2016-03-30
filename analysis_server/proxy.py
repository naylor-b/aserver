
import os
import sys
import logging
import traceback

from multiprocessing.managers import BaseManager, BaseProxy

from openmdao.core.problem import Problem
from openmdao.core.group import Group
from openmdao.util.file_util import DirContext


class SystemWrapper(object):

    def init(self, classname, fpath=None, directory='', args=()):
        self.problem, self.system = _setup_obj(classname, fpath, directory,
                                               args=args)

    def set(self, name, value):
        self.system.params[name] = value

    def get(self, name):
        if name in self.system.unknowns:
            return self.system.unknowns[name]
        else:
            return self.system.params[name]

    def set_name(self, name):
        self.system.name = name

    def pre_delete(self):
        if hasattr(self.system, 'pre_delete'):
            self.system.pre_delete()

class SysManager(BaseManager):
    pass

SysManager.register('SystemWrapper', SystemWrapper)


def _setup_obj(classname, filename=None, directory='', args=()):
    # Get Python class and create instance.

    if filename is None:  # assume we can just import the class
        modname, classname = classname.rsplit('.', 1)
        dirname = os.getcwd()
    else:
        dirname = os.path.dirname(filename)
        modname = os.path.splitext(os.path.basename(filename))[0]  # drop '.py'
        if not os.path.isabs(dirname):
            if dirname:
                dirname = os.path.join(os.getcwd(), dirname)
            else:
                dirname = os.getcwd()

    logging.info('    prepending %r to sys.path', dirname)
    sys.path.insert(0, dirname)
    try:
        __import__(modname)
    finally:
        sys.path.pop(0)

    module = sys.modules[modname]
    try:
        cls = getattr(module, classname)
    except AttributeError as exc:
        raise RuntimeError("Can't get class %r in %r: %r"
                           % (classname, modname, exc))

    with DirContext(dirname):
        try:
            obj = cls(*args)
        except Exception as exc:
            logging.error(traceback.format_exc())
            raise RuntimeError("Can't instantiate %s.%s: %r"
                               % (modname, classname, exc))

        if isinstance(obj, Group):
            root = obj
        else:
            root = Group()

        p = Problem(root=root)
        if obj is not root:
            root.add('comp', obj)

        p.setup(check=False)

    return p, obj
