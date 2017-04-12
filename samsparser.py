import sys
from statemachine import StateMachine
from lxml import etree
import io

try:
    import regex as re

    re_supports_unicode_categories = True
except ImportError:
    import re

    re_supports_unicode_categories = False
    print(
        """Regular expression support for Unicode categories not available.
IDs starting with non-ASCII lowercase letters will not be recognized and
will be treated as titles. Please install Python regex module.

""", file=sys.stderr)



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
        self.stateMachine.add_state("LIST-ITEM", self._list_item)
        self.stateMachine.add_state("NUM-LIST-ITEM", self._num_list_item)
        self.stateMachine.add_state("BLOCK-INSERT", self._block_insert)
        self.stateMachine.add_state("END", None, end_state=1)
        self.stateMachine.set_start("NEW")
        self.current_paragraph = None
        self.doc = DocStructure()
        self.source = None
        self.patterns = {
            'comment': re.compile(r'\s*#.*'),
            'block-start': re.compile(r'(\s*)([a-zA-Z0-9-_]+):(?:\((.*?)\))?(.*)'),
            'codeblock-start': re.compile(r'(\s*)```(.*)'),
            'codeblock-end': re.compile(r'(\s*)```\s*$'),
            'paragraph-start': re.compile(r'\w*'),
            'blank-line': re.compile(r'^\s*$'),
            'record-start': re.compile(r'\s*[a-zA-Z0-9-_]+::(.*)'),
            'list-item': re.compile(r'(\s*)(\*\s+)(.*)'),
            'num-list-item': re.compile(r'(\s*)([0-9]+\.\s+)(.*)'),
            'block-insert': re.compile(r'(\s*)>>\(.*?\)\w*')
        }

    def parse(self, source):
        self.source = source
        try:
            self.stateMachine.run(self.source)
        except EOFError:
            raise Exception("Document ended before structure was complete. At:\n\n"
                            + self.current_paragraph)

    def paragraph_start(self, line):
        self.current_paragraph = line.strip()

    def paragraph_append(self, line):
        self.current_paragraph += " " + line.strip()

    def pre_start(self, line):
        self.current_paragraph = line

    def pre_append(self, line):
        self.current_paragraph += line

    def _new_file(self, source):
        line = source.next_line
        if line[:4] == 'sam:':
            self.doc.new_root('sam', line[5:])
            return "SAM", source
        else:
            raise Exception("Not a SAM file!")

    def _block(self, source):
        line = source.currentLine
        match = self.patterns['block-start'].match(line)
        indent = len(match.group(1))
        element = match.group(2).strip()
        attributes = match.group(3)
        content = match.group(4).strip()

        if content[:1] == ':':
            return "RECORD-START", source
        else:
            self.doc.new_block(element, attributes, content, indent)
            return "SAM", source

    def _codeblock_start(self, source):
        line = source.currentLine
        local_indent = len(line) - len(line.lstrip())
        match = self.patterns['codeblock-start'].match(line)
        attributes = re.compile(r'\((.*?)\)').match(match.group(2).strip())
        language = attributes.group(1)
        self.doc.new_block('codeblock', language, None, local_indent)
        self.pre_start('')
        return "CODEBLOCK", source

    def _codeblock(self, source):
        line = source.next_line
        if self.patterns['codeblock-end'].match(line):
            self.doc.add_flow(Pre(self.current_paragraph))
            return "SAM", source
        else:
            self.pre_append(line)
            return "CODEBLOCK", source

    def _paragraph_start(self, source):
        line = source.currentLine
        local_indent = len(line) - len(line.lstrip())
        self.doc.new_block('p', None, '', local_indent)
        self.paragraph_start(line)
        return "PARAGRAPH", source

    def _paragraph(self, source):
        line = source.next_line
        if self.patterns['blank-line'].match(line):
            para_parser.parse(self.current_paragraph, self.doc)
            return "SAM", source
        else:
            self.paragraph_append(line)
            return "PARAGRAPH", source

    def _list_item(self, source):
        line = source.currentLine
        match = self.patterns['list-item'].match(line)
        local_indent = len(match.group(1))
        content_indent = local_indent + len(match.group(2))
        self.doc.new_unordered_list_item(local_indent, content_indent)
        self.paragraph_start(str(match.group(3)).strip())
        return "PARAGRAPH", source


    def _num_list_item(self, source):
        line = source.currentLine
        match = self.patterns['num-list-item'].match(line)
        local_indent = len(match.group(1))
        content_indent = local_indent + len(match.group(2))
        self.doc.new_ordered_list_item(local_indent, content_indent)
        self.paragraph_start(str(match.group(3)).strip())
        return "PARAGRAPH", source

    def _block_insert(self, source):
        line = source.currentLine
        indent = len(source.currentLine) - len(source.currentLine.lstrip())
        attribute_pattern = re.compile(r'\s*>>\((.*?)\)')
        match = attribute_pattern.match(line)
        self.doc.new_block('insert', text='', attributes=parse_insert(match.group(1)), indent=indent)
        return "SAM", source

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
        try:
            line = source.next_line
        except EOFError:
            return "END", source
        if self.patterns['comment'].match(line):
            self.doc.new_comment(Comment(line.strip()[1:]))
            return "SAM", source
        elif self.patterns['block-start'].match(line):
            return "BLOCK", source
        elif self.patterns['blank-line'].match(line):
            return "SAM", source
        elif self.patterns['codeblock-start'].match(line):
            return "CODEBLOCK-START", source
        elif self.patterns['list-item'].match(line):
            return "LIST-ITEM", source
        elif self.patterns['num-list-item'].match(line):
            return "NUM-LIST-ITEM", source
        elif self.patterns['block-insert'].match(line):
            return "BLOCK-INSERT", source
        elif self.patterns['paragraph-start'].match(line):
            return "PARAGRAPH-START", source
        else:
            raise Exception("I'm confused")

    def serialize(self, serialize_format):
        return self.doc.serialize(serialize_format)


class Block:
    def __init__(self, name='', attributes='', content='', indent=0):

        # Test for a valid block name. Must be valid XML name.
        try:
            x = etree.Element(name)
        except ValueError:
            raise Exception("Invalid block name: " + name)

        self.name = name
        self.attributes = attributes
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
        while x.indent >= indent:
            x = x.parent
        b.parent = x
        x.children.append(b)

    def __str__(self):
        return ''.join(self._output_block())

    def _output_block(self):
        yield " " * self.indent
        yield "[%s:'%s'" % (self.name, self.content)
        for x in self.children:
            yield "\n"
            yield str(x)
        yield "]"

    def serialize_xml(self):
        yield '<{0}'.format(self.name)
        if self.children:
            if self.attributes:
                if self.name == 'codeblock':
                    yield ' language="{0}"'.format(self.attributes)
                else:
                    try:
                        yield ' ids="{0}"'.format(' '.join(self.attributes[0]))
                    except (IndexError, TypeError):
                        pass
                    try:
                        yield ' conditions="{0}"'.format(' '.join(self.attributes[1]))
                    except (IndexError, TypeError):
                        pass

            yield ">"

            if self.content:
                    yield "\n<title>{0}</title>".format(self.content)

            if type(self.children[0]) is not Flow:
                yield "\n"

            for x in self.children:
                yield from x.serialize_xml()
            yield "</{0}>\n".format(self.name)
        else:
            yield ">{1}</{0}>\n".format(self.name, self.content)


class Comment(Block):
    def __init__(self, content='', indent=0):
        super().__init__(name='comment', content=content, indent=indent)

    def __str__(self):
        return "[%s:'%s']" % ('#comment', self.content)

    def serialize_xml(self):
        yield '<!-- {0} -->\n'.format(self.content)


class BlockInsert(Block):
    # Should not really inherit from Block as cannot have children, etc
    def __init__(self, content='', indent=0):
        super().__init__(name='insert', content=content, indent=indent)

    def __str__(self):
        return "[%s:'%s']" % ('#insert', self.content)

    def serialize_xml(self):
        yield '<insert type="{0}"'.format(self.content[0])
        yield ' item="{0}"'.format(self.content[1])
        try:
            if self.content[2]:
                yield ' ids="{0}"'.format(' '.join(self.content[2]))
        except IndexError:
            pass
        try:
            if self.content[3]:
                yield ' conditions="{0}"'.format(' '.join(self.content[3]))
        except IndexError:
            pass
        yield '/>\n'


class Root(Block):
    def __init__(self, name='', content='', indent=-1):
        super().__init__(name, None, content, -1)

    def serialize_xml(self):
        yield '<?xml version="1.0" encoding="UTF-8"?>\n'
        yield '<sam>' # should include namespace and schema
        for x in self.children:
            yield from x.serialize_xml()
        yield '</sam>'


class Flow:
    def __init__(self, thing=None):
        self.flow = []
        if thing:
            self.append(thing)

    def __str__(self):
        return "[{0}]".format(''.join([str(x) for x in self.flow]))

    def append(self, thing):
        if not thing == '':
            self.flow.append(thing)

    def serialize_xml(self):
        for x in self.flow:
            try:
                yield from x.serialize_xml()
            except AttributeError:
                yield self._escape_for_xml(x)

    def _escape_for_xml(self, s):
        t = dict(zip([ord('<'), ord('>'), ord('&')], ['&lt;', '&gt;', '&amp;']))
        return s.translate(t)


class StringSource:
    def __init__(self, string_to_parse):
        """

        :param string_to_parse: The string to parse.
        """
        self.current_line = None
        self.current_line_number = 0
        self.buf = io.StringIO(string_to_parse)

    @property
    def next_line(self):
        self.current_line = self.buf.readline()
        if self.current_line == "":
            raise EOFError("End of file")
        self.current_line_number += 1
        return self.current_line


def parse_block_attributes(attributes_string):
    try:
        attributes_list = attributes_string.split()
    except AttributeError:
        return None, None
    ids = [x[1:] for x in attributes_list if x[0] == '#']
    conditions = [x[1:] for x in attributes_list if x[0] == '?']
    unexpected_attributes = [x for x in attributes_list if not(x[0] in '?#')]
    if unexpected_attributes:
        raise Exception("Unexpected insert attribute(s): {0}".format(unexpected_attributes))
    return ids if ids else None, conditions if conditions else None


def parse_insert(insert_string):
    attributes_list = insert_string.split()
    insert_type = attributes_list.pop(0)
    insert_url = attributes_list.pop(0)
    insert_id = [x[1:] for x in attributes_list if x[0] == '#']
    insert_condition = [x[1:] for x in attributes_list if x[0] == '?']
    unexpected_attributes = [x for x in attributes_list if not(x[0] in '?#')]
    if unexpected_attributes:
        raise Exception("Unexpected insert attribute(s): {0}".format(unexpected_attributes))
    return insert_type, \
           insert_url, \
           insert_id if insert_id else None, \
           insert_condition if insert_condition else None

if __name__ == "__main__":
    samParser = SamParser()
    filename = sys.argv[-1]
    try:
        with open(filename, "r") as myfile:
            test = myfile.read()
    except FileNotFoundError:
        test = """samschema:(http://
        this:
            is: a test"""

    samParser.parse(StringSource(test))
    print("".join(samParser.serialize('xml')))
