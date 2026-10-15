"""Python build commands for FBMatrix's browser assets."""

from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from setuptools import Command, setup


ROOT = Path(__file__).resolve().parent


class BuildFrontend(Command):
    description = 'compile the TypeScript browser UI'
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        npm = shutil.which('npm') or shutil.which('npm.cmd')
        if npm is None:
            raise RuntimeError(
                'Building the fbmserve web UI requires Node.js and npm. '
                'Install Node.js, then run `npm ci` in the repository root.')
        if not (ROOT / 'node_modules' / 'typescript').is_dir():
            raise RuntimeError(
                'TypeScript is not installed. Run `npm ci` in the repository root '
                'before starting fbmserve.')
        subprocess.run([npm, 'run', 'build'], cwd=ROOT, check=True)


class Run(Command):
    description = 'build the browser UI and start fbmserve'
    user_options = [('args=', None, 'arguments to pass to fbmserve.py')]

    def initialize_options(self):
        self.args = ''

    def finalize_options(self):
        pass

    def run(self):
        self.run_command('build_frontend')
        subprocess.run([sys.executable, str(ROOT / 'fbmserve.py'),
                        *shlex.split(self.args or '')], cwd=ROOT, check=True)


class Test(Command):
    description = 'build the browser UI and run the Python test suite'
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        self.run_command('build_frontend')
        subprocess.run([sys.executable, '-m', 'pytest'], cwd=ROOT, check=True)


setup(
    packages=[],
    py_modules=[],
    cmdclass={
        'build': BuildFrontend,
        'build_frontend': BuildFrontend,
        'run': Run,
        'test': Test,
    },
)
