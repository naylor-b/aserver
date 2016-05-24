
import os
import sys
import time
import logging
from inspect import getmembers, ismethod, isfunction

from six import iteritems

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
}


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

    def __init__(self, config, section, timestamp):

        # Get description info.
        # Get Python class and create temporary instance.
        for option in _CONFIG_DEFAULTS:
            setattr(self, option, config.get(section, option))

        self.num_procs = int(self.num_procs)

        self.args = [a.strip() for a in self.args.split() if a.strip()]

        p, instance = _setup_obj(section, 'comp', self.filename, args=self.args)

        # Check for optional diectory path.
        if self.directory:
            if os.path.isabs(self.directory) or self.directory.startswith('..'):
                raise ValueError('directory %r must be a subdirectory'
                                 % self.directory)

        self.section = section

        # Timestamp from config file timestamp
        self.timestamp = timestamp
        self.checksum = 0
        self.has_icon = False

        # Default description from instance.__doc__.
        if not self.description:
            if instance.__doc__ is not None:
                self.description = instance.__doc__

        # Get properties.
        self.inputs = self._setup_mapping(instance, 'in')
        self.outputs = self._setup_mapping(instance, 'out')
        self.properties = {}
        self.properties.update(self.inputs)
        self.properties.update(self.outputs)

        # Get methods.
        self.methods = {}
        for name, meth in sorted(getmembers(instance, ismethod)):
            if name.startswith('_'):
                continue

            logging.debug('    register %s()', name)
            self.methods[name] = name

        p.cleanup()
        if hasattr(instance, 'pre_delete'):
            instance.pre_delete()

    def _setup_mapping(self, instance, iotype):
        """
        Return dictionary mapping external paths to internal paths.

        instance: Component
            Temporary wrapped instance to interrogate.

        iotype: string
            'in' or 'out'.

        """
        if iotype == 'in':
            items = iteritems(instance.params)
        else:
            items = iteritems(instance.unknowns)

        mapping = {}
        for name, meta in sorted(items, key=lambda x: x[0]):
            val = meta['val']
            # Only register if it's a supported type.
            wrapper_class = _find_var_wrapper(val)
            if wrapper_class is None:
                logging.warning("%s", val)
                logging.warning('%r not a supported type: %r',
                               name, type(val).__name__)
                continue
            logging.debug('    register %s %r %r',
                         type(val).__name__, name, iotype)
            mapping[name.replace(':', '.')] = name

        return mapping
