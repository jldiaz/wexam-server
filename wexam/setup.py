# -*- coding: utf-8 -*-

from setuptools import setup, find_packages

name = 'wexam'
description = (
    'Un servidor de preguntas y examenes colaborativo'
)
version = '0.0.0'


setup(
    name=name,
    version=version,
    description=description,
    author='JL Diaz',
    author_email='jldiaz@uniovi.es',
    packages=find_packages(),
    namespace_packages=name.split('.')[:-1],
    include_package_data=True,
    zip_safe=False,
    platforms='any',
    install_requires=[
        'morepath',
        'more.pony',
        'more.jwtauth',
        'passlib',
        'bcrypt',
        'pyjwt==2.4.0',
        'werkzeug',
        'uwsgi',
        'simhash',
        'redis',
        'rq',
        'pyyaml',
        'psycopg2-binary',
    ],
    extras_require=dict(
        test=[
            'pytest',
            'webtest',
            'ruamel.yaml',
            'jsonschema'
        ],
        development=[
            'werkzeug'
            ]
    ),
    entry_points=dict(
        console_scripts=[
            'run-app = wexam.run:run',
            'morepathq = wexam.query:query_tool',
        ],
    ),
    classifiers=[
        'Intended Audience :: Developers',
        'Environment :: Web Environment',
        'Topic :: Internet :: WWW/HTTP :: WSGI',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.4',
    ]
)
