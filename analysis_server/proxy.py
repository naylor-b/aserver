
import os
import sys
import logging
import traceback

from multiprocessing.managers import BaseManager, BaseProxy

from openmdao.core.problem import Problem
from openmdao.core.fileref import FileRef
from openmdao.core.group import Group
from openmdao.util.file_util import DirContext


class SystemWrapper(object):

    def init(self, classname, instname, fpath=None, directory='', args=()):
        self.problem, self.system = _setup_obj(classname, instname, fpath,
                                               directory, args=args)

    def set(self, name, value):
        self.system.params[name] = value

    def get(self, name):
        if name in self.system.unknowns:
            return self.system.unknowns[name]
        else:
            return self.system.params[name]

    def invoke(self, name):
        return getattr(self.system, name)()

    def get_pathname(self):
        return self.system.pathname

    def run(self):
        self.problem.run()

    def write(self, name, value):
        fileref = self.system.params[name]
        if isinstance(fileref, FileRef):
            fileref.write(value)
        else:
            raise RuntimeError("'%s' is not a FileRef." % name)

    def listdir(self, root):
        return os.listdir(root)

    def get_abs_directory(self):
        return self.system._sysdata.absdir

    def get_description(self, name):
        if name in self.system.unknowns:
            meta = self.system.unknowns._dat[name].meta
        else:
            meta = self.system.params._dat[name].meta
        return meta.get('desc', '')

    def get_metadata(self, name):
        if name in self.system.unknowns:
            meta = self.system.unknowns._dat[name].meta
        else:
            meta = self.system.params._dat[name].meta
        return meta

    def set_name(self, name):
        self.system.name = name

    def pre_delete(self):
        if hasattr(self.system, 'pre_delete'):
            self.system.pre_delete()

class SysManager(BaseManager):
    pass

SysManager.register('SystemWrapper', SystemWrapper)


def _setup_obj(classname, instname, filename=None, directory='', args=()):
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

        p = Problem(root=Group())
        p.root.add(instname, obj)
        p.setup(check=False)

    return p, obj
