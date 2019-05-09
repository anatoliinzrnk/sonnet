"""Setup for pip package."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from setuptools import find_namespace_packages
from setuptools import setup

import sonnet as sonnet

_VERSION = sonnet.__version__

EXTRA_PACKAGES = {
    'tensorflow': ['tensorflow>=2'],
    'tensorflow with gpu': ['tensorflow-gpu>=2'],
}

REQUIRED_PACKAGES = [
    'absl-py',
    'numpy',
    'six',
    'wrapt'
]

setup(
    name='dm-sonnet',
    version=_VERSION,
    url='https://github.com/deepmind/sonnet',
    license='Apache 2.0',
    author='DeepMind',
    description=(
        'Sonnet is a library for building neural networks in TensorFlow.'),
    long_description=open('README').read(),
    author_email='sonnet-dev-os@google.com',
    # Contained modules and scripts.
    packages=find_namespace_packages(exclude=['*_test.py']),
    install_requires=REQUIRED_PACKAGES,
    extras_require=EXTRA_PACKAGES,
    tests_require=['mock'],
    requires_python='>=3.6',
    include_package_data=True,
    zip_safe=False,
    # PyPI package information.
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Intended Audience :: Education',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Topic :: Scientific/Engineering :: Mathematics',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Software Development :: Libraries',
    ],
)
