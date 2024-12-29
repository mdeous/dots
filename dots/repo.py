# coding: utf-8
import os
import platform
import shutil
from configparser import ConfigParser
from fnmatch import fnmatch

from dots.logger import Logger

from git import Repo


class DotRepository:
    """
    The `dots` repository object. Abstracts operations to the repository.
    """
    homedir = os.path.expanduser('~')

    def __init__(self, cfg: ConfigParser, verbose=False):
        self.hostname = platform.node()
        self.path = ''
        self.gpg_key_id = ''
        self.ignored_files = []
        self.log = Logger(verbose=verbose)
        self.load_config(cfg)
        self.files_path = os.path.join(self.path, 'files')
        self.enc_files_path = os.path.join(self.path, 'encrypted')
        self.git_repo = None

    def load_config(self, cfg: ConfigParser):
        """
        Assigns instance variables according to the configuration.
        :param cfg: a `ConfigParser` object that holds the configuration file content
        :return: None
        """
        self.log.debug('Loading configuration file')
        section = cfg['DEFAULT']
        # use host-specific configuration, if any
        if self.hostname in cfg:
            section = cfg[self.hostname]
        self.path = os.path.abspath(os.path.expanduser(section['repo_dir']))
        self.gpg_key_id = section['gpg_key_id']
        self.ignored_files = section['ignored_files'].split(',')
        self.ignored_files.append('.gitkeep')

    def check_repo(self):
        """
        Checks if the repository structure is valid, outputs an error and exits otherwise.
        :return: None
        """
        if not os.path.exists(self.path):
            self.log.error(f"No dots repository found at '{self.path}'")
        if not os.path.exists(self.files_path):
            self.log.error("Corrupted repository, the 'files' subfolder is missing")
        if not os.path.exists(self.enc_files_path):
            self.log.error("Corrupted repository, the 'encrypted' subfolder is missing")
        if not os.path.exists(os.path.join(self.path, '.git')):
            self.log.error("Corrupted repository, folder exists but is not versioned")
        self.git_repo = Repo(self.path)

    def rm_empty_folders(self, bottom: str):
        """
        Recursively (deepest to shortest) delete empty directories
        :param bottom: path from which deletion should start
        :return: None
        """
        if not os.listdir(bottom):
            if not self.log.ask_yesno(f"Delete empty folder '{bottom}'?", default='y'):
                return
            self.log.debug(f'Deleting empty folder: {bottom}')
            os.rmdir(bottom)
            self.rm_empty_folders(os.path.split(bottom)[0])

    def git_commit(self, msg):
        """
        Adds repository changes to Git and commits.
        :param msg: commit message
        :return: None
        """
        self.git_repo.git.add(all=True)
        self.git_repo.git.commit(message=f'[dots] {msg}')

    def cmd_init(self, _args):
        """
        Initializes the dots repository.
        :return: None
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
        # create .gitignore to avoid tracking decrypted files
        self.log.debug('Adding decrypted files to git ignore list')
        with open(os.path.join(self.path, '.gitignore'), 'a') as ofile:
            ofile.write('encrypted/*.cleartext\n')
        # create repository subfolders
        for dirpath in (self.files_path, self.enc_files_path):
            self.log.debug(f"Creating folder: {dirpath}")
            os.mkdir(dirpath)
            self.log.debug("Adding .gitkeep file")
            with open(os.path.join(dirpath, '.gitkeep'), 'w') as _outf:
                pass
        self.log.debug('Adding new files to Git')
        self.git_commit('initial commit')
        self.log.debug(f'Creating new branch: {self.hostname}')
        self.git_repo.head.reference = self.git_repo.create_head(self.hostname, 'HEAD')
        assert not self.git_repo.head.is_detached
        self.git_repo.head.reset(index=True, working_tree=True)

    def cmd_list(self, args):
        """
        Lists repository content.
        :param args: command-line arguments
        :return: None
        """
        self.log.debug('Listing repository content...')
        # TODO: show files as a tree
        self.cmd_sync(args, list_only=True)

    def cmd_add(self, args):
        """
        Adds a new file to the repository.
        :param args: command-line arguments
        :return: None
        """
        self.log.debug(f"Adding '{args.file}' to the repository...")
        self.check_repo()
        # TODO: implement encryption
        if args.encrypted:
            raise NotImplementedError('encryption is not implemented yet')
        # check if file exists
        if not os.path.exists(args.file):
            self.log.error(f'File not found: {args.file}')
        if os.path.islink(args.file):
            if os.path.realpath(args.file).startswith(self.files_path):
                self.log.error(f'File is already in the repository: {args.file}')
            else:
                self.log.error(f'Can not add link file: {args.file}')
        # check if file is in a subfolder of the home directory
        if not args.file.startswith(self.homedir):
            self.log.error(f'File is not in a subfolder of {self.homedir}')
        if args.file.startswith(self.path):
            self.log.error("Files inside the repository can't be added")
        # generate paths
        repo_relpath = args.file.replace(self.homedir, '')[1:]
        filename = os.path.split(args.file)[1]
        repo_subdirs = os.path.split(repo_relpath)[0].split(os.path.sep)
        repo_dir = os.path.join(self.files_path, *repo_subdirs)
        repo_file = os.path.join(repo_dir, filename)
        # move file into the repository and create symlink
        if not os.path.exists(repo_dir):
            self.log.debug(f'Creating folder: {repo_dir}')
            os.makedirs(repo_dir)
        self.log.debug('Moving {} to {}'.format(args.file, repo_file))
        shutil.move(args.file, repo_file)
        self.log.debug('Creating symlink')
        os.symlink(repo_file, args.file)
        # add new file to Git
        self.log.debug('Adding new file to Git')
        self.git_commit(f'add {args.file}')
        self.log.info(f'File added: {args.file}')

    def cmd_rm(self, args):
        """
        Removes a file from the repository.
        :param args: command-line arguments
        :return: None
        """
        self.log.debug(f"Removing '{args.file}' from the repository...")
        self.check_repo()
        # check if file is inside the repository and if original file is indeed a symlink
        filepath = os.path.realpath(args.file)
        if not filepath.startswith(self.files_path):
            self.log.error(f'Not a repository file: {args.file}')
        orig_path = filepath.replace(self.files_path, self.homedir)
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

    def cmd_sync(self, args, list_only=False):
        """
        Synchronizes repository content (adds missing symlinks and warns about conflicts).
        :param args: command-line arguments
        :param list_only: only list repository content (do not fix unsynced files)
        :return: None
        """
        if not list_only:
            self.log.debug('Synchronizing repository files...')
        for curdir, dirs, files in os.walk(self.files_path):
            for f in files:
                ignore_file = False
                repo_path = os.path.join(curdir, f).replace(self.files_path, '')
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
                linkpath = fpath.replace(self.files_path, self.homedir)
                if not os.path.exists(linkpath) and not os.path.islink(linkpath):
                    if not list_only:
                        linkdir = os.path.dirname(linkpath)
                        if not os.path.exists(linkdir):
                            os.makedirs(linkpath)
                        os.symlink(fpath, linkpath)
                        self.log.info(f'Synced: {linkpath}')
                    else:
                        self.log.notice(f'Not synced: {linkpath}')
                else:
                    if os.path.islink(linkpath):
                        # target path already exists
                        frealpath = os.path.realpath(linkpath)
                        if frealpath != fpath:
                            self.log.warning('Conflict (wrong link): {} -> {}'.format(linkpath, frealpath))
                            if not list_only:
                                if not args.force:
                                    if not self.log.ask_yesno('Overwrite existing link?', default='n'):
                                        continue
                                self.log.debug(f'Installing link in place of existing link: {linkpath}')
                                os.unlink(linkpath)
                                os.symlink(fpath, linkpath)
                        else:
                            self.log.info(f'OK: {linkpath}')
                    else:  # linkpath is a regular file
                        self.log.warning(f'Conflict (file already exists): {linkpath}')
                        if not list_only:
                            if not args.force:
                                if not self.log.ask_yesno('Overwrite existing file?', default='n'):
                                    continue
                            self.log.debug(f'Installing link in place of existing file: {linkpath}')
                            os.unlink(linkpath)
                            os.symlink(fpath, linkpath)
