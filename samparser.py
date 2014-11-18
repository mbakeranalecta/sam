from statemachine import StateMachine
from SamParaParser import SamParaParser
import re
import sys


class SamParser:
    def __init__(self):

        self.stateMachine = StateMachine()
        self.stateMachine.add_state("NEW", self._new_file)
        self.stateMachine.add_state("SAM", self._sam)
        self.stateMachine.add_state("BLOCK", self._block)
        self.stateMachine.add_state("CODEBLOCK-START", self._codeblock_start)
        self.stateMachine.add_state("CODEBLOCK", self._codeblock)
        self.stateMachine.add_state("PARAGRAPH-START", self._paragraph_start)
        self.stateMachine.add_state("PARAGRAPH", self._paragraph)
        self.stateMachine.add_state("RECORD-START", self._record_start)
        self.stateMachine.add_state("RECORD", self._record)
        self.stateMachine.add_state("LIST-START", self._list_start)
        self.stateMachine.add_state("LIST", self._list_continue)
        self.stateMachine.add_state("NUM-LIST-START", self._num_list_start)
        self.stateMachine.add_state("NUM-LIST", self._num_list_continue)
        self.stateMachine.add_state("END", None, end_state=1)
        self.stateMachine.set_start("NEW")

        self.doc = DocStructure()
        self.source = None
        self.patterns = {
            'comment': re.compile('\s*#.*'),
            'block-start': re.compile('(\s*)([a-zA-Z0-9-_]+):(.*)'),
            'codeblock-start': re.compile('(\s*)```(.*)'),
            'codeblock-end': re.compile('(\s*)```\s*$'),
            'paragraph-start': re.compile('\w*'),
            'blank-line': re.compile('^\s*$'),
            'record-start': re.compile('\s*[a-zA-Z0-9-_]+::(.*)'),
            'list-item': re.compile('(\s*)\*\s(.*)'),
            'num-list-item': re.compile('(\s*)[0-9]+\.\s(.*)')
        }

    def parse(self, source):
        self.source = Source(source)
        self.stateMachine.run(self.source)

    def _new_file(self, source):
        line = source.next_line
        if line[:4] == 'sam:':

            return "SAM", source
        else:
            raise Exception("Not a SAM file!")

    def _block(self, source):
        line = source.currentLine
        match = self.patterns['block-start'].match(line)
        local_indent = len(match.group(1))
        local_element = match.group(2).strip()
        local_content = match.group(3).strip()

        if local_content[:1] == ':':
            return "RECORD-START", source
        else:
            self.doc.new_block(local_element, local_content, local_indent)
            return "SAM", source

    def _codeblock_start(self, source):
        line = source.currentLine
        local_indent = len(line) - len(line.lstrip(' '))
        match = self.patterns['codeblock-start'].match(line)
        language = match.group(2).strip()
        self.doc.new_block('codeblock', '', local_indent)
        return "CODEBLOCK", source

    def _codeblock(self, source):
        line = source.next_line
        if self.patterns['codeblock-end'].match(line):
            return "SAM", source
        else:
            return "CODEBLOCK", source

    def _paragraph_start(self, source):
        line = source.currentLine
        local_indent = len(line) - len(line.lstrip(' '))
        self.doc.new_block('p', '', local_indent)
        self.doc.paragraph_start(line)
        return "PARAGRAPH", source

    def _paragraph(self, source):
        line = source.next_line
        if self.patterns['blank-line'].match(line):

            para_parser = SamParaParser(self.doc.currentParagraph)
            para_parser.parse()
            #self.__process_paragraph(self.doc.currentParagraph)

            return "SAM", source
        else:
            self.doc.paragraph_append(line)
            return "PARAGRAPH", source

    def _list_start(self, source):
        line = source.currentLine
        local_indent = len(line) - len(line.lstrip(' '))
        self.doc.new_block('ul', '', local_indent)
        match = self.patterns['list-item'].match(line)
        self.doc.new_block('li', 'str(match.group(2)).strip()', local_indent)
        return "LIST", source

    def _list_continue(self, source):
        line = source.next_line
        local_indent = len(line) - len(line.lstrip(' '))
        if self.patterns['blank-line'].match(line):
            return "SAM", source
        elif self.patterns['list-item'].match(line):
            match = self.patterns['list-item'].match(line)
            self.doc.new_block('li', 'str(match.group(2)).strip()', local_indent)
            return "LIST", source
        else:
            raise Exception("Broken list at line " + str(source.currentLineNumber) + " " + source.filename)

    def _num_list_start(self, source):
        line = source.currentLine
        local_indent = len(line) - len(line.lstrip(' '))
        self.doc.new_block('ul', '', local_indent)
        match = self.patterns['num-list-item'].match(line)
        self.doc.new_block('li', 'str(match.group(2)).strip()', local_indent)
        return "NUM-LIST", source

    def _num_list_continue(self, source):
        line = source.next_line
        local_indent = len(line) - len(line.lstrip(' '))
        if self.patterns['blank-line'].match(line):
            return "SAM", source
        elif self.patterns['num-list-item'].match(line):
            match = self.patterns['num-list-item'].match(line)
            self.doc.new_block('li', 'str(match.group(2)).strip()', local_indent)
            return "NUM-LIST", source
        else:
            raise Exception("Broken num list at line " + str(source.currentLineNumber) + " " + source.filename)

    def _record_start(self, source):
        line = source.currentLine
        match = self.patterns['block-start'].match(line)
        local_indent = len(match.group(1))
        local_element = match.group(2).strip()
        field_names = [x.strip() for x in self.patterns['record-start'].match(line).group(1).split(',')]
        self.doc.new_record_set(local_element, field_names, local_indent)
        return "RECORD", source

    def _record(self, source):
        line = source.next_line
        if self.patterns['blank-line'].match(line):
            return "SAM", source
        else:
            field_values = [x.strip() for x in line.split(',')]
            record = list(zip(self.doc.fields, field_values))
            self.doc.new_record(record)
            return "RECORD", source

    def _sam(self, source):
        line = source.next_line
        if line == "":
            return "END", source
        elif self.patterns['comment'].match(line):
            print('<!--' + line.strip()[1:] + '-->')
            return "SAM", source
        elif self.patterns['block-start'].match(line):
            return "BLOCK", source
        elif self.patterns['blank-line'].match(line):
            print()
            return "SAM", source
        elif self.patterns['codeblock-start'].match(line):
            return "CODEBLOCK-START", source
        elif self.patterns['list-item'].match(line):
            return "LIST-START", source
        elif self.patterns['num-list-item'].match(line):
            return "NUM-LIST-START", source
        elif self.patterns['paragraph-start'].match(line):
            return "PARAGRAPH-START", source
        elif line != "":
            print('*NOT MATCHED* ' + line, end='')
            return "SAM", source
        else:
            raise Exception("I'm confused")

    def _process_paragraph(self, paragraph):

        parts = self.patterns['annotation'].split(paragraph)
        for part in parts:
            p = self.patterns['annotation-split'].match(part)
            if p is None:
                print(part, end="")
            else:
                print('<annotation type="' + str(p.group(2)).strip() + '">' + p.group(1) + '</annotation>', end="")


class Element:
    def __init__(self, name, attributes=None):
        self.name = name
        assert isinstance(attributes, dict)
        self.attributes = attributes

class Block:
    def __init__(self, name, content, indent):
        self.name = name
        self.content = content
        self.indent = indent
        self.parent = None
        self.children = []

    def add_child(self, b):
        b.parent = self
        self.children.append(b)

    def add_sibling(self, b):
        b.parent = self.parent
        self.parent.children.append(b)

    def add_at_indent(self, b, indent):
        x = self.parent
        while x.indent > indent:
            x = x.parent
        b.parent = x.parent
        x.children.append(b)

    def __str__(self):
        return ''.join(self._output_block())

    def _output_block(self):
        yield " " * self.indent
        yield "[%s:'%s'" % (self.name, self.content)
        for x in self.children:
            yield "\n"
            yield ''.join(x._output_block())
        yield "]"



class DocStructure:
    def __init__(self):
        self.doc = None
        self.fields = None
        self.current_record = None
        self.current_paragraph = None
        self.current_block = None

    def new_block(self, block_type, text, indent):
        b = Block(block_type, text, indent)
        if self.doc is None:
            self.doc = b
        elif self.current_block.indent < indent:
            self.current_block.add_child(b)
        elif self.current_block.indent == indent:
            self.current_block.add_sibling(b)
        else:
            self.current_block.add_at_indent(b, indent)
        self.current_block = b
        print(self.doc)
        print('-----------------------------------------------------')

    def new_record_set(self, local_element, field_names, local_indent):
        self.current_record = {'local_element': local_element, 'local_indent': local_indent}
        self.fields = field_names

    def new_record(self, record):
        b = Block(self.current_record['local_element'], '', self.current_record['local_indent'])
        self.current_block.add_child(b)
        self.current_block = b
        for name, content in record:
            b = Block(name, content, self.current_block.indent+4)
            self.current_block.add_child(b)


    @property
    def current_element(self):
        if not self.elements:
            return None
        else:
            return self.elements[-1]['element']

    @property
    def current_indent(self):
        if not self.stack[-1]['indent']:
            return -1
        else:
            return self.stack[-1]["indent"]

    def paragraph_start(self, line):
        self.currentParagraph = line.strip()

    def paragraph_append(self, line):
        self.currentParagraph += " " + line.strip()


class Source:
    def __init__(self, filename):
        """

        :param filename: The filename of the source to parse.
        """
        self.filename = filename
        self.sourceFile = open(filename, encoding='utf-8')
        self.currentLine = None
        self.currentLineNumber = 0

    @property
    def next_line(self):
        self.currentLine = self.sourceFile.readline()
        self.currentLineNumber += 1
        return self.currentLine


if __name__ == "__main__":
    samParser = SamParser()
    filename = sys.argv[-1]
    samParser.parse(filename)