#!/usr/bin/env python
from __future__ import unicode_literals

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

long_description = (
    'AAutoCaption is a utility to generate subtitle automatically for videos. '
)

setup(
    name='autocaption',
    version='0.0.01',
    description='Auto-generates subtitles for any video or audio file',
    long_description=long_description,
    author='geniusq1981',
    author_email='geniusq1981@hotmail.com',
    url='https://github.com/geniusq1981/AutoCaption',
    packages=['autocaption'],
    entry_points={
        'console_scripts': [
            'autocaption = autocaption:main',
        ],
    },
    install_requires=[
        'requests>=2.3.0',
        'pysrt>=1.0.1',
        'progressbar2>=3.34.3',
        'six>=1.11.0',
        'SpeechRecognition>=3.8.1'
        'pocketsphinx>=0.1.15',
    ],
    license=open("LICENSE").read()
)
