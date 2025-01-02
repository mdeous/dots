# coding: utf-8

COLORS = {
    'green': '\033[22;32m',
    'boldgreen': '\033[01;32m',
    'boldblue': '\033[01;34m',
    'purple': '\033[22;35m',
    'red': '\033[22;31m',
    'boldred': '\033[01;31m',
    'normal': '\033[0;0m'
}


class Logger:
    def __init__(self, verbose: bool=False):
        self.verbose = verbose

    @staticmethod
    def _print_msg(msg: str, color: str=None):
        if color is None or color not in COLORS:
            print(msg)
        else:
            print(f'{COLORS[color]}{msg}\033[0;0m')

    def debug(self, msg: str):
        if self.verbose:
            self._print_msg(msg, 'purple')

    def info(self, msg: str):
        self._print_msg(msg, 'green')

    def notice(self, msg: str):
        self._print_msg(msg, 'boldgreen')

    def warning(self, msg: str):
        self._print_msg(msg, 'red')

    def error(self, msg: str, exitcode: int=255):
        self._print_msg(msg, 'boldred')
        exit(exitcode)

    @staticmethod
    def ask(msg: str):
        question = f'{COLORS["boldblue"]}{msg}\033[0;0m '
        answer = input(question)
        return answer.strip()

    def ask_yesno(self, msg: str, default: str=''):
        valid_answers = {
            'y': True, 'yes': True,
            'n': False, 'no': False
        }
        default = default.lower()
        if default and default not in valid_answers:
            default = ''
        question = f'{msg} ' + '(y/n)'.replace(default, default.upper())
        answer = self.ask(question).lower()
        if answer == '':
            answer = default
        while answer not in valid_answers:
            answer = self.ask(question).lower()
        return valid_answers[answer]
