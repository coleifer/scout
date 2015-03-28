import os
from setuptools import setup

cur_dir = os.path.dirname(__file__)
readme_file = os.path.join(cur_dir, 'README.md')
with open(readme_file) as fh:
    readme = fh.read()

try:
    import scout
    VERSION = scout.__version__
except ImportError:
    VERSION = '0.1.4'

setup(
    name='scout',
    description='scout',
    long_description=readme,
    version=VERSION,
    author='Charles Leifer',
    author_email='coleifer@gmail.com',
    url='http://github.com/coleifer/scout/',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python'],
    license='MIT',
    install_requires=[
        'flask',
        'peewee>=2.4'],
    py_modules=['scout', 'scout_client'],
    scripts=['scout.py'],
    test_suite='tests',
)
