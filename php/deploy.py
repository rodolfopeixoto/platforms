# -*- coding: utf-8 -*-

# Copyright 2017 tsuru authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import os
import yaml
import sys
import re
from utils import parse_env

from interpretor import interpretors
from frontend import frontends
from vars import php_versions, default_version


class ConfigurationException(Exception):
    pass


class InstallationException(Exception):
    pass


class Manager(object):

    def __init__(self, configuration, application):
        self.configuration = configuration
        self.application = application

        self.frontend = self.create_frontend()
        self.interpretor = self.create_interpretor()

    def install(self):
        # Calling pre-install hooks
        self.frontend.pre_install()
        if self.interpretor is not None:
            self.interpretor.pre_install()

        packages_php_extensions = []
        if self.interpretor is not None:
            packages_php_extensions = self.interpretor.get_packages_extensions()

        if packages_php_extensions:
            print('Installing php extensions..')
            packages_to_install = []
            for package in packages_php_extensions:
                if "-" in package:
                    packages_to_install.append(self.prefix_package_version(package.split("-")[1]))
                else:
                    packages_to_install.append(self.prefix_package_version(package))
            try:
                if os.system("sudo apt-get install -y --force-yes %s" % (' '.join(packages_to_install))) != 0:
                    raise InstallationException('An error appeared while installing needed packages')
            except InstallationException:
                os.system("apt-get update")
                if os.system("sudo apt-get install -y --force-yes %s" % (' '.join(packages_to_install))) != 0:
                    raise InstallationException('An error appeared while installing needed packages')
            for package in packages_to_install:
                module_name = package.split("-")[1]
                if os.system("phpenmod %s" % module_name) != 0:
                    raise InstallationException('Could not enable %s php module' % module_name)

        # Calling post-install hooks
        self.frontend.post_install()
        if self.interpretor is not None:
            self.interpretor.post_install()

        # If there's no Procfile, create it
        Procfile_path = os.path.join(self.application.get('directory'), 'Procfile')
        procfile_contents = None
        if os.path.isfile(Procfile_path):
            with open(Procfile_path, 'r') as f:
                web_match = re.search(r"^web:", f.read(), flags=re.MULTILINE)
                if web_match is None:
                    f.seek(0)
                    procfile_contents = f.read()

        if not os.path.isfile(Procfile_path) or procfile_contents:
            with open(Procfile_path, 'w') as f:
                f.write('web: /bin/bash -lc "sudo -E %s' % self.frontend.get_startup_cmd())
                if self.interpretor is not None:
                    f.write(' && %s' % self.interpretor.get_startup_cmd(self.get_php_version()))
                f.write(' "\n')
                if procfile_contents:
                    f.write(procfile_contents)

        if self.configuration.get('composer', True):
            self.install_composer()

    def get_php_version(self):
        version = str(self.configuration.get('version', default_version))
        if version not in php_versions:
            version = default_version
        return version

    def prefix_package_version(self, package):
        return "php{}-{}".format(self.get_php_version(), package)

    def install_composer(self):
        if os.path.isfile(os.path.join(self.application.get('directory'), 'composer.json')):
            print('Install composer dependencies')
            composer_phar = '/usr/local/bin/composer_phar'
            if os.system('cd %s && sudo -u %s %s install' % (self.application.get('directory'),
                                                             self.application.get('user'), composer_phar)) != 0:
                raise InstallationException('Unable to install composer dependencies')

    def configure(self):
        if self.interpretor is not None:
            print('Configuring interpretor...')
            self.interpretor.configure(self.frontend)

        print('Configuring frontend...')
        self.frontend.configure(self.interpretor)

    def setup_environment(self):
        if self.interpretor is not None:
            self.interpretor.setup_environment()

        self.frontend.setup_environment()

    def create_frontend(self):
        frontend = self.configuration.get('frontend', {
            'name': 'apache-mod-php'
        })
        frontend_options = frontend.get('options', {})
        frontend_options['version'] = self.configuration.get('version', default_version)
        return self.get_frontend_by_name(frontend.get('name'))(frontend_options, self.application)

    def create_interpretor(self):
        interpretor = self.configuration.get('interpretor', None)
        if interpretor is None:
            return None
        elif 'name' not in interpretor:
            raise ConfigurationException('Interpretor name must be set')

        return self.get_interpretor_by_name(interpretor.get('name'))(interpretor.get('options', {}), self.application)

    @staticmethod
    def get_interpretor_by_name(name):
        if name not in interpretors:
            raise ConfigurationException('Interpretor %s is unknown' % name)

        return interpretors.get(name)

    @staticmethod
    def get_frontend_by_name(name):
        if name not in frontends:
            raise ConfigurationException('Frontend %s is unknown' % name)

        return frontends.get(name)


def load_file(working_dir="/home/application/current"):
    files_name = ["tsuru.yml", "tsuru.yaml", "app.yaml", "app.yml"]
    for file_name in files_name:
        try:
            file_path = os.path.join(working_dir, file_name)
            if os.path.exists(file_path) and file_name[0:3] == 'app':
                print('[WARNING] The `%s` configuration file name is deprecated' % file_name)

            with open(file_path) as f:
                return f.read()
        except IOError:
            pass

    return ""


def load_configuration():
    result = yaml.load(load_file())
    if result:
        return result.get('php', {})

    return {}


def print_help():
    print('This have to be called with 1 argument, which is the action')
    print()
    print('Possible values are:')
    print('- install: Install dependencies and configure system')
    print('- environment: Setup the environment')

if __name__ == '__main__':
    # Load PHP configuration from `tsuru.yml`
    config = load_configuration()

    # Create an application object from environ
    application = {
        'directory': '/home/application/current',
        'user': 'ubuntu',
        'source_directory': '/var/lib/tsuru',
        'env': parse_env(config)
    }

    # Get the application manager
    manager = Manager(config, application)

    # Run installation & configuration
    if len(sys.argv) <= 1:
        print_help()
    elif sys.argv[1] == 'install':
        manager.install()
        manager.configure()
    elif sys.argv[1] == 'environment':
        manager.setup_environment()
    else:
        print('Action "%s" not found\n' % sys.argv[1])
        print_help()
