import sys
from statemachine import StateMachine
from lxml import etree
import io

try:
    import regex as re
except ImportError:
    import re


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
        self.stateMachine.add_state("LABELED-LIST-ITEM", self._labeled_list_item)
        self.stateMachine.add_state("BLOCK-INSERT", self._block_insert)
        self.stateMachine.add_state("END", None, end_state=1)
        self.stateMachine.set_start("NEW")
        self.current_paragraph = None
        self.doc = DocStructure()
        self.source = None
        self.patterns = {
            'comment': re.compile(r'\s*#.*'),
            'block-start': re.compile(r'(?P<indent>\s*)(?P<element>[a-zA-Z0-9-_]+):(\((?P<attributes>.*?(?<!\\))\))?(?P<content>.*)?'),
            'codeblock-start': re.compile(r'(?P<indent>\s*)(?P<flag>```.*?)\((?P<attributes>.*?)\)'),
            'blockquote-start': re.compile(r'(?P<indent>\s*)("""|\'\'\'|blockquote:)(\((?P<type>\w*)\s*(["\'](?P<citation>.+?)["\'])?\s*(\((?P<format>\w+?)\))?(?P<other>.+?)?\))?'),
            'paragraph-start': re.compile(r'\w*'),
            'blank-line': re.compile(r'^\s*$'),
            'record-start': re.compile(r'(?P<indent>\s*)(?P<record_name>[a-zA-Z0-9-_]+)::(?P<field_names>.*)'),
            'list-item': re.compile(r'(?P<indent>\s*)(?P<marker>\*\s+)(?P<content>.*)'),
            'num-list-item': re.compile(r'(?P<indent>\s*)(?P<marker>[0-9]+\.\s+)(?P<content>.*)'),
            'labeled-list-item': re.compile(r'(?P<indent>\s*)\|(?P<label>.+?)\|\s+(?P<content>.*)'),
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
        indent = len(match.group("indent"))
        element = match.group("element").strip()
        attributes = parse_block_attributes(match.group("attributes"))
        content = match.group("content").strip()
        self.doc.new_block(element, attributes, content, indent)
        return "SAM", context

    def _codeblock_start(self, context):
        source, match = context
        indent = len(match.group("indent"))
        codeblock_flag = match.group("flag")
        self.patterns['codeblock-end'] = re.compile(r'(\s*)' + codeblock_flag + '\s*$')
        # FIXME: Does codeblock allow other attributes? If not, test?
        language = match.group("attributes").strip()
        self.doc.new_block('codeblock', {"language":language}, None, indent)
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
        indent = len(match.group('indent'))

        attributes = {}

        citation_type = match.group("type")
        if citation_type is not None:
            attributes['type']= citation_type

        citation = match.group("citation")
        if citation is not None:
            attributes["citation"] = citation

        citation_format = match.group("format")
        if citation_format is not None:
            attributes["format"] = citation_format

        other = match.group("other")
        if other is not None:
            attributes.update(parse_block_attributes(other))

        self.doc.new_block('blockquote', attributes, None, indent)
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
        indent = len(match.group("indent"))
        content_indent = indent + len(match.group("marker"))
        self.doc.new_unordered_list_item(indent, content_indent)
        self.paragraph_start(str(match.group("content")).strip())
        return "PARAGRAPH", context

    def _num_list_item(self, context):
        source, match = context
        indent = len(match.group("indent"))
        content_indent = indent + len(match.group("marker"))
        self.doc.new_ordered_list_item(indent, content_indent)
        self.paragraph_start(str(match.group("content")).strip())
        return "PARAGRAPH", context

    def _labeled_list_item(self, context):
        source, match = context
        indent = len(match.group("indent"))
        label = match.group("label")
        self.doc.new_labeled_list_item(indent, label)
        self.paragraph_start(str(match.group("content")).strip())
        return "PARAGRAPH", context

    def _block_insert(self, context):
        source, match = context
        indent = len(match.group("indent"))
        self.doc.new_block('insert', text='', attributes=parse_insert(match.group("attributes")), indent=indent)
        return "SAM", context

    def _record_start(self, context):
        source, match = context
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

        match = self.patterns['labeled-list-item'].match(line)
        if match is not None:
            return "LABELED-LIST-ITEM", (source, match)

        match = self.patterns['block-insert'].match(line)
        if match is not None:
            return "BLOCK-INSERT", (source, match)

        match = self.patterns['block-start'].match(line)
        if match is not None:
            return "BLOCK", (source, match)

        match = self.patterns['paragraph-start'].match(line)
        if match is not None:
            return "PARAGRAPH-START", (source, match)

        raise Exception("I'm confused")

    def serialize(self, serialize_format):
        return self.doc.serialize(serialize_format)


class Block:
    def __init__(self, name, attributes=None, content=None, indent=0):

        # Test for a valid block name. Must be valid XML name.
        try:
            x = etree.Element(name)
        except ValueError:
            raise Exception("Invalid block name: " + name)

        assert isinstance(attributes, dict) or attributes is None

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
        x = self.ancestor_at_indent(indent)
        b.parent = x
        x.children.append(b)

    def ancestor_at_indent(self, indent):
        x = self.parent
        while x.indent >= indent:
            x = x.parent
        return x


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

        if self.attributes:
            for key, value in self.attributes.items():
                yield " {0}=\"{1}\" ".format(key, value)
        if self.children:
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
        return u"[#comment:'{1:s}']".format(self.content)

    def serialize_xml(self):
        yield '<!-- {0} -->\n'.format(self.content)


class BlockInsert(Block):
    # Should not really inherit from Block as cannot have children, etc
    def __init__(self, attributes, indent=0):
        super().__init__(name='insert', attributes=attributes, indent=indent)

    def __str__(self):
        return "[%s:'%s']" % ('#insert', self.content)

    def serialize_xml(self):
        yield '<insert '
        for key, value in self.attributes.items():
            yield " {0}=\"{1}\" ".format(key, value)
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

    def find_last_annotation(self, text):
        for i in reversed(self.flow):
            if type(i) is Annotation:
                if i.text == text:
                    return i
        return None


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
    def __init__(self, attributes):
        self.attributes = attributes

    def __str__(self):
        return "[#insert:'%s']" % self.attributes

    def serialize_xml(self):
        # This duplicates block insert, but is it inherently the same
        # or only incidentally the same? Does DNRY apply?
        yield '<insert '
        for key, value in self.attributes.items():
            yield " {0}=\"{1}\" ".format(key, value)
        yield '/>\n'



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
            b = Block(block_type, attributes, text, indent)
        if self.doc is None:
            raise Exception('No root element found.')
        elif self.current_block.indent < indent:
            if self.current_block.name == 'p':
                raise Exception(
                    'A paragraph cannot have block children. At \"{0}\".'.format(str(self.current_block.children[0])))
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

    def new_labeled_list_item(self, indent, label):
        lli = Block('li', None, '', indent)
        lli.add_child(Block('label',None,label,indent))
        if self.current_block.parent.name == 'li':
            self.current_block.parent.add_sibling(lli)
        else:
            ll = Block('ll', None, '', indent)
            self.current_block.add_sibling(ll)
            ll.add_child(lli)
        p = Block('p', None,'',indent)
        lli.add_child(p)
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

    def find_last_annotation(self, text, node=None):
        if node is None:
            node = self.doc
        if type(node) is Flow:
            result = node.find_last_annotation(text)
            if result is not None:
                return result
        else:
            try:
                for i in reversed(node.children):
                    result = self.find_last_annotation(text, i)
                    if result is not None:
                        return result
            except AttributeError:
                pass
        return None

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
            'annotation': re.compile(r'\[(?P<text>[^\[]*?[^\\])\](\((?P<type>[^\(]\S*?\s*[^\\"\'])(["\'](?P<specifically>.*?)["\'])??\s*(\((?P<namespace>\w+)\))?\))?'),
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
            annotation_type = match.group('type')
            text = match.group("text")
            # If there is an annotated phrase with no annotation, look back
            # to see if it has been annotated already, and if so, copy the
            # closest preceding annotation.
            if annotation_type is None:
                # First look back in the current flow
                # (which is not part of the doc structure yet).
                previous = self.flow.find_last_annotation(text)
                if previous is not None:
                    self.flow.append(previous)
                else:
                    # Then look back in the document.
                    previous = self.doc.find_last_annotation(text)
                    if previous is not None:
                        self.flow.append(previous)

                    # Else raise an exception.
                    else:
                        raise Exception(
                                "Blank annotation found: [" + text + "] " +
                                "If you are trying to insert square brackets " +
                                "into the document, use \[" + text +
                                "]. Otherwise, make sure annotated text matches "
                                "previous annotation exactly."
                        )

            else:
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
    result = {}
    try:
        attributes_list = attributes_string.split()
    except AttributeError:
        return None
    unexpected_attributes = [x for x in attributes_list if not(x[0] in '?#')]
    if unexpected_attributes:
        raise Exception("Unexpected attribute(s): {0}".format(', '.join(unexpected_attributes)))
    ids = [x[1:] for x in attributes_list if x[0] == '#']
    conditions = [x[1:] for x in attributes_list if x[0] == '?']
    if ids:
        result["ids"] = " ".join(ids)
    if conditions:
        result["conditions"] = " ".join(conditions)
    return result


def parse_insert(insert_string):
    result={}
    attributes_list = insert_string.split()
    insert_type = attributes_list.pop(0)
    if insert_type == '$':
        insert_type = 'string'
    if insert_type == '#':
        insert_type = 'ref'
    insert_item = attributes_list.pop(0)
    insert_ids = [x[1:] for x in attributes_list if x[0] == '#']
    insert_conditions = [x[1:] for x in attributes_list if x[0] == '?']
    unexpected_attributes = [x for x in attributes_list if not(x[0] in '?#')]
    if unexpected_attributes:
        raise Exception("Unexpected insert attribute(s): {0}".format(unexpected_attributes))
    result['type'] = insert_type
    result['item'] = insert_item
    if insert_ids:
        result['ids'] = " ".join(insert_ids)
    if insert_conditions:
        result['conditions'] = " ".join(insert_conditions)
    return result

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
