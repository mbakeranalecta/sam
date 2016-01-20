import sys
from statemachine import StateMachine
from lxml import etree
import xml.parsers.expat
import io
from urllib.parse import urlparse

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
        self.stateMachine.add_state("FRAGMENT-START", self._fragment_start)
        self.stateMachine.add_state("PARAGRAPH-START", self._paragraph_start)
        self.stateMachine.add_state("PARAGRAPH", self._paragraph)
        self.stateMachine.add_state("RECORD-START", self._record_start)
        self.stateMachine.add_state("RECORD", self._record)
        self.stateMachine.add_state("LIST-ITEM", self._list_item)
        self.stateMachine.add_state("NUM-LIST-ITEM", self._num_list_item)
        self.stateMachine.add_state("LABELED-LIST-ITEM", self._labeled_list_item)
        self.stateMachine.add_state("BLOCK-INSERT", self._block_insert)
        self.stateMachine.add_state("STRING-DEF", self._string_def)
        self.stateMachine.add_state("LINE-START", self._line_start)
        self.stateMachine.add_state("EMBEDDED-XML", self._embedded_xml)
        self.stateMachine.add_state("END", None, end_state=1)
        self.stateMachine.set_start("NEW")
        self.current_paragraph = None
        self.doc = DocStructure()
        self.source = None
        self.patterns = {
            'sam-declaration': re.compile(r'sam:\s*(?:(?:\{(?P<namespace>\S+?)\})|(?P<schema>\S+))?'),
            'comment': re.compile(r'\s*#.*'),
            'block-start': re.compile(
                r'(?P<indent>\s*)(?P<element>\S+?):(\((?P<attributes>.*?(?<!\\))\))?(?P<content>.+)?'),
            'codeblock-start': re.compile(
                r'(?P<indent>\s*)(?P<flag>```\S*?(?=\())(\((?P<language>\w*)\s*(["\'](?P<source>.+?)["\'])?\s*(\((?P<namespace>\S+?)\))?(?P<other>.+?)?\))?'),
            'blockquote-start': re.compile(
                r'(?P<indent>\s*)("""|\'\'\'|blockquote:)(\((?P<attributes>.*?(?<!\\))\))?((\[\s*\*(?P<id>\S+)(?P<extra>.+?)\])|(\[\s*\#(?P<name>\S+)(?P<extra>.+?)\])|(\[\s*(?P<citation>.*?)\]))?'),
            'fragment-start': re.compile(r'(?P<indent>\s*)~~~(\((?P<attributes>.*?)\))?'),
            'paragraph-start': re.compile(r'\w*'),
            'line-start': re.compile(r'(?P<indent>\s*)\|(\((?P<attributes>.*?)\))?\s(?P<text>.*)'),
            'blank-line': re.compile(r'^\s*$'),
            'record-start': re.compile(r'(?P<indent>\s*)(?P<record_name>[a-zA-Z0-9-_]+)::(?P<field_names>.*)'),
            'list-item': re.compile(r'(?P<indent>\s*)(?P<marker>\*\s+)(?P<content>.*)'),
            'num-list-item': re.compile(r'(?P<indent>\s*)(?P<marker>[0-9]+\.\s+)(?P<content>.*)'),
            'labeled-list-item': re.compile(r'(?P<indent>\s*)\|(?P<label>\S.*?)(?<!\\)\|\s+(?P<content>.*)'),
            'block-insert': re.compile(r'(?P<indent>\s*)>>\((?P<attributes>.*?)\)\w*'),
            'string-def': re.compile(r'(?P<indent>\s*)\$(?P<name>\w*?)=(?P<value>.+)'),
            'embedded-xml': re.compile(r'(?P<indent>\s*)(?P<xmltag>\<\?xml.+)')
        }

    def parse(self, source):
        self.source = StringSource(source)
        try:
            self.stateMachine.run(self.source)
        except EOFError:
            raise SAMParserError("Document ended before structure was complete. At:\n\n"
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
        match = self.patterns['sam-declaration'].match(line)
        if match:
            self.doc.new_root(match)
            return "SAM", (source, None)
        else:
            raise SAMParserError("Not a SAM file!")

    def _block(self, context):
        source, match = context
        indent = len(match.group("indent"))
        element = match.group("element").strip()
        attributes = self.parse_block_attributes(match.group("attributes"))
        content = match.group("content")
        self.doc.new_block(element, attributes, para_parser.parse(content, self.doc), indent)
        return "SAM", context

    def _codeblock_start(self, context):
        source, match = context
        indent = len(match.group("indent"))
        codeblock_flag = match.group("flag")
        self.patterns['codeblock-end'] = re.compile(r'(\s*)' + codeblock_flag + '\s*$')

        attributes = {}

        language = match.group("language")
        if language is not None:
            attributes['language'] = language

        source = match.group("source")
        if source is not None:
            attributes["source"] = source

        namespace = match.group("namespace")
        if namespace is not None:
            attributes["namespace"] = namespace

        other = match.group("other")
        if other is not None:
            attributes.update(self.parse_block_attributes(other))

        self.doc.new_block('codeblock', attributes, None, indent)
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

        # TODO: Refactor this with the paraparser version


        extra=source.current_line.rstrip()[len(match.group(0)):]
        if extra:
            raise SAMParserError("Extra text found after blockquote start: " + extra)

        attributes = self.parse_block_attributes(match.group("attributes"))

        b = self.doc.new_block('blockquote', attributes, None, indent)

        #see if there is a citation
        idref = match.group('id')
        nameref = match.group('name')
        citation = match.group('citation')
        extra = match.group('extra')

        if idref:
            citation_type = 'idref'
            citation_value = idref.strip()
        elif nameref:
            citation_type = 'nameref'
            citation_value = nameref.strip()
        elif citation:
            citation_type = 'citation'
            citation_value = citation.strip()
        else:
            citation_type=None

        if citation_type:
            cit = (Citation(citation_type, citation_value, extra))
            b.add_child(cit)

        return "SAM", context

    def _fragment_start(self, context):
        source, match = context
        indent = len(match.group('indent'))

        attributes = {}

        attributes_string = match.group("attributes")
        if attributes_string is not None:
            attributes.update(self.parse_block_attributes(attributes_string))

        self.doc.new_block('fragment', attributes, None, indent)
        return "SAM", context

    def _paragraph_start(self, context):
        source, match = context
        line = source.current_line
        local_indent = len(line) - len(line.lstrip())
        self.doc.new_block('p', None, '', local_indent)
        self.paragraph_start(line)
        return "PARAGRAPH", context

    def _paragraph(self, context):
        source, match = context
        try:
            line = source.next_line
        except EOFError:
            f = para_parser.parse(self.current_paragraph, self.doc)
            self.doc.new_flow(f)
            return "END", context

        if self.patterns['blank-line'].match(line):
            f = para_parser.parse(self.current_paragraph, self.doc)
            self.doc.new_flow(f)
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
        self.doc.new_block("insert", attributes=parse_insert(match.group("attributes")), text=None, indent=indent)
        return "SAM", context

    def _string_def(self, context):
        source, match = context
        indent = len(match.group("indent"))
        self.doc.new_string_def(match.group('name'), para_parser.parse(match.group('value'), self.doc), indent=indent)
        return "SAM", context

    def _line_start(self, context):
        source, match = context
        indent = len(match.group("indent"))
        self.doc.new_block('line', self.parse_block_attributes(match.group("attributes")), para_parser.parse(match.group('text'), self.doc, strip=False), indent=indent)
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
        try:
            line = source.next_line
        except EOFError:
            return "END", context
        indent = len(line) - len(line.lstrip())
        if self.patterns['blank-line'].match(line):
            return "SAM", context
        elif indent < self.doc.current_block.indent:
            source.return_line()
            return "SAM", context
        else:
            field_values = [x.strip() for x in re.split(r'(?<!\\),',line)]
            if len(field_values) != len(self.doc.fields):
                raise SAMParserError("Record length does not match record set header. At:\n\n " + line)
            record = list(zip(self.doc.fields, field_values))
            self.doc.new_record(record)
            return "RECORD", context

    def _embedded_xml(self, context):
        source, match = context
        indent = len(match.group("indent"))
        embedded_xml_parser = xml.parsers.expat.ParserCreate()
        embedded_xml_parser.XmlDeclHandler=self._embedded_xml_declaration_check
        embedded_xml_parser.Parse(source.current_line.strip())
        xml_lines = []
        try:
            while True:
                line = source.next_line
                xml_lines.append(line)
                embedded_xml_parser.Parse(line)
        except xml.parsers.expat.ExpatError as err:
            if err.code==9: #junk after document element
                source.return_line()
                xml_text = ''.join(xml_lines[:-1])
                self.doc.new_embedded_xml(xml_text, indent)
                return "SAM", context
            else:
                raise

    def _embedded_xml_declaration_check(self, version, encoding, standalone):
        if version != "1.0":
            raise SAMParserError("The version of an embedded XML fragment must be 1.0.")
        if encoding.upper() != "UTF-8":
            raise SAMParserError("The encoding of an embedded XML fragment must be UTF-8.")



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

        match = self.patterns['fragment-start'].match(line)
        if match is not None:
            return "FRAGMENT-START", (source, match)

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

        match = self.patterns['string-def'].match(line)
        if match is not None:
            return "STRING-DEF", (source, match)

        match = self.patterns['line-start'].match(line)
        if match is not None:
            return "LINE-START", (source, match)

        match = self.patterns['embedded-xml'].match(line)
        if match is not None:
            return "EMBEDDED-XML", (source, match)

        match = self.patterns['block-start'].match(line)
        if match is not None:
            return "BLOCK", (source, match)

        match = self.patterns['paragraph-start'].match(line)
        if match is not None:
            return "PARAGRAPH-START", (source, match)

        raise SAMParserError("I'm confused")

    def serialize(self, serialize_format):
        return self.doc.serialize(serialize_format)

    def parse_block_attributes(self, attributes_string):
        result = {}
        try:
            attributes_list = attributes_string.split()
        except AttributeError:
            return None
        unexpected_attributes = [x for x in attributes_list if not (x[0] in '?#*')]
        if unexpected_attributes:
            raise SAMParserError("Unexpected attribute(s): {0}".format(', '.join(unexpected_attributes)))
        ids = [x[1:] for x in attributes_list if x[0] == '*']
        if len(ids) > 1:
            raise SAMParserError("More than one ID specified: " + ", ".join(ids))
        names = [x[1:] for x in attributes_list if x[0] == '#']
        if len(names) > 1:
            raise SAMParserError("More than one name specified: " + ", ".join(names))
        conditions = [x[1:] for x in attributes_list if x[0] == '?']
        if ids:
            if ids[0] in self.doc.ids:
                raise SAMParserError("Duplicate ID found: " + ids[0])
            self.doc.ids.extend(ids)
            result["id"] = "".join(ids)
        if names:
            result["name"] = "".join(names)
        if conditions:
            result["conditions"] = " ".join(conditions)
        return result

class Block:
    def __init__(self, name, attributes=None, content=None, namespace=None, indent=0):

        # Test for a valid block name. Must be valid XML name.
        try:
            x = etree.Element(name)
        except ValueError:
            raise SAMParserError("Invalid block name: " + name)

        assert isinstance(attributes, dict) or attributes is None

        self.name = name
        self.namespace = namespace
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

        if self.namespace is not None:
            if type(self.parent) is Root or self.namespace != self.parent.namespace:
                yield ' xmlns="{0}"'.format(self.namespace)

        if self.attributes:
            for key, value in self.attributes.items():
                yield " {0}=\"{1}\"".format(key, value)
        if self.children:
            yield ">"
            if self.content:
                yield "\n<title>"
                yield from self.content.serialize_xml()
                yield "</title>".format(self.content)

            if type(self.children[0]) is not Flow:
                yield "\n"

            for x in self.children:
                if x is not None:
                    yield from x.serialize_xml()
            yield "</{0}>\n".format(self.name)
        else:
            if self.content is None:
                yield "/>\n"
            else:
                yield '>'
                yield from self.content.serialize_xml()
                yield "</{0}>\n".format(self.name)


class Comment(Block):
    def __init__(self, content='', indent=0):
        super().__init__(name='comment', content=content, indent=indent)

    def __str__(self):
        return u"[#comment:'{1:s}']".format(self.content)

    def serialize_xml(self):
        yield '<!-- {0} -->\n'.format(self.content)


class StringDef(Block):
    def __init__(self, string_name, value, indent=0):
        super().__init__(name=string_name, content=value, indent=indent)

    def __str__(self):
        return "[%s:'%s']" % ('$' + self.name, self.content)

    def serialize_xml(self):
        yield '<string name="{0}">'.format(self.name)
        yield from self.content.serialize_xml()
        yield "</string>\n"


class Root(Block):
    def __init__(self):
        self.name = None
        self.attributes = None
        self.content = None
        self.indent = -1
        self.parent = None
        self.children = []

    def serialize_xml(self):
        yield '<?xml version="1.0" encoding="UTF-8"?>\n'
        for x in self.children:
            yield from x.serialize_xml()


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

class EmbeddedXML(Block):
    def __init__(self, text, indent):
        self.text = text
        self.indent = indent
        self.namespace = None

    def serialize_xml(self):
        yield self.text


class Annotation:
    def __init__(self, annotation_type, text, specifically='', namespace=''):
        self.annotation_type = annotation_type
        self.text = text
        self.specifically = specifically
        self.namespace = namespace

    def __str__(self):
        return '{%s}(%s "%s" (%s))' % (self.text, self.annotation_type, self.specifically, self.namespace)

    def serialize_xml(self):
        yield '<annotation type="{0}"'.format(self.annotation_type)
        if self.specifically:
            yield ' specifically="{0}"'.format(escape_for_xml(self.specifically))
        if self.namespace:
            yield ' namespace="{0}"'.format(self.namespace)
        yield '>{0}</annotation>'.format(escape_for_xml(self.text))


class Citation:
    def __init__(self, citation_type, citation_value, citation_extra):
        self.citation_type = citation_type
        self.citation_value = citation_value
        self.citation_extra = citation_extra

    def __str__(self):
        return '[%s %s]' % (self.citation_type, self.citation_value, self.citation_extra)

    def serialize_xml(self):
        if self.citation_type == 'citation':
            yield '<citation>{1}</citation>'.format(self.citation_type, self.citation_value)
        else:
            yield '<citation type="{0}" value="{1}" extra="{2}"/>'.format(self.citation_type, self.citation_value, self.citation_extra)

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
        yield '<insert'
        for key, value in self.attributes.items():
            yield " {0}=\"{1}\"".format(key, value)
        yield '/>'


class DocStructure:
    def __init__(self):
        self.doc = None
        self.fields = None
        self.current_record = None
        self.current_block = None
        self.default_namespace =None
        self.ids = []

    def new_root(self, match):
        if match.group('schema') is not None:
            pass
        elif match.group('namespace') is not None:
            self.default_namespace = match.group('namespace')
        r = Root()
        self.doc = r
        self.current_block = r


    def add_block(self, block):
        """
        Adds a block to the current document structure. The location
        to add the block is determined by comparing the indent of
        the new block to that of the current block in the document
        structure.

        All new block methods should call this method to add a
        block based on indent. In some cases, (such as lists)
        document structure is not based on indent. In these cases,
        the new block method should update the doc structure itself,
        making sure to set current_block to the last block they add.

        :param block: The Block object to be added.
        :return: None
        """

        if block.namespace is None and self.default_namespace is not None:
            block.namespace = self.default_namespace

        if self.doc is None:
            raise SAMParserError('No root element found.')
        elif self.current_block.indent < block.indent:
            if self.current_block.name == 'p':
                raise SAMParserError(
                        'A paragraph cannot have block children. At \"{0}\".'.format(
                            str(self.current_block.children[0])))
            self.current_block.add_child(block)
        elif self.current_block.indent == block.indent:
            self.current_block.add_sibling(block)
        else:
            self.current_block.add_at_indent(block, block.indent)
        self.current_block = block
        # Useful lines for debugging the build of the tree
        # print(self.doc)
        # print('-----------------------------------------------------')

    def new_block(self, block_type, attributes, text, indent):
        b = Block(block_type, attributes, text, None, indent)
        self.add_block(b)
        return b

    def new_unordered_list_item(self, indent, content_indent):
        uli = Block('li', None, '', None, indent + 1)
        if self.current_block.parent.name == 'li':
            self.add_block(uli)
        else:
            ul = Block('ul', None, '', None, indent)
            self.add_block(ul)
            self.add_block(uli)
        p = Block('p', None, '', None, content_indent)
        self.add_block(p)

    def new_ordered_list_item(self, indent, content_indent):
        oli = Block('li', None, '', None, indent + 1)
        if self.current_block.parent.name == 'li':
            self.add_block(oli)
        else:
            ol = Block('ol', None, '', None, indent)
            self.add_block(ol)
            self.add_block(oli)
        p = Block('p', None, '', None, content_indent)
        self.add_block(p)

    def new_labeled_list_item(self, indent, label):
        lli = Block('li', None, '', None, indent)
        lli.add_child(Block('label', None, para_parser.parse(label, self.doc), None, indent))
        if self.current_block.parent.name == 'li':
            self.current_block.parent.add_sibling(lli)
        else:
            ll = Block('ll', None, '', None, indent)
            self.add_block(ll)
            ll.add_child(lli)
            self.current_block = lli
        p = Block('p', None, '', None, indent)
        lli.add_child(p)
        self.current_block = p

    def new_flow(self, flow):
        self.current_block.add_child(flow)

    def new_comment(self, comment):
        self.current_block.add_child(comment)

    def new_embedded_xml(self, text, indent):
        b = EmbeddedXML(text=text, indent=indent)
        self.add_block(b)

    def new_string_def(self, string_name, value, indent):
        s = StringDef(string_name, value, indent)
        self.add_block(s)

    def new_record_set(self, local_element, field_names, local_indent):
        self.current_record = {'local_element': local_element, 'local_indent': local_indent}
        self.fields = field_names

    def new_record(self, record):
        b = Block(self.current_record['local_element'], None, '', None, self.current_record['local_indent'])
        if self.current_block.indent == b.indent:
            self.current_block.add_sibling(b)
        else:
            self.current_block.add_child(b)

        self.current_block = b
        for name, content in record:
            b = Block(name, None, para_parser.parse(content, self.doc), None, self.current_block.indent + 4)
            self.current_block.add_child(b)
        # self.current_block = self.current_block.parent

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
            raise SAMParserError("Unknown serialization protocol {0}".format(serialize_format))


class StringSource:
    def __init__(self, source):
        """

        :param string_to_parse: The string to parse.
        """
        self.current_line = None
        self.pending_line = None
        self.previous_line = None
        self.buf = source

    @property
    def next_line(self):
        self.previous_line = self.current_line
        if self.pending_line is None:
            self.current_line = self.buf.readline()
        else:
            self.current_line = self.pending_line
            self.pending_line = None
        if self.current_line == "":
            raise EOFError("End of file")
        return self.current_line

    def return_line(self):
        self.pending_line = self.current_line
        self.current_line = self.previous_line



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
        self.stateMachine.add_state("CITATION-START", self._citation_start)
        self.stateMachine.add_state("BOLD-START", self._bold_start)
        self.stateMachine.add_state("ITALIC-START", self._italic_start)
        self.stateMachine.add_state("MONO-START", self._mono_start)
        self.stateMachine.add_state("QUOTES-START", self._quotes_start)
        self.stateMachine.add_state("INLINE-INSERT", self._inline_insert)
        self.stateMachine.set_start("PARA")
        self.patterns = {
            'escape': re.compile(r'\\'),
            'escaped-chars': re.compile(r'[\\\(\{\}\[\]_\*,`]'),
            'annotation': re.compile(
                r'\{(?P<text>[^\{]*?[^\\])\}(\(\s*(?P<type>\S*?\s*[^\\"\'])(["\'](?P<specifically>.*?)["\'])??\s*(\((?P<namespace>\w+)\))?\))?'),
            'bold': re.compile(r'\*(?P<text>\S.+?\S)\*'),
            'italic': re.compile(r'_(?P<text>\S.*?\S)_'),
            'mono': re.compile(r'`(?P<text>\S.*?\S)`'),
            'quotes': re.compile(r'"(?P<text>\S.*?\S)"'),
            'inline-insert': re.compile(r'>>\((?P<attributes>.*?)\)'),
            'citation': re.compile(r'(\[\s*\*(?P<id>\S+)(\s+(?P<extra>.+?))?\])|(\[\s*\#(?P<name>\S+)(\s+(?P<extra>.+?))?\])|(\[\s*(?P<citation>.*?)\])')
        }

    def parse(self, para, doc, strip=True):
        if para is None:
            return None
        self.doc = doc
        self.para = Para(para, strip)
        self.current_string = ''
        self.flow = Flow()
        self.stateMachine.run(self.para)
        return self.flow

    def _para(self, para):
        try:
            char = para.next_char
        except IndexError:
            self.flow.append(self.current_string)
            self.current_string = ''
            return "END", para
        if char == '\\':
            return "ESCAPE", para
        elif char == '{':
            return "ANNOTATION-START", para
        elif char == '[':
            return "CITATION-START", para
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
                        raise SAMParserError(
                                "Blank annotation found: {" + text + "} " +
                                "If you are trying to insert square brackets " +
                                "into the document, use \{" + text +
                                "]. Otherwise, make sure annotated text matches "
                                "previous annotation exactly."
                        )

            else:
                #Check for link shortcut
                if urlparse(annotation_type,None).scheme is not None:
                    specifically = annotation_type
                    annotation_type='link'
                else:
                    specifically = match.group('specifically') if match.group('specifically') is not None else None
                namespace = match.group('namespace').strip() if match.group('namespace') is not None else None
                self.flow.append(Annotation(annotation_type.strip(), text, specifically, namespace))
            para.advance(len(match.group(0)) - 1)
            return "PARA", para
        else:
            self.current_string += '{'
            return "PARA", para

    def _citation_start(self, para):
        match = self.patterns['citation'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            idref = match.group('id')
            nameref = match.group('name')
            citation = match.group('citation')
            extra = match.group('extra')

            if idref:
                citation_type = 'idref'
                citation_value = idref.strip()
            elif nameref:
                citation_type = 'nameref'
                citation_value = nameref.strip()
            else:
                citation_type = 'citation'
                citation_value = citation.strip()

            self.flow.append(Citation(citation_type, citation_value, extra))
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
            para.advance(len(match.group(0)) - 1)
        else:
            self.current_string += '>'
        return "PARA", para

    def _inline_insert_id(self, para):
        match = self.patterns['inline-insert_id'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            self.flow.append(InlineInsert('reference', match.group("id")))
            para.advance(len(match.group(0)) - 1)
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
    def __init__(self, para, strip=True):
        self.para = para.strip() if strip else para
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

class SAMParserError(Exception):
    """
    Raised if the SAM parser encounters an error.
    """



def parse_insert(insert_string):
    result = {}
    attributes_list = insert_string.split()
    insert_type = attributes_list.pop(0)
    if insert_type[0] == '$':
        insert_item = insert_type[1:]
        insert_type = 'string'
    elif insert_type[0] == '*':
        insert_item = insert_type[1:]
        insert_type = 'id'
    elif insert_type[0] == '#':
        insert_item = insert_type[1:]
        insert_type = 'name'
    elif insert_type[0] == '~':
        insert_item = insert_type[1:]
        insert_type = 'fragment'
    else:
        insert_item = attributes_list.pop(0)
    insert_ids = [x[1:] for x in attributes_list if x[0] == '*']
    insert_names = [x[1:] for x in attributes_list if x[0] == '#']
    insert_conditions = [x[1:] for x in attributes_list if x[0] == '?']
    unexpected_attributes = [x for x in attributes_list if not (x[0] in '?#*')]
    if len(insert_ids) > 1:
        raise SAMParserError("More than one ID specified: " + ", ".join(insert_ids))
    if len(insert_names) > 1:
        raise SAMParserError("More than one name specified: " + ", ".join(insert_names))
    if unexpected_attributes:
        raise SAMParserError("Unexpected insert attribute(s): {0}".format(unexpected_attributes))
    result['type'] = insert_type
    result['item'] = insert_item
    if insert_ids:
        result['id'] = "".join(insert_ids)
    if insert_names:
        result['name'] = "".join(insert_names)
    if insert_conditions:
        result['conditions'] = " ".join(insert_conditions)
    return result


def escape_for_xml(s):
    t = dict(zip([ord('<'), ord('>'), ord('&')], ['&lt;', '&gt;', '&amp;']))
    return s.translate(t)


para_parser = SamParaParser()

if __name__ == "__main__":
    samParser = SamParser()
    infile = sys.argv[-1]
    try:
        with open(infile, "r") as inf:
            test = inf.read()
    except FileNotFoundError:
        test = """sam:
        this:
            is: a test"""
    try:
        samParser.parse(io.StringIO(test))
    except SAMParserError as err:
        print(err, file=sys.stderr)
        exit(1)


    # Using a loop to avoid buffering the serialized XML.
    for i in samParser.serialize('xml'):
        print(i, end="")
