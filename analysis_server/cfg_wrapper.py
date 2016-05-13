
import os
import sys
import time
import logging
from inspect import getmembers, ismethod, isfunction

from six import iteritems

from analysis_server.varwrapper import _find_var_wrapper
from analysis_server.proxy import _setup_obj

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
        defaults = {
            'version': '',
            'comment': '',
            'author': '',
            'description': '',
            'help_url': '',
            'keywords': '',
            'requirements': '',
        }

        # Get Python class and create temporary instance.
        if config.has_option(section, 'filename'):
            fname = config.get(section, 'filename')
        else:
            fname = None

        self.filename = fname

        if config.has_option(section, 'args'):
            args = [a.strip() for a in config.get(section, 'args').split()
                                   if a.strip()]
        else:
            args = []

        p, instance = _setup_obj(section, 'comp', fname, args=args)

        # Check for optional diectory path.
        self.directory = directory = None
        if config.has_option(section, 'directory'):
            directory = config.get(section, 'directory')
            if os.path.isabs(directory) or directory.startswith('..'):
                raise ValueError('directory %r must be a subdirectory'
                                 % directory)

        self.section = section

        for option, value in defaults.items():
            if not config.has_option(section, option):
                setattr(self, option, value)
            else:
                setattr(self, option, config.get(section, option))

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
