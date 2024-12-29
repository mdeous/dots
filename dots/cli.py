# coding: utf-8

from argparse import ArgumentParser
from configparser import ConfigParser
import os.path

from dots import VERSION
from dots.logger import logger
from dots.repo import DotRepository


def parse_args():
    parser = ArgumentParser(description='Configuration files management tool.')
    parser.add_argument(
        '-c', '--config',
        help='configuration file (default: ~/.dots.conf)',
        default='~/.dots.conf'
    )
    parser.add_argument(
        '--repo-dir',
        help='custom repository path',
        metavar='DIR'
    )
    parser.add_argument(
        '-V', '--version',
        help='display program version and exit',
        action='store_true'
    )
    parser.add_argument(
        '-v', '--verbose',
        help='display debug information (default: false)',
        action='store_true'
    )
    subparsers = parser.add_subparsers(help='command help')

    parser_init = subparsers.add_parser('init', help='initialize dots repository')
    parser_init.set_defaults(func='init')

    parser_list = subparsers.add_parser('list', help='list repository content')
    parser_list.set_defaults(func='list')

    parser_add = subparsers.add_parser('add', help='add file to the repository')
    parser_add.set_defaults(func='add')
    parser_add.add_argument(
        'file',
        help='path of the file to add'
    )
    parser_add.add_argument(
        '-e', '--encrypted',
        help='encrypt file for versioning (default: false)',
        action='store_true'
    )

    parser_rm = subparsers.add_parser('rm', help='remove file from the repository')
    parser_rm.set_defaults(func='rm')
    parser_rm.add_argument(
        'file',
        help='path of the file to remove'
    )

    parser_sync = subparsers.add_parser('sync', help='synchronize config and repo files')
    parser_sync.set_defaults(func='sync')
    parser_sync.add_argument(
        '-f', '--force',
        help='overwrite possibly existing files (default: false)',
        action='store_true'
    )

    args = parser.parse_args()
    if args.version:
        print('dots {}'.format(VERSION))
        exit(0)
    if not hasattr(args, 'func'):
        # show help if no command was given
        parser.print_help()
        exit(1)
    if args.verbose:
        logger.verbose = True
    if hasattr(args, 'file'):
        args.file = os.path.abspath(os.path.expanduser(args.file))
    return args


def main():
    args = parse_args()
    cfg = ConfigParser(defaults={
        'repo_dir': '~/dots',
        'gpg_key_id': '',
        'ignored_files': ''
    })
    cfg.read(args.config)
    repo = DotRepository(cfg)
    method_name = 'cmd_{}'.format(args.func)
    method_obj = getattr(repo, method_name)
    method_obj(args)


if __name__ == "__main__":
    main()
