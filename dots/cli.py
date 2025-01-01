# coding: utf-8

from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter, Namespace
from configparser import ConfigParser
import os.path

from dots import VERSION
from dots.repo import DotRepository


def parse_args() -> Namespace:
    parser = ArgumentParser(
        description='Configuration files management tool.',
        formatter_class=ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        '-c', '--config',
        help='configuration file',
        default='~/.dots.conf'
    )
    parser.add_argument(
        '-V', '--version',
        help='display program version and exit',
        action='store_true'
    )
    parser.add_argument(
        '-v', '--verbose',
        help='display debug information',
        action='store_true'
    )
    subparsers = parser.add_subparsers(help='command help')

    parser_init = subparsers.add_parser('init', help='initialize dots repository')
    parser_init.set_defaults(func='init')

    parser_add = subparsers.add_parser('add', help='add file to the repository')
    parser_add.set_defaults(func='add')
    parser_add.add_argument(
        'file',
        help='path of the file to add'
    )

    parser_rm = subparsers.add_parser('rm', help='remove file from the repository')
    parser_rm.set_defaults(func='rm')
    parser_rm.add_argument(
        'file',
        help='path of the file to remove'
    )

    parser_list = subparsers.add_parser('list', help='list repository content')
    parser_list.set_defaults(func='list')

    parser_sync = subparsers.add_parser('sync', help='synchronize config and repo files')
    parser_sync.set_defaults(func='sync')
    parser_sync.add_argument(
        '-r', '--force-relink',
        help='if a link points to another file, overwrite it without asking',
        action='store_true'
    )
    parser_file_exists = parser_sync.add_mutually_exclusive_group()
    parser_file_exists.add_argument(
        '-a', '--force-add',
        help='if a file already exists, overwrite the repository version without asking',
        action='store_true'
    )
    parser_file_exists.add_argument(
        '-l', '--force-link',
        help='If a file already exists, overwrite the local version without asking',
        action='store_true'
    )

    args = parser.parse_args()
    if args.version:
        print(f'dots {VERSION}')
        exit(0)
    if not hasattr(args, 'func'):
        # show help if no command was provided
        parser.print_help()
        exit(1)
    if hasattr(args, 'file'):
        args.file = os.path.abspath(os.path.expanduser(args.file))
    return args


def main():
    args = parse_args()
    cfg = ConfigParser(defaults={
        'repo_dir': '~/dots',
        'ignored_files': ''
    })
    cfg.read(args.config)
    repo = DotRepository(cfg, verbose=args.verbose)
    method_name = f'cmd_{args.func}'
    method_obj = getattr(repo, method_name)
    method_obj(args)


if __name__ == "__main__":
    main()
