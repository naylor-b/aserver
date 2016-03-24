
from distutils.core import setup

setup(name='analysis_server',
      version='1.0',
      description="OpenMDAO interface to Phoenix Integration's ModelCenter/AnalysisServer",
      classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Science/Research',
        'Topic :: Scientific/Engineering',
        'License :: OSI Approved :: Apache Software License',
        'Natural Language :: English',
        'Operating System :: MacOS :: MacOS X',
        'Operating System :: POSIX :: Linux',
        'Operating System :: Microsoft :: Windows',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: Implementation :: CPython',
      ],
      keywords='analysis',
      author='OpenMDAO Team',
      author_email='openmdao@openmdao.org',
      url='http://openmdao.org',
      download_url='',
      license='Apache License, Version 2.0',
      packages=[
          'analysis_server',
      ],
      package_data={},
      install_requires=[
        'openmdao',
      ],
      entry_points="""
      [console_scripts]
      """
)
