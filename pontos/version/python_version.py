# Copyright (C) 2020-2021 Greenbone Networks GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import importlib

from pathlib import Path

import tomlkit

from .helper import (
    safe_version,
    strip_version,
    check_develop,
    is_version_pep440_compliant,
    VersionError,
    versions_equal,
)
from .version import VersionCommand


TEMPLATE = """# pylint: disable=invalid-name

# THIS IS AN AUTOGENERATED FILE. DO NOT TOUCH!

__version__ = "{}"\n"""


# This class is used for Python Version command(s)
class PythonVersionCommand(VersionCommand):
    def __init__(self, *, project_file_path: Path = None) -> None:
        if not project_file_path:
            project_file_path = Path.cwd() / 'pyproject.toml'

        if not project_file_path.exists():
            raise VersionError(f'{str(project_file_path)} file not found.')

        self.pyproject_toml = tomlkit.parse(
            project_file_path.read_text(encoding='utf-8')
        )

        if (
            'tool' not in self.pyproject_toml
            or 'pontos' not in self.pyproject_toml['tool']
            or 'version' not in self.pyproject_toml['tool']['pontos']
        ):
            raise VersionError(
                '[tool.pontos.version] section missing '
                f'in {str(project_file_path)}.'
            )

        pontos_version_settings = self.pyproject_toml['tool']['pontos'][
            'version'
        ]

        try:
            version_file_path = Path(
                pontos_version_settings['version-module-file']
            )
        except tomlkit.exceptions.NonExistentKey:
            raise VersionError(
                'version-module-file key not set in [tool.pontos.version] '
                f'section of {str(project_file_path)}.'
            ) from None

        super().__init__(
            version_file_path=version_file_path,
            project_file_path=project_file_path,
        )

    def _get_version_from_pyproject_toml(self) -> str:
        """
        Return the version information from the [tool.poetry] section of the
        pyproject.toml file. The version may be in non standardized form.
        """

        if (
            'tool' in self.pyproject_toml
            and 'poetry' in self.pyproject_toml['tool']
            and 'version' in self.pyproject_toml['tool']['poetry']
        ):
            return self.pyproject_toml['tool']['poetry']['version']

        raise VersionError(
            'Version information not found in '
            f'{str(self.project_file_path)} file.'
        )

    def _update_version_file(self, new_version: str) -> None:
        """
        Update the version file with the new version
        """
        new_version = safe_version(new_version)
        self.version_file_path.write_text(
            TEMPLATE.format(new_version), encoding='utf-8'
        )

    def _update_pyproject_version(
        self,
        new_version: str,
    ) -> None:
        """
        Update the version in the pyproject.toml file
        """

        new_version = safe_version(new_version)
        pyproject_toml = tomlkit.parse(
            self.project_file_path.read_text(encoding='utf-8')
        )

        if 'tool' not in pyproject_toml:
            tool_table = tomlkit.table()
            pyproject_toml['tool'] = tool_table

        if 'poetry' not in pyproject_toml['tool']:
            poetry_table = tomlkit.table()
            pyproject_toml['tool'].add('poetry', poetry_table)

        pyproject_toml['tool']['poetry']['version'] = new_version

        self.project_file_path.write_text(
            tomlkit.dumps(pyproject_toml), encoding='utf-8'
        )

    def get_current_version(self) -> str:
        version_module_name = self.version_file_path.stem
        module_parts = list(self.version_file_path.parts[:-1]) + [
            version_module_name
        ]
        module_name = '.'.join(module_parts)
        try:
            version_module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            raise VersionError(
                f'Could not load version from {module_name}. Import failed.'
            ) from None

        return version_module.__version__

    def verify_version(self, version_str: str) -> None:
        current_version = self.get_current_version()
        if not is_version_pep440_compliant(current_version):
            raise VersionError(
                f"The version {current_version} in "
                f"{str(self.version_file_path)} is not PEP 440 compliant."
            )

        pyproject_version = self._get_version_from_pyproject_toml()

        if pyproject_version != current_version:
            raise VersionError(
                f"The version {pyproject_version} in "
                f"{str(self.project_file_path)} doesn't match the current "
                f"version {current_version}."
            )

        if version_str != 'current':
            provided_version = strip_version(version_str)
            if provided_version != current_version:
                raise VersionError(
                    f"Provided version {provided_version} does not match the "
                    f"current version {current_version}."
                )

        self._print('OK')

    def update_version(
        self, new_version: str, *, develop: bool = False, force: bool = False
    ) -> None:

        new_version = safe_version(new_version)
        if check_develop(new_version) and develop:
            develop = False
        if develop:
            new_version = f'{new_version}.dev1'

        pyproject_version = self._get_version_from_pyproject_toml()

        if not self.version_file_path.exists():
            self.version_file_path.touch()
        elif not force and versions_equal(
            new_version, self.get_current_version()
        ):
            self._print('Version is already up-to-date.')
            return

        self._update_pyproject_version(new_version=new_version)

        self._update_version_file(new_version=new_version)

        self._print(
            f'Updated version from {pyproject_version} to {new_version}'
        )
