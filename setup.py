from setuptools import setup

setup(
    name='scout',
    packages=['scout'],
    py_modules=['scout_client'],
    entry_points={'console_scripts': ['scout = scout.server:main']})
