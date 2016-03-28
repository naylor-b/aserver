
import os
import sys
import time
import logging
from inspect import getmembers, ismethod, isfunction

from six import iteritems

from analysis_server.wrapper import _find_var_wrapper

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

    def __init__(self, config, instance, cfg_path):

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
        for option in defaults:
            if not config.has_option('AnalysisServer', option):
                config.set('AnalysisServer', option, defaults[option])
            setattr(self, option, config.get('AnalysisServer', option))

        # Normalize name of config file to <component_name>-<version>.cfg.
        cfg_name = os.path.basename(cfg_path)
        name, _, version = cfg_name.partition('-')
        if not version:
            name = name[:-4]  # Drop '.cfg'
            if self.version:
                version = self.version
            else:
                raise ValueError('No version in .cfg file or .cfg filename')
        elif not self.version:
            raise ValueError('No version in .cfg file')

        self.cfg_path = cfg_path

        # Timestamp from config file timestamp
        self.timestamp = time.ctime(os.path.getmtime(cfg_path))
        self.checksum = 0
        self.has_icon = False

        # Default description from instance.__doc__.
        if not self.description:
            if instance.__doc__ is not None:
                self.description = instance.__doc__

        # Default author from file owner.
        if not self.author and sys.platform != 'win32':
            stat_info = os.stat(cfg_path)
            self.author = pwd.getpwuid(stat_info.st_uid).pw_name

        # Get properties.
        self.inputs = self._setup_mapping(instance, 'in')
        self.outputs = self._setup_mapping(instance, 'out')
        self.properties = {}
        self.properties.update(self.inputs)
        self.properties.update(self.outputs)

        # Get methods.
        self.methods = {}
        for name, meth in sorted(getmembers(instance, ismethod)):
            # Register all valid non-vanilla methods.
            if name.startswith('_'):
                continue

            logging.debug('    register %s()', name)
            self.methods[name] = name

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
