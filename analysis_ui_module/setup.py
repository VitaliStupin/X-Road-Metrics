#!/usr/bin/python3
from setuptools import setup, find_packages

requirements = [
    "dill==0.3.1.1",
    "django==1.11.17",
    "pymongo==3.10.1",
    "pyyaml==5.3.1",
    "numpy"
]

classifiers = [
    'Development Status :: 3 - Alpha',
    'Environment :: Console',
    'Intended Audience :: System Administrators',
    'License :: OSI Approved :: MIT License',
    'Natural Language :: English',
    'Operating System :: POSIX :: Linux',
    'Programming Language :: Python :: 3',
    'Topic :: Utilities',
]

setup(
    name='opmon-analysis-ui',
    version='0.1',
    description='X-Road Operational Monitoring Analysis UI Module',
    long_description='',
    author='NIIS',
    author_email='info@niis.org',
    packages=find_packages(exclude=("tests",)),
    include_package_data=True,
    install_requires=requirements,
    classifiers=classifiers,
    platforms='POSIX',
    license='MIT License'
)
