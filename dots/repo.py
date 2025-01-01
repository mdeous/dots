# coding: utf-8
import os
import platform
import shutil
from argparse import Namespace
from configparser import ConfigParser
from fnmatch import fnmatch

from dots.logger import Logger

from git import Repo

HOME = os.path.expanduser('~')


class DotRepository:
    """
    The `dots` repository object. Abstracts operations to the repository.
    """
    def __init__(self, cfg: ConfigParser, verbose: bool=False):
        self.hostname = platform.node()
        self.git_repo = None
        self.log = Logger(verbose=verbose)

        # load configuration
        self.log.debug('Loading configuration file')
        section = cfg[self.hostname] if self.hostname in cfg else cfg['DEFAULT']
        self.path = os.path.abspath(os.path.expanduser(section['repo_dir']))
        self.ignored_files = section['ignored_files'].split(',')

    def check_repo(self):
        """
        Checks if the repository structure is valid, outputs an error and exits otherwise.
        """
        if not os.path.exists(self.path):
            self.log.error(f"No dots repository found at '{self.path}'")
        if not os.path.exists(os.path.join(self.path, '.git')):
            self.log.error("Corrupted repository, folder exists but is not versioned")
        self.git_repo = Repo(self.path)

    def rm_empty_folders(self, leaf: str):
        """
        Recursively (bottom-up) delete empty directories
        :param leaf: path from which deletion should start
        """
        if not os.listdir(leaf):
            if not self.log.ask_yesno(f"Delete empty folder '{leaf}'?", default='y'):
                return
            self.log.debug(f'Deleting empty folder: {leaf}')
            os.rmdir(leaf)
            self.rm_empty_folders(os.path.split(leaf)[0])

    def git_commit(self, msg: str):
        """
        Adds repository changes to Git and commits.
        :param msg: commit message
        """
        self.git_repo.git.add(all=True)
        self.git_repo.git.commit(message=f'[dots] {msg}')

    def add_file(self, target_file: str):
        """
        Adds a file to the repository.
        :param target_file: path of the file to add
        """
        self.log.debug(f"Adding '{target_file}' to the repository...")
        # check if file exists
        if not os.path.exists(target_file):
            self.log.error(f'File not found: {target_file}')
        if os.path.islink(target_file):
            if os.path.realpath(target_file).startswith(self.path):
                self.log.error(f'File is already in the repository: {target_file}')
            else:
                self.log.error(f'Can not add link file: {target_file}')

        # check if file is in a subfolder of the home directory
        if not target_file.startswith(HOME):
            self.log.error(f'File is not in a subfolder of {HOME}')
        if target_file.startswith(self.path):
            self.log.error("Files inside the repository can't be added")

        # generate paths
        repo_relpath = target_file.replace(HOME, '')[1:]
        filename = os.path.split(target_file)[1]
        repo_subdirs = os.path.split(repo_relpath)[0].split(os.path.sep)
        repo_dir = os.path.join(self.path, *repo_subdirs)
        repo_file = os.path.join(repo_dir, filename)

        # move file into the repository and create symlink
        if not os.path.exists(repo_dir):
            self.log.debug(f'Creating folder: {repo_dir}')
            os.makedirs(repo_dir)
        self.log.debug('Moving {} to {}'.format(target_file, repo_file))
        shutil.move(target_file, repo_file)
        self.log.debug('Creating symlink')
        os.symlink(repo_file, target_file)

        # add new file to Git
        self.log.debug('Adding new file to Git')
        self.git_commit(f'add {target_file}')
        self.log.info(f'File added: {target_file}')

    def cmd_init(self, _args):
        """
        Initializes the dots repository.
        """
        self.log.debug('Initializing repository...')
        # check if a repository already exists
        if os.path.exists(self.path):
            self.log.warning(f"Folder already exists: {self.path}")
            if self.log.ask_yesno('Overwrite existing repository?', default='n'):
                shutil.rmtree(self.path)
                self.log.debug(f"Creating folder: {self.path}")
                os.mkdir(self.path)
            else:
                return
        self.log.debug('Initializing git repository')
        self.git_repo = Repo.init(self.path)
        self.log.debug(f'Creating new branch: {self.hostname}')
        self.git_repo.head.reference = self.git_repo.create_head(self.hostname, 'HEAD')
        assert not self.git_repo.head.is_detached
        self.git_repo.head.reset(index=True, working_tree=True)

    def cmd_list(self, args: Namespace):
        """
        Lists repository content.
        :param args: command-line arguments
        """
        self.log.debug('Listing repository content...')
        # TODO: show files as a tree
        self.cmd_sync(args, list_only=True)

    def cmd_add(self, args: Namespace):
        """
        Adds a new file to the repository.
        :param args: command-line arguments
        """
        self.check_repo()
        self.add_file(args.file)

    def cmd_rm(self, args: Namespace):
        """
        Removes a file from the repository.
        :param args: command-line arguments
        """
        self.log.debug(f"Removing '{args.file}' from the repository...")
        self.check_repo()

        # check if file is inside the repository and if original file is indeed a symlink
        filepath = os.path.realpath(args.file)
        if not filepath.startswith(self.path):
            self.log.error(f'Not a repository file: {args.file}')
        orig_path = filepath.replace(self.path, HOME)
        if not os.path.islink(orig_path):
            self.log.error(f'Original file path is not a symlink: {orig_path}')

        # move file to its original location
        self.log.debug(f'Deleting symlink: {orig_path}')
        os.unlink(orig_path)
        self.log.debug('Moving file to its original location')
        shutil.move(filepath, orig_path)

        # check for empty dirs to remove
        self.rm_empty_folders(os.path.split(filepath)[0])
        self.log.debug('Removing file from Git')
        self.git_commit(f'remove {args.file}')
        self.log.info(f'File removed: {args.file}')

    def cmd_sync(self, args: Namespace, list_only: bool=False):
        """
        Synchronizes repository content (adds missing symlinks and warns about conflicts).
        :param args: command-line arguments
        :param list_only: only list repository content (do not fix unsynced files)
        """
        def force_add(file_path: str, link_path: str):
            self.log.debug(f'Deleting existing repository file: {file_path}')
            os.unlink(file_path)
            self.add_file(link_path)
        def force_link(file_path: str, link_path: str):
            self.log.debug(f'Deleting local file: {link_path}')
            os.unlink(link_path)
            os.symlink(file_path, link_path)
            self.log.info(f'Replaced local file: {link_path}')

        self.check_repo()
        if not list_only:
            self.log.debug('Synchronizing repository files...')
        for curdir, dirs, files in os.walk(self.path):
            if '.git' in dirs:
                dirs.remove('.git')
            for f in files:
                ignore_file = False
                repo_path = os.path.join(curdir, f).replace(self.path, '')
                for ignored in self.ignored_files:
                    if ignored.startswith('/'):
                        f = os.path.join(repo_path, f)
                    if fnmatch(f, ignored):
                        self.log.debug('Ignored file ({}): {}'.format(ignored, repo_path[1:]))
                        ignore_file = True
                        break
                if ignore_file:
                    continue
                fpath = os.path.join(curdir, f)
                linkpath = fpath.replace(self.path, HOME)
                if not os.path.exists(linkpath) and not os.path.islink(linkpath):
                    if not list_only:
                        linkdir = os.path.dirname(linkpath)
                        if not os.path.exists(linkdir):
                            os.makedirs(linkdir)
                        os.symlink(fpath, linkpath)
                        self.log.info(f'Installed: {linkpath}')
                    else:
                        self.log.notice(f'Missing: {linkpath}')
                else:
                    if os.path.islink(linkpath):
                        # target path already exists
                        frealpath = os.path.realpath(linkpath)
                        if frealpath != fpath:
                            link_state = 'valid' if os.path.exists(frealpath) else 'broken'
                            self.log.warning(f'Conflict ({link_state} link): {linkpath} -> {frealpath}')
                            if not list_only:
                                if not args.force_relink:
                                    if not self.log.ask_yesno('Overwrite existing link?', default='n'):
                                        continue
                                os.unlink(linkpath)
                                os.symlink(fpath, linkpath)
                                self.log.info(f'Replaced link: {linkpath}')
                        else:
                            self.log.info(f'OK: {linkpath}')
                    else:
                        # target path is a regular file
                        self.log.warning(f'Conflict (file exists): {linkpath}')
                        if not list_only:
                            if args.force_add:
                                force_add(fpath, linkpath)
                            elif args.force_link:
                                force_link(fpath, linkpath)
                            else:
                                if self.log.ask_yesno('Replace repository file?', default='n'):
                                    force_add(fpath, linkpath)
                                    continue
                                if self.log.ask_yesno('Replace local file?', default='n'):
                                    force_link(fpath, linkpath)
                                    continue
