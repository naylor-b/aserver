from __future__ import print_function

import os
import sys
import logging
import traceback

from multiprocessing.managers import BaseManager, BaseProxy

from openmdao.core.problem import Problem
from openmdao.core.fileref import FileRef
from openmdao.core.group import Group
from openmdao.util.file_util import DirContext

try:
    from mpi4py import MPI
except ImportError:
    MPI = None

class SystemWrapper(object):

    def init(self, classname, instname, fpath=None, directory='', args=()):
        self.problem, self.system = _setup_obj(classname, instname, fpath,
                                               directory, args=args)

    def set(self, name, value):
        if name in self.system.params:
            self.system.params[name] = value
        else: # try to find a matching Problem attribute
            parts = name.split('.')
            obj = self.problem
            for n in parts[:-1]:
                obj = getattr(obj, n)
            setattr(obj, parts[-1], value)

    def get(self, name):
        if name in self.system.unknowns:
            return self.system.unknowns[name]
        elif name in self.system.params:
            return self.system.params[name]
        else:  # try to find a matching Problem attribute
            obj = self.problem
            for n in name.split('.'):
                obj = getattr(obj, n)
            return obj

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

    def fread(self, path, offset, num_bytes):
        """Attempt to read the specified number of bytes from the file with
        the specified path name.
        """
        with open(path, 'rb') as f:
            f.seek(offset)
            return f.read(num_bytes)

    def check_file(self, path):
        if not os.path.isfile(path):
            raise OSError("%s not found" % path)

    def stat(self, path):
        """
        Returns ``os.stat(path)`` if `path` is legal.

        path: string
            Path to file to interrogate.
        """
        logging.debug('stat %r', path)
        try:
            return os.stat(path)
        except Exception as exc:
            logging.error('stat %r in %s failed %s',
                               path, os.getcwd(), exc)
            raise

    def list_text_files(self):
        text_files = []
        absdir = self.get_abs_directory()
        for path in os.listdir(absdir):
            if os.path.isdir(path) or path.startswith('.'):
                continue
            with open(os.path.join(absdir, path), 'rb') as inp:
                if '\x00' not in inp.read(1 << 12):  # 4KB
                    text_files.append(path)

        return text_files

    def listdir(self, root):
        return os.listdir(root)

    def isdir(self, path):
        return os.path.isdir(path)

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


class DynMPISystemWrapper(SystemWrapper):
    """Wrapper for a Problem that requires multiple MPI processes. These
    processes are allocated dynamicallly using MPI.COMM_SELF.Spawn().
    """

    def init(self, num_procs, classname, instname, fpath=None, directory='',
             args=()):
        print("DYNMPISYSWRAPPER!")
        mydir = os.path.dirname(os.path.abspath(__file__))
        dynmod = os.path.join(mydir, 'dyn_mpi.py')
        dynargs = [dynmod, classname, instname]
        if fpath:
            dynargs.append('filename=%s' % fpath)
        if directory:
            dynargs.append("directory=%s" % directory)
        dynargs.extend(args)

        self.comm = MPI.COMM_SELF.Spawn(sys.executable,
                                        args=dynargs,
                                        maxprocs=num_procs)

    def _do_cmd(self, cmd, *args):
        self.comm.bcast((cmd, args), root=MPI.ROOT)
        results = self.comm.gather(None, root=MPI.ROOT)
        for r, tb in results:
            if tb is not None:  # an error occurred
                raise RuntimeError(tb)
        return results[0][0]

    def set(self, name, value):
        self._do_cmd('set', name, value)

    def get(self, name):
        return self._do_cmd('get', name)

    def invoke(self, name):
        return self._do_cmd('invoke', name)

    def get_pathname(self):
        return self._do_cmd('get_pathname')

    def run(self):
        return self._do_cmd('run')

    def write(self, name, value):
        return self._do_cmd('write', name, value)

    def fread(self, path, offset, num_bytes):
        """Attempt to read the specified number of bytes from the file with
        the specified path name.
        """
        return self._do_cmd('fread', path, offset, num_bytes)

    def check_file(self, path):
        return self._do_cmd('check_file', path)

    def stat(self, path):
        """
        Returns ``os.stat(path)`` if `path` is legal.

        path: string
            Path to file to interrogate.
        """
        return self._do_cmd('stat', path)

    def list_text_files(self):
        return self._do_cmd('list_text_files')

    def listdir(self, root):
        return self._do_cmd('listdir', root)

    def isdir(self, path):
        return self._do_cmd('isdir', path)

    def get_abs_directory(self):
        return self._do_cmd('get_abs_directory')

    def get_description(self, name):
        return self._do_cmd('get_description', name)

    def get_metadata(self, name):
        return self._do_cmd('get_metadata', name)

    def set_name(self, name):
        return self._do_cmd('set_name', name)

    def pre_delete(self):
        self._do_cmd('pre_delete')

        self.comm.bcast('STOP', root=MPI.ROOT)
        self.comm.Disconnect()


class SysManager(BaseManager):
    pass


SysManager.register('SystemWrapper', SystemWrapper)
SysManager.register('DynMPISystemWrapper', DynMPISystemWrapper)


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

        if isinstance(obj, Problem):
            p = obj
            obj = p.root
        else:
            if isinstance(obj, Group) and not instname:
                p = Problem(root=obj)
            else:
                p = Problem(root=Group())
                p.root.add(instname, obj)

        p.setup(check=False)

    return p, obj
