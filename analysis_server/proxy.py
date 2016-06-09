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
import openmdao.util.log

try:
    from mpi4py import MPI
except ImportError:
    MPI = None

class ProblemProxy(object):

    def init(self, classname, instname, fpath=None, directory='', args=()):
        self.problem = _setup_obj(classname, instname, fpath,
                                  directory, args=args)
        self.system = self.problem.root
        self._logger = logging.getLogger(instname+'_proxy')

    def set(self, name, value):
        try:
            self.problem[name] = value
        except:
            parts = name.split('.')
            obj = self.problem
            for n in parts[:-1]:
                obj = getattr(obj, n)
            setattr(obj, parts[-1], value)

    def get(self, name):
        try:
            ret = self.problem[name]
            #self._logger.info("returning prob[%s] = %s" % (name,ret))
            return ret
        except:
            #self._logger.info("GETTING attr: %s" % name)
            obj = self.problem
            for n in name.split('.'):
                obj = getattr(obj, n)
            return obj

    def invoke(self, name):
        #self._logger.info("INVOKING: %s" % name)
        obj = self.problem
        try:
            for n in name.split('.'):
                obj = getattr(obj, n)
        except AttributeError: # look in root object next
            obj = self.problem.root
            for n in name.split('.'):
                obj = getattr(obj, n)
        return obj()

    def get_pathname(self):
        return self.problem.pathname

    def run(self):
        self.problem.run()

    def write(self, name, value):
        fileref = self.problem[name]
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
        self._logger.debug('stat %r', path)
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
        meta = self.get_metadata(name)
        return meta.get('desc', '')

    def get_metadata(self, name):
        #logging.info("get_metadata(%s)" % name)
        if name in self.system.unknowns:
            return self.system.unknowns._dat[name].meta
        else:
            pdict = self.system._params_dict # this contains all model params
            to_abs = self.system._sysdata.to_abs_pnames
            if name in to_abs:
                for p in to_abs[name]:
                    if p in pdict:
                        return pdict[p]
        return {}

    def set_name(self, name):
        self.problem.name = name

    def pre_delete(self):
        if hasattr(self.system, 'pre_delete'):
            self.system.pre_delete()


class SysManager(BaseManager):
    pass


SysManager.register('ProblemProxy', ProblemProxy)


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
    # strip categories from classname
    classname = classname.rsplit('/', 1)[-1]
    try:
        cls = getattr(module, classname)
    except AttributeError as exc:
        raise RuntimeError("Can't get class %r in %r: %r"
                           % (classname, modname, exc))

    with DirContext(dirname):
        try:
            p = cls(*args)
        except Exception as exc:
            logging.error(traceback.format_exc())
            raise RuntimeError("Can't instantiate %s.%s: %r"
                               % (modname, classname, exc))

        if not isinstance(p, Problem):
            raise TypeError("Wrapped instance must be a Problem and not a %s" % type(p))

        p.name = instname
        p.setup(check=False)

    return p
