from setuptools import setup, find_packages

setup(
    name = "jvbot",
    version = "2.0.0",
    packages = ["jvbot"],
    package_dir = {
        "jvbot": "jvbot"
    },
    author = "Eric Oberholtz",
    author_email = "eoberhol@ucsd.edu",
    install_requires = [
        'numpy',
        'matplotlib',
        'scipy',
        # 'keithley_package'
    ],
    license = 'MIT',
    long_descripton = open('./jvbot/README.txt').read(),
)