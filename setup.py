from setuptools import setup

setup(
    name='scout',
    version=__import__('scout').__version__,
    description='scout',
    author='Charles Leifer',
    author_email='coleifer@gmail.com',
    url='http://github.com/coleifer/scout/',
    py_modules=['scout'],
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
    ],
    scripts=['scout.py'],
    test_suite='tests',
)
