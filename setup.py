import os
import warnings

from setuptools import setup

cur_dir = os.path.dirname(__file__)
readme_file = os.path.join(cur_dir, 'README.md')
with open(readme_file) as fh:
    readme = fh.read()

try:
    from scout import __version__ as scout_version
except ImportError:
    scout_version = '0.0.0'
    warnings.warn('Unable to determine scout library version!')

setup(
    name='scout',
    version=scout_version,
    url='http://github.com/coleifer/scout/',
    license='MIT',
    author='Charles Leifer',
    author_email='coleifer@gmail.com',
    description='scout - a lightweight search server powered by SQLite',
    packages=['scout'],
    zip_safe=False,
    platforms='any',
    install_requires=[
        'flask',
        'peewee>=3.0.0'],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python'],
    py_modules=['scout_client'],
    test_suite='scout.tests',
    entry_points="""
        [console_scripts]
        scout=scout.server:main
    """,
)
