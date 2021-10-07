# Copyright (C) 2019-2021 Greenbone Networks GmbH
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

"""Script to update the year of last modification
in the license header of source code files.\n
Also it appends a header if it is missing in the file.
"""

import sys
import re

from argparse import ArgumentParser, Namespace, FileType
from datetime import datetime

from subprocess import CalledProcessError, run
from typing import Dict, List, Tuple, Union
from pathlib import Path

from pontos.terminal import _set_terminal, error, warning, info, ok
from pontos.terminal.terminal import Terminal

SUPPORTED_FILE_TYPES = [
    ".bash",
    ".c",
    ".h",
    ".go",
    ".cmake",
    ".js",
    ".nasl",
    ".po",
    ".py",
    ".sh",
    ".txt",
    ".xml",
    ".xsl",
]
SUPPORTED_LICENCES = [
    "AGPL-3.0-or-later",
    "GPL-2.0-only",
    "GPL-2.0-or-later",
    "GPL-3.0-or-later",
]


def _get_modified_year(f: Path) -> str:
    """In case of the changed arg, update year to last modified year"""
    try:
        cmd = ["git", "log", "-1", "--format=%ad", "--date=format:%Y", str(f)]
        proc = run(
            cmd,
            text=True,
            capture_output=True,
            check=True,
            universal_newlines=True,
        )
        return proc.stdout.rstrip()
    except CalledProcessError as e:
        raise e


def _find_copyright(
    line: str,
    regex: re.Pattern,
) -> Tuple[bool, Union[Dict[str, Union[str, None]], None]]:
    """Match the line for the regex"""
    copyright_match = re.search(regex, line)
    if copyright_match:
        return (
            True,
            {
                "creation_year": copyright_match.group(1),
                "modification_year": copyright_match.group(2),
                "company": copyright_match.group(3),
            },
        )
    return False, None


def _add_header(
    suffix: str, licence: str, company: str, year: str
) -> Union[str, None]:
    """Tries to add the header to the file.
    Requirements:
      - file type must be supported
      - licence file must exist
    """
    if suffix in SUPPORTED_FILE_TYPES:
        root = Path(__file__).parent
        licence_file = root / "templates" / licence / f"template{suffix}"
        try:
            return (
                licence_file.read_text(encoding='utf-8')
                .replace("<company>", company)
                .replace("<year>", year)
            )
        except FileNotFoundError as e:
            raise e
    else:
        raise ValueError


def _update_file(
    file: Path,
    regex: re.Pattern,
    args: Namespace,
) -> None:
    """Function to update the given file.
    Checks if header exists. If not it adds an
    header to that file, else it checks if year
    is up to date
    """

    if args.changed:
        try:
            args.year = _get_modified_year(file)
        except CalledProcessError:
            warning(
                f"{file}: Could not get date of last modification"
                f" using git, using {str(args.year)} instead."
            )

    try:
        with file.open("r+") as fp:
            found = False
            i = 10  # assume that copyright is in the first 10 lines
            while not found and i > 0:
                line = fp.readline()
                if line == "":
                    i = 0
                    continue
                found, copyright_match = _find_copyright(line=line, regex=regex)
                i = i - 1
            if i == 0 and not found:
                try:
                    header = _add_header(
                        file.suffix, args.licence, args.company, args.year
                    )
                    if header:
                        fp.seek(0)  # back to beginning of file
                        rest_of_file = fp.read()
                        fp.seek(0)
                        fp.write(header)
                        fp.write('\n')
                        fp.write(rest_of_file)
                        info(f"{file}: Added licence header.")
                        return 0
                except ValueError:
                    error(
                        f"{file}: No licence header for the"
                        f" format {file.suffix} found.",
                    )
                except FileNotFoundError:
                    error(
                        f"{file}: Licence file for {args.licence} "
                        "is not existing."
                    )
                return 1
            # replace header and write it to file
            if (
                not copyright_match["modification_year"]
                and copyright_match["creation_year"] < args.year
                or copyright_match["modification_year"]
                and copyright_match["modification_year"] < args.year
            ):
                copyright_term = (
                    f'Copyright (C) {copyright_match["creation_year"]}'
                    f'-{args.year} {copyright_match["company"]}'
                )
                new_line = re.sub(regex, copyright_term, line)
                fp_write = fp.tell() - len(line)  # save position to insert
                rest_of_file = fp.read()
                fp.seek(fp_write)
                fp.write(new_line)
                fp.write(rest_of_file)
                info(
                    f"{file}: Changed Licence Header Copyright Year "
                    f'{copyright_match["modification_year"]} -> '
                    f"{args.year}"
                )

                return 0
            else:
                ok(f"{file}: Licence Header is ok.")
                return 0
    except FileNotFoundError as e:
        error(f"{file}: File is not existing.")
        raise e
    except UnicodeDecodeError as e:
        info(f"{file}: Ignoring binary file.")
        raise e


def _get_exclude_list(
    exclude_file: Path, directories: List[Path]
) -> List[Path]:
    """Tries to get the list of excluded files / directories.
    If a file is given, it will be used. Otherwise it will be searched
    in the executed root path.
    The ignore file should only contain relative paths like *.py,
    not absolute as **/*.py
    """

    if exclude_file is None:
        exclude_file = Path(".pontos-header-ignore")
    try:
        exclude_lines = exclude_file.read_text(encoding='utf-8').split('\n')
    except FileNotFoundError:
        print("No exclude list file found.")
        return []

    expanded_globs = [
        directory.rglob(line.strip())
        for directory in directories
        for line in exclude_lines
        if line
    ]

    exclude_list = []
    for glob_paths in expanded_globs:
        for path in glob_paths:
            if path.is_dir():
                for efile in path.rglob('*'):
                    exclude_list.append(efile.absolute())
            else:
                exclude_list.append(path.absolute())

    return exclude_list


def _parse_args(args=None):
    """Parsing the args"""

    parser = ArgumentParser(
        description="Update copyright in source file headers.",
        prog="pontos-update-header",
    )

    date_group = parser.add_mutually_exclusive_group()
    date_group.add_argument(
        "-c",
        "--changed",
        action="store_true",
        default=False,
        help=(
            "Update modified year using git log modified year. \n"
            "This will probably not changed all files to current year!",
        ),
    )
    date_group.add_argument(
        "-y",
        "--year",
        default=str(datetime.now().year),
        help=(
            "If year is set, modified year will be \n"
            "set to the specified year."
        ),
    )

    parser.add_argument(
        "-l",
        "--licence",
        choices=SUPPORTED_LICENCES,
        default="GPL-3.0-or-later",
        help=(
            "Use the passed licence type. Options:\n"
            "* AGPL-3.0-or-later\n* GPL-3.0-or-later\n"
            "* GPL-2.0-or-later\n* GPL-2.0-only"
        ),
    )

    parser.add_argument(
        "--company",
        default="Greenbone Networks GmbH",
        help=(
            "If a header will be added to file, \n"
            "it will be licenced by company."
        ),
    )

    files_group = parser.add_mutually_exclusive_group(required=True)
    files_group.add_argument(
        "-f", "--files", nargs="+", help="Files to update."
    )
    files_group.add_argument(
        "-d",
        "--directories",
        nargs="+",
        help="Directories to find files to update recursively.",
    )

    parser.add_argument(
        "--exclude-file",
        help=(
            "File containing glob patterns for files to"
            " ignore when finding files to update in a directory."
            " Will look for '.pontos-header-ignore' in the directory"
            " if none is given."
            "The ignore file should only contain relative paths like *.py,"
            "not absolute as **/*.py"
        ),
        type=FileType('r'),
    )

    return parser.parse_args(args)


def main() -> None:
    args = _parse_args()
    exclude_list = []

    term = Terminal()
    _set_terminal(term)

    term.bold_info('pontos-update-header -> Updating file headers')

    with term.indent():
        if args.directories:
            if isinstance(args.directories, list):
                directories = [
                    Path(directory) for directory in args.directories
                ]
            else:
                directories = [Path(args.directories)]
            # get file paths to exclude
            exclude_list = _get_exclude_list(args.exclude_file, directories)
            # get files to update
            files = [
                Path(file)
                for directory in directories
                for file in directory.rglob("*")
                if file.is_file()
            ]
        elif args.files:
            if isinstance(args.files, list):
                files = [Path(name) for name in args.files]
            else:
                files = [Path(args.files)]

        else:
            # should never happen
            error("Specify files to update!")
            sys.exit(1)

        regex = re.compile(
            "[Cc]opyright.*?(19[0-9]{2}|20[0-9]{2}) "
            f"?-? ?(19[0-9]{{2}}|20[0-9]{{2}})? ({args.company})"
        )

        for file in files:
            try:
                if file.absolute() in exclude_list:
                    info(f"{file}: Ignoring file from exclusion list.")
                else:
                    _update_file(file=file, regex=regex, args=args)
            except (FileNotFoundError, UnicodeDecodeError, ValueError):
                continue

    return 0


if __name__ == "__main__":
    main()
