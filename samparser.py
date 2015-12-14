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
        self.stateMachine.add_state("BLOCKQUOTE-START", self._blockquote_start)
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
            'block-start': re.compile(r'(?P<indent>\s*)(?P<element>[a-zA-Z0-9-_]+):(?P<attributes>\((.*?)\))?(?P<content>.*)'),
            'codeblock-start': re.compile(r'(?P<indent>\s*)```\((?P<attributes>.*?)\)'),
            'codeblock-end': re.compile(r'(\s*)```\s*$'),
            'blockquote-start': re.compile(r'(?P<indent>\s*)((""")|(\'\'\'))(\((?P<citation>.*)\))?'),
            'paragraph-start': re.compile(r'\w*'),
            'blank-line': re.compile(r'^\s*$'),
            'record-start': re.compile(r'(?P<indent>\s*)(?P<record_name>[a-zA-Z0-9-_]+)::(?P<field_names>.*)'),
            'list-item': re.compile(r'(?P<indent>\s*)(?P<marker>\*\s+)(?P<content>.*)'),
            'num-list-item': re.compile(r'(?P<indent>\s*)(?P<marker>[0-9]+\.\s+)(?P<content>.*)'),
            'block-insert': re.compile(r'(?P<indent>\s*)>>\((?P<attributes>.*?)\)\w*')
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
            return "SAM", (source, None)
        else:
            raise Exception("Not a SAM file!")

    def _block(self, context):
        source, match = context
        line = source.currentLine
        indent = len(match.group("indent"))
        element = match.group("element").strip()
        attributes = match.group("attributes")
        content = match.group("content").strip()
        self.doc.new_block(element, attributes, content, indent)
        return "SAM", context

    def _codeblock_start(self, context):
        source, match = context
        line = source.currentLine
        indent = len(match.group("indent"))
        # FIXME: Does codeblock allow other attributes? If not, test?
        language = match.group("attributes").strip()
        self.doc.new_block('codeblock', language, None, indent)
        self.pre_start('')
        return "CODEBLOCK", context

    def _codeblock(self, context):
        source, match = context
        line = source.next_line
        if self.patterns['codeblock-end'].match(line):
            self.doc.new_flow(Pre(self.current_paragraph))
            return "SAM", context
        else:
            self.pre_append(line)
            return "CODEBLOCK", context

    def _blockquote_start(self, context):
        source, match = context
        citation = match.group("citation")
        indent = len(match.group('indent'))
        self.doc.new_block('blockquote', citation, None, indent)
        return "SAM", context

    def _paragraph_start(self, context):
        source, match = context
        line = source.currentLine
        local_indent = len(line) - len(line.lstrip())
        self.doc.new_block('p', None, '', local_indent)
        self.paragraph_start(line)
        return "PARAGRAPH", context

    def _paragraph(self, context):
        source, match = context
        line = source.next_line
        if self.patterns['blank-line'].match(line):
            para_parser.parse(self.current_paragraph, self.doc)
            return "SAM", context
        else:
            self.paragraph_append(line)
            return "PARAGRAPH", context

    def _list_item(self, context):
        source, match = context
        line = source.currentLine
        indent = len(match.group("indent"))
        content_indent = indent + len(match.group("marker"))
        self.doc.new_unordered_list_item(indent, content_indent)
        self.paragraph_start(str(match.group("content")).strip())
        return "PARAGRAPH", context

    def _num_list_item(self, context):
        source, match = context
        line = source.currentLine
        indent = len(match.group("indent"))
        content_indent = indent + len(match.group("marker"))
        self.doc.new_ordered_list_item(indent, content_indent)
        self.paragraph_start(str(match.group("content")).strip())
        return "PARAGRAPH", context

    def _block_insert(self, context):
        source, match = context
        indent = len(match.group("indent"))
        self.doc.new_block('insert', text='', attributes=parse_insert(match.group("attributes")), indent=indent)
        return "SAM", context

    def _record_start(self, context):
        source, match = context
        line = source.currentLine
        indent = len(match.group("indent"))
        record_name = match.group("record_name").strip()
        field_names = [x.strip() for x in match.group("field_names").split(',')]
        self.doc.new_record_set(record_name, field_names, indent)
        return "RECORD", context

    def _record(self, context):
        source, match = context
        line = source.next_line
        if self.patterns['blank-line'].match(line):
            return "SAM", context
        else:
            field_values = [x.strip() for x in line.split(',')]
            record = list(zip(self.doc.fields, field_values))
            self.doc.new_record(record)
            return "RECORD", context

    def _sam(self, context):
        source, match = context
        try:
            line = source.next_line
        except EOFError:
            return "END", context

        match = self.patterns['comment'].match(line)
        if match is not None:
            self.doc.new_comment(Comment(line.strip()[1:]))
            return "SAM", (source, match)

        match = self.patterns['record-start'].match(line)
        if match is not None:
            return "RECORD-START", (source, match)

        match = self.patterns['block-start'].match(line)
        if match is not None:
            return "BLOCK", (source, match)

        match = self.patterns['blank-line'].match(line)
        if match is not None:
            return "SAM", (source, match)

        match = self.patterns['codeblock-start'].match(line)
        if match is not None:
            return "CODEBLOCK-START", (source, match)

        match = self.patterns['blockquote-start'].match(line)
        if match is not None:
            return "BLOCKQUOTE-START", (source, match)

        match = self.patterns['list-item'].match(line)
        if match is not None:
            return "LIST-ITEM", (source, match)

        match = self.patterns['num-list-item'].match(line)
        if match is not None:
            return "NUM-LIST-ITEM", (source, match)

        match = self.patterns['block-insert'].match(line)
        if match is not None:
            return "BLOCK-INSERT", (source, match)

        match = self.patterns['paragraph-start'].match(line)
        if match is not None:
            return "PARAGRAPH-START", (source, match)

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
                elif self.name == 'blockquote':
                    yield ' citation="{0}"'.format(self.attributes)
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
        yield '<sam>\n'  # should include namespace and schema
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


class Pre(Flow):
    def serialize_xml(self):
        yield "<![CDATA["
        for x in self.flow:
            try:
                yield from x.serialize_xml()
            except AttributeError:
                yield x
        yield "]]>"


class Annotation:
    def __init__(self, annotation_type, text, specifically='', namespace=''):
        self.annotation_type = annotation_type
        self.text = text
        self.specifically = specifically
        self.namespace = namespace

    def __str__(self):
        return '[%s](%s "%s" (%s))' % (self.text, self.annotation_type, self.specifically, self.namespace)

    def serialize_xml(self):
        yield '<annotation type="{0}"'.format(self.annotation_type)
        if self.specifically:
            yield ' specifically="{0}"'.format(escape_for_xml(self.specifically))
        if self.namespace:
            yield ' namespace="{0}"'.format(self.namespace)
        yield '>{0}</annotation>'.format(escape_for_xml(self.text))


class Decoration:
    def __init__(self, decoration_type, text):
        self.decoration_type = decoration_type
        self.text = text

    def __str__(self):
        return '[%s](%s)' % (self.text, self.decoration_type)

    def serialize_xml(self):
        yield '<decoration type="{1}">{0}</decoration>'.format(self.text, self.decoration_type)


class InlineInsert:
    def __init__(self, content):
        self.content = content

    def __str__(self):
        return "[#insert:'%s']" % self.content

    def serialize_xml(self):
        # This duplicates block insert, but is it inherently the same
        # or only incidentally the same? Does DNRY apply?
        yield '<insert type="{0}"'.format(self.content[0])
        yield ' item="{0}"'.format(self.content[1])
        try:
            yield ' ids="{0}"'.format(' '.join(self.content[2]))
        except IndexError:
            pass
        try:
            yield ' conditions="{0}"'.format(' '.join(self.content[3]))
        except IndexError:
            pass
        yield '/>'



class DocStructure:
    def __init__(self):
        self.doc = None
        self.fields = None
        self.current_record = None
        self.current_block = None

    def new_root(self, block_type, text):
        r = Root(block_type, text)
        self.doc = r
        self.current_block = r

    def new_block(self, block_type, attributes, text, indent):
        if block_type == 'codeblock':
            b = Block(block_type, attributes, text, indent)
        elif block_type == 'blockquote':
            b = Block(block_type, attributes, text, indent)
        elif block_type == 'insert':
            b = BlockInsert(attributes, indent)
        else:
            b = Block(block_type, parse_block_attributes(attributes), text, indent)
        if self.doc is None:
            raise Exception('No root element found.')
        elif self.current_block.indent < indent:
            if self.current_block.name == 'p' and block_type == 'p' and self.current_block.indent != indent:
                raise Exception('Inconsistent paragraph indentation after "' + str(self.current_block.children[0]) + '".' )
            self.current_block.add_child(b)
        elif self.current_block.indent == indent:
            self.current_block.add_sibling(b)
        else:
            self.current_block.add_at_indent(b, indent)
        self.current_block = b
        # Useful lines for debugging the build of the tree
        # print(self.doc)
        # print('-----------------------------------------------------')

    def new_unordered_list_item(self, indent, content_indent):
        uli = Block('li', None, '', indent)
        if self.current_block.parent.name == 'li':
            self.current_block.parent.add_sibling(uli)
        else:
            ul = Block('ul', None, '', indent)
            self.current_block.add_sibling(ul)
            ul.add_child(uli)
        p = Block('p',None,'',content_indent)
        uli.add_child(p)
        self.current_block = p

    def new_ordered_list_item(self, indent, content_indent):
        oli = Block('li', None, '', indent)
        if self.current_block.parent.name == 'li':
            self.current_block.parent.add_sibling(oli)
        else:
            ol = Block('ol', None, '', indent)
            self.current_block.add_sibling(ol)
            ol.add_child(oli)
        p = Block('p', None,'',content_indent)
        oli.add_child(p)
        self.current_block = p

    def new_flow(self, flow):
        self.current_block.add_child(flow)

    def new_comment(self, comment):
        self.current_block.add_child(comment)

    def new_block_insert(self, insert, indent):
        bi = BlockInsert(insert, indent)
        self.current_block.add_sibling(bi)

    def new_record_set(self, local_element, field_names, local_indent):
        self.current_record = {'local_element': local_element, 'local_indent': local_indent}
        self.fields = field_names

    def new_record(self, record):
        b = Block(self.current_record['local_element'], None, '', self.current_record['local_indent'])
        self.current_block.add_child(b)
        self.current_block = b
        for name, content in record:
            b = Block(name, None, content, self.current_block.indent + 4)
            self.current_block.add_child(b)
        self.current_block = self.current_block.parent

    def serialize(self, serialize_format):
        if serialize_format.upper() == 'XML':
            yield from self.doc.serialize_xml()
        else:
            raise Exception("Unknown serialization protocol {0}".format(serialize_format))


class StringSource:
    def __init__(self, string_to_parse):
        """

        :param string_to_parse: The string to parse.
        """
        self.currentLine = None
        self.currentLineNumber = 0
        self.buf = io.StringIO(string_to_parse)

    @property
    def next_line(self):
        self.currentLine = self.buf.readline()
        if self.currentLine == "":
            raise EOFError("End of file")
        self.currentLineNumber += 1
        return self.currentLine


class SamParaParser:
    def __init__(self):
        # These attributes are set by the parse method
        self.doc = None
        self.para = None
        self.current_string = None
        self.flow = None

        self.stateMachine = StateMachine()
        self.stateMachine.add_state("PARA", self._para)
        self.stateMachine.add_state("ESCAPE", self._escape)
        self.stateMachine.add_state("END", None, end_state=1)
        self.stateMachine.add_state("ANNOTATION-START", self._annotation_start)
        self.stateMachine.add_state("BOLD-START", self._bold_start)
        self.stateMachine.add_state("ITALIC-START", self._italic_start)
        self.stateMachine.add_state("MONO-START", self._mono_start)
        self.stateMachine.add_state("QUOTES-START", self._quotes_start)
        self.stateMachine.add_state("INLINE-INSERT", self._inline_insert)
        self.stateMachine.set_start("PARA")
        self.patterns = {
            'escape': re.compile(r'\\'),
            'escaped-chars': re.compile(r'[\\\[\(\]_\*`]'),
            'annotation': re.compile(r'\[(?P<text>[^\[]*?[^\\])\]\((?P<type>[^\(]\S*?\s*[^\\"\'])(["\'](?P<specifically>.*?)["\'])??\s*(\((?P<namespace>\w+)\))?\)'),
            'bold': re.compile(r'\*(?P<text>\S.+?\S)\*'),
            'italic': re.compile(r'_(?P<text>\S.*?\S)_'),
            'mono': re.compile(r'`(?P<text>\S.*?\S)`'),
            'quotes': re.compile(r'"(?P<text>\S.*?\S)"'),
            'inline-insert': re.compile(r'>>\((?P<attributes>.*?)\)'),
            'inline-insert-id': re.compile(r'>>#(?P<id>\w*)')
        }

    def parse(self, para, doc):
        self.doc = doc
        self.para = Para(para)
        self.current_string = ''
        self.flow = Flow()
        self.stateMachine.run(self.para)

    def _para(self, para):
        try:
            char = para.next_char
        except IndexError:
            self.flow.append(self.current_string)
            self.current_string = ''
            self.doc.new_flow(self.flow)
            return "END", para
        if char == '\\':
            return "ESCAPE", para
        elif char == '[':
            return "ANNOTATION-START", para
        elif char == "*":
            return "BOLD-START", para
        elif char == "_":
            return "ITALIC-START", para
        elif char == "`":
            return "MONO-START", para
        elif char == '"':
            return "QUOTES-START", para
        elif char == ">":
            return "INLINE-INSERT", para
        else:
            self.current_string += char
            return "PARA", para

    def _annotation_start(self, para):
        match = self.patterns['annotation'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            annotation_type = str(match.group('type')).strip()
            text = match.group("text")
            specifically = match.group('specifically') if match.group('specifically') is not None else None
            namespace = match.group('namespace') if match.group('namespace') is not None else None
            self.flow.append(Annotation(annotation_type, text, specifically, namespace))
            para.advance(len(match.group(0)) - 1)
            return "PARA", para
        else:
            self.current_string += '['
            return "PARA", para

    def _bold_start(self, para):
        match = self.patterns['bold'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            self.flow.append(Decoration('bold', match.group("text")))
            para.advance(len(match.group(0)) - 1)
        else:
            self.current_string += '*'
        return "PARA", para

    def _italic_start(self, para):
        match = self.patterns['italic'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            self.flow.append(Decoration('italic', match.group("text")))
            para.advance(len(match.group(0)) - 1)
        else:
            self.current_string += '_'
        return "PARA", para

    def _mono_start(self, para):
        match = self.patterns['mono'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            self.flow.append(Decoration('mono', match.group("text")))
            para.advance(len(match.group(0)) - 1)
        else:
            self.current_string += '`'
        return "PARA", para

    def _quotes_start(self, para):
        match = self.patterns['quotes'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            self.flow.append(Decoration('quotes', match.group("text")))
            para.advance(len(match.group(0)) - 1)
        else:
            self.current_string += '"'
        return "PARA", para

    def _inline_insert(self, para):
        match = self.patterns['inline-insert'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            self.flow.append(InlineInsert(parse_insert(match.group("attributes"))))
            para.advance(len(match.group(0))-1)
        else:
            match = self.patterns['inline-insert-id'].match(para.rest_of_para)
            if match:
                self.flow.append(self.current_string)
                self.current_string = ''
                self.flow.append(InlineInsert(('reference', match.group("attributes"))))
                para.advance(len(match.group(0))-1)
            else:
                self.current_string += '>'
        return "PARA", para

    def _inline_insert_id(self, para):
        match = self.patterns['inline-insert_id'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            self.flow.append(InlineInsert('reference', match.group("id")))
            para.advance(len(match.group(0))-1)
        else:
            self.current_string += '>'
        return "PARA", para

    def _escape(self, para):
        char = para.next_char
        if self.patterns['escaped-chars'].match(char):
            self.current_string += char
        else:
            self.current_string += '\\' + char
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

def escape_for_xml(s):
    t = dict(zip([ord('<'), ord('>'), ord('&')], ['&lt;', '&gt;', '&amp;']))
    return s.translate(t)

para_parser = SamParaParser()

if __name__ == "__main__":
    samParser = SamParser()
    filename = sys.argv[-1]
    try:
        with open(filename, "r") as myfile:
            test = myfile.read()
    except FileNotFoundError:
        test = """sam:
        this:
            is: a test"""

    samParser.parse(StringSource(test))
    print("".join(samParser.serialize('xml')))
