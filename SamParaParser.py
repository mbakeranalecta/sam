from statemachine import StateMachine
import re


class SamParaParser:
    def __init__(self, para):

        self.para = Para(para)
        self.stateMachine = StateMachine()
        self.stateMachine.add_state("PARA", self._para)
        self.stateMachine.add_state("ESCAPE", self._escape)
        self.stateMachine.add_state("END", None, end_state=1)
        self.stateMachine.add_state("ANNOTATION-START", self._annotation_start)
        self.stateMachine.add_state("BOLD-START", self._bold_start)
        self.stateMachine.add_state("ITALIC-START", self._italic_start)
        self.stateMachine.set_start("PARA")
        self.patterns = {
            'escape': re.compile('\\\\'),
            'escaped-chars': re.compile('[\\\\\[\(\]]'),
            'annotation': re.compile('\[([^\[]*[^\\\\])\]\(([^\(]*[^\\\\])\)'),
            'bold': re.compile('\*(\S.+?\S)\*'),
            'italic': re.compile('_(\S.*\S)_')
        }

    def parse(self):
        self.stateMachine.run(self.para)

    @staticmethod
    def _para(para):
        try:
            char = para.next_char
        except IndexError:
            return "END", para
        if char == '\\':
            return "ESCAPE", para
        elif char == '[':
            return "ANNOTATION-START", para
        elif char == "*":
            return "BOLD-START", para
        elif char == "_":
            return "ITALIC-START", para
        else:
            print(char, end='')
            return "PARA", para

    def _annotation_start(self, para):
        match = self.patterns['annotation'].match(para.rest_of_para)
        if match:
            print('<annotation type="' + str(match.group(2)).strip() + '">' + match.group(1) + '</annotation>', end="")
            para.advance(len(match.group(0)) - 1)
            return "PARA", para
        else:
            print('[', end='')
            return "PARA", para

    def _bold_start(self, para):
        match = self.patterns['bold'].match(para.rest_of_para)
        if match:
            print('<bold>' + match.group(1) + '</bold>', end="")
            para.advance(len(match.group(0)) - 1)
        else:
            print('*', end='')
        return "PARA", para

    def _italic_start(self, para):
        match = self.patterns['italic'].match(para.rest_of_para)
        if match:
            print('<italic>' + match.group(1) + '</italic>', end="")
            para.advance(len(match.group(0)) - 1)
        else:
            print('_', end='')
        return "PARA", para

    def _escape(self, para):
        char = para.next_char
        if self.patterns['escaped-chars'].match(char):
            print(char, end='')
        else:
            print('\\' + char, end='')
        return "PARA", para


class Para:
    def __init__(self, para):
        self.para = para
        self.currentCharNumber = -1

    @property
    def next_char(self):
        self.currentCharNumber += 1
        return self.para[self.currentCharNumber]

    @property
    def current_char(self):
        return self.para[self.currentCharNumber]

    @property
    def rest_of_para(self):
        return self.para[self.currentCharNumber:]

    def advance(self, count):
        self.currentCharNumber += count
