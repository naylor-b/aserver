
import os
import sys
import time
import logging
from inspect import getmembers, ismethod, isfunction
from itertools import chain
from fnmatch import fnmatchcase

from six import iteritems

from openmdao.core.problem import Problem
import openmdao.util.log

from analysis_server.varwrapper import _find_var_wrapper
from analysis_server.proxy import _setup_obj

_CONFIG_DEFAULTS = {
    'version': '',
    'comment': '',
    'author': '',
    'description': '',
    'help_url': '',
    'keywords': '',
    'requirements': '',
    'num_procs': '1',
    'args': '',
    'directory': None,
    'filename': None,
    'in_attrs': '',
    'out_attrs': '',
    'in_vars': '',
    'out_vars': '*',
    'methods': '',
}

# maps option names from cfg file to attribute names in the wrapper
_CFG_MAP = {
    'in_vars': 'in_var_patterns',
    'out_vars': 'out_var_patterns',
}

def _str2list(string):
    lst = []
    for s in string.split():
        ss = s.strip()
        if ss:
            lst.append(ss)
    return lst

def _get_match(name, patterns):
    for p in patterns:
        if fnmatchcase(name, p):
            return name.replace(':', '.')

def _deep_getattr(obj, name):
    for n in name.split('.'):
        obj = getattr(obj, n)
    return obj

class _ConfigWrapper(object):
    """
    Retains configuration data for a wrapped component class.

    config: :class:`ConfigParser.ConfigParser`
        Configuration data.

    instance: Component
        Temporary wrapped instance to interrogate.

    cfg_path: string
        Path to the configuration file.

    """

    def __init__(self, classname, config, timestamp):

        # Get description info.
        # Get Python class and create temporary instance.
        for option in _CONFIG_DEFAULTS:
            setattr(self, _CFG_MAP.get(option, option), config.get('AnalysisServer', option))

        self.num_procs = int(self.num_procs)

        self.args = _str2list(self.args)
        self.in_var_patterns = _str2list(self.in_var_patterns)
        self.out_var_patterns = _str2list(self.out_var_patterns)
        self.in_attrs = _str2list(self.in_attrs)
        self.out_attrs = _str2list(self.out_attrs)
        self.methods = _str2list(self.methods)

        instance = _setup_obj(classname, 'comp', self.filename, args=self.args)

        # Check for optional diectory path.
        if self.directory:
            if os.path.isabs(self.directory) or self.directory.startswith('..'):
                raise ValueError('directory %r must be a subdirectory'
                                 % self.directory)

        self.classname = classname

        # Timestamp from config file timestamp
        self.timestamp = timestamp
        self.checksum = 0
        self.has_icon = False

        # Default description from instance.__doc__.
        if not self.description:
            if instance.__doc__ is not None:
                self.description = instance.__doc__

        # Get properties.
        self.inputs = self._setup_mapping(instance, 'invar')
        self.outputs = self._setup_mapping(instance, 'outvar')
        self.in_attrs = self._setup_mapping(instance, 'inattr')
        self.out_attrs = self._setup_mapping(instance, 'outattr')

        # overlapping glob patterns result in outputs
        for name in self.out_attrs:
            if name in self.in_attrs:
                del self.in_attrs

        self.properties = {}
        self.properties.update(self.inputs)
        self.properties.update(self.outputs)
        self.properties.update(self.in_attrs)
        self.properties.update(self.out_attrs)

        # Get methods.
        methods = self.methods
        self.methods = {}
        for name in methods:
            logging.debug('    register %s()', name)
            self.methods[name] = name

        instance.cleanup()
        if hasattr(instance, 'pre_delete'):
            instance.pre_delete()

    def _setup_mapping(self, instance, iotype):
        """
        Return dictionary mapping external paths to internal paths.

        instance: Problem
            Temporary wrapped Problem to interrogate.

        iotype: str
            String indicating type [invar, outvar, inattr, outattr]
        """
        mapping = {}

        if iotype in ('inattr', 'outattr'):
            attrs = self.in_attrs if iotype == 'inattr' else self.out_attrs

            for attr in attrs:
                try:
                    val = _deep_getattr(instance, attr)
                except AttributeError as exc:
                    raise AttributeError("Couldn't find '%s' in '%s': %s" % (attr, instance.pathname,str(exc)))
                wrapper_class = _find_var_wrapper(val)
                if wrapper_class is None:
                    logging.warning("%s", val)
                    logging.warning('%r not a supported type: %r',
                                   attr, type(val).__name__)
                    continue
                mapping[attr] = attr
            return mapping

        to_prom = instance.root._sysdata.to_prom_name

        if iotype == 'invar':
            pdict = instance.root._params_dict
            seen = set()
            items = []
            for k, m in chain(iteritems(pdict), iteritems(instance.root._unknowns_dict)):
                prom = to_prom[k]
                if prom not in seen:
                    seen.add(prom)
                    items.append((prom, m['val']))

            patterns = self.in_var_patterns
        elif iotype == 'outvar':
            items = [(to_prom[k],m['val']) for k,m in iteritems(instance.root._unknowns_dict)]
            patterns = self.out_var_patterns
        else:
            raise TypeError("bad iotype (%s). Should be one of [invar, outvar, inattr, outattr]" % iotype)

        for name, val in sorted(items, key=lambda x: x[0]):
            # Only register if it's a supported type.
            wrapper_class = _find_var_wrapper(val)
            if wrapper_class is None:
                logging.warning("%s", val)
                logging.warning('%r not a supported type: %r',
                               name, type(val).__name__)
                continue

            m = _get_match(name, patterns)
            if m is not None:
                mapping[m] = name

        return mapping
