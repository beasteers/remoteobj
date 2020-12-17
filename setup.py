import setuptools

USERNAME = 'beasteers'
NAME = 'remoteobj'

setuptools.setup(
    name=NAME,
    version='0.2.8',
    description='Facilitating cross-process programming.',
    long_description=open('README.md').read().strip(),
    long_description_content_type='text/markdown',
    author='Bea Steers',
    author_email='bea.steers@gmail.com',
    url='https://github.com/{}/{}'.format(USERNAME, NAME),
    packages=setuptools.find_packages(),
    # entry_points={'console_scripts': ['{name}={name}:main'.format(name=NAME)]},
    install_requires=[],
    license='MIT License',
    keywords='multiprocessing process except raise exception handling '
             'proxy remote ops result yield')
