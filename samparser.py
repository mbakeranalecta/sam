import sys
from statemachine import StateMachine
from lxml import etree
import xml.parsers.expat
import html
import argparse
import urllib.request
import pathlib
import codecs

from urllib.parse import urlparse

try:
    import regex as re
except ImportError:
    import re

# Block regex component expressions
re_indent = r'(?P<indent>\s*)'
re_attributes = r'(?P<attributes>(\((.*?(?<!\\))\))*)'
re_content = r'(?P<content>.*)'
re_name = r'(?P<name>\S+?)'
re_ul_marker = r'(?P<marker>\*)'
re_ol_marker = r'(?P<marker>[0-9]+\.)'
re_ll_marker = r'\|(?P<label>\S.*?)(?<!\\)\|'
re_spaces = r'\s+'
re_one_space = r'\s'
re_comment = r'#.*'


class SamParser:
    def __init__(self):

        self.stateMachine = StateMachine()
        self.stateMachine.add_state("NEW", self._new_file)
        self.stateMachine.add_state("SAM", self._sam)
        self.stateMachine.add_state("BLOCK", self._block)
        self.stateMachine.add_state("CODEBLOCK-START", self._codeblock_start)
        self.stateMachine.add_state("CODEBLOCK", self._codeblock)
        self.stateMachine.add_state("EMBED-START", self._embed_start)
        self.stateMachine.add_state("EMBED", self._embed)
        self.stateMachine.add_state("BLOCKQUOTE-START", self._blockquote_start)
        self.stateMachine.add_state("FRAGMENT-START", self._fragment_start)
        self.stateMachine.add_state("PARAGRAPH-START", self._paragraph_start)
        self.stateMachine.add_state("PARAGRAPH", self._paragraph)
        self.stateMachine.add_state("RECORD-START", self._record_start)
        self.stateMachine.add_state("RECORD", self._record)
        self.stateMachine.add_state("GRID-START", self._grid_start)
        self.stateMachine.add_state("GRID", self._grid)
        self.stateMachine.add_state("LIST-ITEM", self._list_item)
        self.stateMachine.add_state("NUM-LIST-ITEM", self._num_list_item)
        self.stateMachine.add_state("LABELED-LIST-ITEM", self._labeled_list_item)
        self.stateMachine.add_state("BLOCK-INSERT", self._block_insert)
        self.stateMachine.add_state("INCLUDE", self._include)
        self.stateMachine.add_state("STRING-DEF", self._string_def)
        self.stateMachine.add_state("LINE-START", self._line_start)
        self.stateMachine.add_state("EMBEDDED-XML", self._embedded_xml)
        self.stateMachine.add_state("END", None, end_state=1)
        self.stateMachine.set_start("NEW")
        self.current_text_block = None
        self.doc = DocStructure()
        self.source = None
        self.smart_quotes = False
        self.patterns = {
            'sam-declaration': re.compile(r'sam:\s*(?:(?:\{(?P<namespace>\S+?)\})|(?P<schema>\S+))?', re.U),
            'comment': re.compile(re_indent + re_comment, re.U),
            'block-start': re.compile(re_indent + re_name + r'(?<!\\):' + re_attributes + re_content + r'?', re.U),
            'codeblock-start': re.compile(
                re_indent + r'(?P<flag>```)(' + re_attributes + ')?\s*(?P<unexpected>.*)',
                re.U),
            'embed-start': re.compile(
                re_indent + r'(?P<flag>===)(' + re_attributes + ')?\s*(?P<unexpected>.*)',
                re.U),
            'grid-start': re.compile(re_indent + r'\+\+\+' + re_attributes, re.U),
            'blockquote-start': re.compile(
                re_indent + r'("""|\'\'\'|blockquote:)' + re_attributes + r'((\[\s*\*(?P<id>\S+)(?P<id_extra>.*?)\])|(\[\s*\#(?P<name>\S+)(?P<name_extra>.*?)\])|(\[\s*(?P<citation>.*?)\]))?',
                re.U),
            'fragment-start': re.compile(re_indent + r'~~~' + re_attributes, re.U),
            'paragraph-start': re.compile(r'\w*', re.U),
            'line-start': re.compile(re_indent + r'\|' + re_attributes + re_one_space + re_content, re.U),
            'blank-line': re.compile(r'^\s*$'),
            'record-start': re.compile(re_indent + re_name + r'(?<!\\)::' + re_attributes + '(?P<field_names>.*)', re.U),
            'list-item': re.compile(re_indent + re_ul_marker + re_attributes + re_spaces + re_content, re.U),
            'num-list-item': re.compile(re_indent + re_ol_marker + re_attributes + re_spaces + re_content, re.U),
            'labeled-list-item': re.compile(re_indent + re_ll_marker + re_attributes + re_spaces + re_content, re.U),
            'block-insert': re.compile(re_indent + r'>>>(?P<insert>\((.*?(?<!\\))\))(' + re_attributes + ')?\s*(?P<unexpected>.*)', re.U),
            'include': re.compile(re_indent + r'<<<' + re_attributes, re.U),
            'string-def': re.compile(re_indent + r'\$' + re_name + '\s*=\s*' + re_content, re.U),
            'embedded-xml': re.compile(re_indent + r'(?P<xmltag>\<\?xml.+)', re.U)
        }

    def parse(self, source):
        self.source = StringSource(source)
        try:
            self.stateMachine.run(self.source)
        except EOFError:
            raise SAMParserError("Document ended before structure was complete.")

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
        block_name = match.group("name").strip()
        attributes = parse_attributes(match.group("attributes"))
        content = match.group("content").strip()
        parsed_content = None if content == '' else para_parser.parse(content, self.doc)
        self.doc.new_block(block_name, attributes, parsed_content, indent)
        return "SAM", context

    def _codeblock_start(self, context):
        source, match = context
        if match.group("unexpected"):
            raise SAMParserError("Unexpected characters in codeblock header. Found: " + match.group("unexpected"))
        indent = len(match.group("indent"))

        attributes = parse_attributes(match.group("attributes"), flagged="*#?", unflagged="language")

        self.doc.new_block('codeblock', attributes, None, indent)
        self.current_text_block = TextBlock()
        return "CODEBLOCK", context

    def _codeblock(self, context):
        source, match = context
        try:
            line = source.next_line
        except EOFError:
            self.doc.new_flow(Pre(self.current_text_block))
            self.current_text_block = None
            return "END", context

        indent = len(line) - len(line.lstrip())
        if self.patterns['blank-line'].match(line):
            self.current_text_block.append(line)
            return "CODEBLOCK", context
        if indent <= self.doc.current_block.indent:
            source.return_line()
            self.doc.new_flow(Pre(self.current_text_block.strip()))
            self.current_text_block = None
            return "SAM", context
        else:
            self.current_text_block.append(line)
            return "CODEBLOCK", context

    def _embed_start(self, context):
        source, match = context
        if match.group("unexpected"):
            raise SAMParserError("Unexpected characters in embed header. Found: " + match.group("unexpected"))
        indent = len(match.group("indent"))

        attributes = parse_attributes(match.group("attributes"), flagged="*#?", unflagged="language")

        self.doc.new_block('embed', attributes, None, indent)
        self.current_text_block = TextBlock()
        return "EMBED", context

    def _embed(self, context):
        source, match = context
        try:
            line = source.next_line
        except EOFError:
            self.doc.new_flow(Pre(self.current_text_block))
            self.current_text_block = None
            return "END", context

        indent = len(line) - len(line.lstrip())
        if self.patterns['blank-line'].match(line):
            self.current_text_block.append(line)
            return "EMBED", context
        if indent <= self.doc.current_block.indent:
            source.return_line()
            self.doc.new_flow(Pre(self.current_text_block.strip()))
            self.current_text_block = None
            return "SAM", context
        else:
            self.current_text_block.append(line)
            return "EMBED", context

    def _blockquote_start(self, context):
        source, match = context
        indent = len(match.group('indent'))

        # TODO: Refactor this with the paraparser version


        extra = source.current_line.rstrip()[len(match.group(0)):]
        if extra:
            raise SAMParserError("Extra text found after blockquote start: " + extra)

        attributes = parse_attributes(match.group("attributes"))

        b = self.doc.new_block('blockquote', attributes, None, indent)

        # see if there is a citation
        try:
            idref = match.group('id')
        except IndexError:
            idref = None
        try:
            nameref = match.group('name')
        except IndexError:
            nameref = None
        try:
            citation = match.group('citation')
        except IndexError:
            citation = None

        if idref:
            citation_type = 'idref'
            citation_value = idref.strip()
            extra = match.group('id_extra')
        elif nameref:
            citation_type = 'nameref'
            citation_value = nameref.strip()
            extra = match.group('name_extra')
        elif citation:
            citation_type = 'citation'
            citation_value = citation.strip()
        else:
            citation_type = None

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
            attributes.update(parse_attributes(attributes_string))

        self.doc.new_block('fragment', attributes, None, indent)
        return "SAM", context

    def _paragraph_start(self, context):
        source, match = context
        line = source.current_line
        local_indent = len(line) - len(line.lstrip())
        self.doc.new_paragraph(None, '', local_indent)
        self.current_text_block = TextBlock(line)
        return "PARAGRAPH", context

    def _paragraph(self, context):
        source, match = context
        try:
            line = source.next_line
        except EOFError:
            f = para_parser.parse(self.current_text_block.text, self.doc)
            self.current_text_block = None
            self.doc.new_flow(f)
            return "END", context

        first_line_indent = len(match.string) - len(match.string.lstrip())
        this_line_indent = len(line) - len(line.lstrip())

        if self.patterns['blank-line'].match(line):
            f = para_parser.parse(self.current_text_block.text, self.doc)
            self.current_text_block = None
            self.doc.new_flow(f)
            return "SAM", context

        if this_line_indent < first_line_indent:
            f = para_parser.parse(self.current_text_block.text, self.doc)
            self.current_text_block = None
            self.doc.new_flow(f)
            source.return_line()
            return "SAM", context

        if self.doc.in_context(['p', 'li']):
            if self.patterns['list-item'].match(line) or self.patterns['num-list-item'].match(line) or self.patterns[
                'labeled-list-item'].match(line):
                f = para_parser.parse(self.current_text_block.text, self.doc)
                self.current_text_block = None
                self.doc.new_flow(f)
                source.return_line()
                return "SAM", context

        self.current_text_block.append(line)
        return "PARAGRAPH", context

    def _list_item(self, context):
        source, match = context
        indent = len(match.group("indent"))
        attributes = parse_attributes(match.group("attributes"))
        self.doc.new_unordered_list_item(attributes, indent)
        self.current_text_block = TextBlock(str(match.group("content")).strip())
        return "PARAGRAPH", context

    def _num_list_item(self, context):
        source, match = context
        indent = len(match.group("indent"))
        attributes = parse_attributes(match.group("attributes"))
        self.doc.new_ordered_list_item(attributes, indent)
        self.current_text_block = TextBlock(str(match.group("content")).strip())
        return "PARAGRAPH", context

    def _labeled_list_item(self, context):
        source, match = context
        indent = len(match.group("indent"))
        label = match.group("label")
        attributes = parse_attributes(match.group("attributes"))
        self.doc.new_labeled_list_item(attributes, indent, label)
        self.current_text_block = TextBlock(str(match.group("content")).strip())
        return "PARAGRAPH", context

    def _block_insert(self, context):
        source, match = context
        if match.group("unexpected"):
            raise SAMParserError("Unexpected characters in block insert. Found: " + match.group("unexpected"))
        indent = len(match.group("indent"))
        attributes = parse_insert(match.group("insert"))
        attributes.update( parse_attributes(match.group("attributes"), flagged="*#?"))
        self.doc.new_block("insert", attributes=attributes, text=None, indent=indent)
        return "SAM", context

    def _include(self, context):
        source, match = context
        indent = len(match.group("indent"))
        # FIXME: Should validate attributes.
        self.doc.new_include(href=match.group("attributes")[1:-1], indent=indent)
        return "SAM", context

    def _string_def(self, context):
        source, match = context
        indent = len(match.group("indent"))
        self.doc.new_string_def(match.group('name'), para_parser.parse(match.group('content'), self.doc), indent=indent)
        return "SAM", context

    def _line_start(self, context):
        source, match = context
        indent = len(match.group("indent"))
        self.doc.new_block('line', parse_attributes(match.group("attributes")),
                           para_parser.parse(match.group('content'), self.doc, strip=False), indent=indent)
        return "SAM", context

    def _record_start(self, context):
        source, match = context
        indent = len(match.group("indent"))
        record_name = match.group("name").strip()
        attributes = parse_attributes(match.group('attributes'))
        field_names = [x.strip() for x in match.group("field_names").split(',')]
        self.doc.new_record_set(record_name, attributes, field_names, indent)
        return "RECORD", context

    def _record(self, context):
        source, match = context
        try:
            line = source.next_line
        except EOFError:
            return "END", context
        indent = len(line) - len(line.lstrip())
        if self.patterns['blank-line'].match(line):
            return "RECORD", context
        if indent < self.doc.current_block.indent:
            source.return_line()
            return "SAM", context
        else:
            field_values = [x.strip() for x in re.split(r'(?<!\\),', line)]
            if len(field_values) != len(self.doc.fields):
                raise SAMParserError("Record length does not match record set header. At:\n\n " + line)
            record = list(zip(self.doc.fields, field_values))
            self.doc.new_record(record, indent)
            return "RECORD", context

    def _grid_start(self, context):
        source, match = context
        indent = len(match.group('indent'))

        attributes = {}

        attributes_string = match.group("attributes")
        if attributes_string is not None:
            attributes.update(parse_attributes(attributes_string))

        self.doc.new_block('grid', attributes, None, indent)
        return "GRID", context

    def _grid(self, context):
        source, match = context
        try:
            line = source.next_line
        except EOFError:
            return "END", context
        indent = len(line) - len(line.lstrip())
        if self.patterns['blank-line'].match(line):
            return "GRID", context
        elif indent < self.doc.current_block.indent:
            source.return_line()
            return "SAM", context
        else:
            cell_values = [x.strip() for x in re.split(r'(?<!\\)\|', line)]
            if self.doc.current_block.name == 'row':
                if len(self.doc.current_block.children) != len(cell_values):
                    raise SAMParserError('Uneven number of cells in grid row at: "' + line + '"')
            self.doc.new_block('row', None, None, indent)
            for content in cell_values:
                self.doc.new_block('cell', None, None, indent + 1)
                self.doc.new_flow(para_parser.parse(content, self.doc))
            # Test for consistency with previous rows?

            return "GRID", context

    def _embedded_xml(self, context):
        source, match = context
        indent = len(match.group("indent"))
        embedded_xml_parser = xml.parsers.expat.ParserCreate()
        embedded_xml_parser.XmlDeclHandler = self._embedded_xml_declaration_check
        embedded_xml_parser.Parse(source.current_line.strip())
        xml_lines = []
        try:
            while True:
                line = source.next_line
                xml_lines.append(line)
                embedded_xml_parser.Parse(line)
        except xml.parsers.expat.ExpatError as err:
            if err.code == 9:  # junk after document element
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

        match = self.patterns['embed-start'].match(line)
        if match is not None:
            return "EMBED-START", (source, match)

        match = self.patterns['blockquote-start'].match(line)
        if match is not None:
            return "BLOCKQUOTE-START", (source, match)

        match = self.patterns['fragment-start'].match(line)
        if match is not None:
            return "FRAGMENT-START", (source, match)

        match = self.patterns['grid-start'].match(line)
        if match is not None:
            return "GRID-START", (source, match)

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

        match = self.patterns['include'].match(line)
        if match is not None:
            return "INCLUDE", (source, match)

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
        yield from self.doc.serialize(serialize_format)



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
        self.parent.add_child(b)

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
            for key, value in sorted(self.attributes.items()):
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


class Paragraph(Block):
    def __init__(self, attributes=None, content=None, namespace=None, indent=0):
        super().__init__(name='p', attributes=attributes, content=content, namespace=namespace, indent=indent)

    def add_child(self, b):
        if not type(b) is Flow:
            raise SAMParserError(
                'A paragraph cannot have block children. At \"{0}\".'.format(
                    str(self)))
        b.parent = self
        self.children.append(b)


class Comment:
    def __init__(self, content='', indent=0):
        self.content=content
        self.indent=indent

    def __str__(self):
        return u"[#comment:'{1:s}']".format(self.content)

    def serialize_xml(self):
        yield '<!-- {0} -->\n'.format(self.content.replace('--', '-\-'))


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
        self.name = '/'
        self.attributes = None
        self.content = None
        self.indent = -1
        self.parent = None
        self.children = []

    def serialize_xml(self):
        yield '<?xml version="1.0" encoding="UTF-8"?>\n'
        for x in self.children:
            yield from x.serialize_xml()

    def add_child(self, b):
        # This is a hack to catch the creation of a second root-level block.
        # It is not good because people can add to the children list without
        # calling this function. Not sure what the options are. Could detect
        # the error at the XML output stage, I suppose, but would rather
        # catch it earlier and give feedback.
        if any( issubclass(type(x), Block) for x in self.children):
            raise SAMParserError("A SAM document can only have one root. Found: "+ str(b))
        b.parent = self
        self.children.append(b)


class TextBlock:
    def __init__(self, line=None):
        self.lines = []
        if line:
            self.lines.append(line)

    def append(self, line):
        self.lines.append(line)

    def strip(self):
        """
        Removes blank lines from the beginning and end of the text block
        :return: Stripped text block
        """
        first_non_blank_line = 0
        for i in self.lines:
            if i.strip() == '':
                first_non_blank_line += 1
            else:
                break

        last_non_blank_line = len(self.lines)
        for i in reversed(self.lines):
            if i.strip() == '':
                last_non_blank_line -= 1
            else:
                break

        self.lines = self.lines[first_non_blank_line:last_non_blank_line]
        return self

    @property
    def text(self):
        return " ".join(x.strip() for x in self.lines)


class Flow(list):
    def __str__(self):
        return "[{0}]".format(''.join([str(x) for x in self]))

    def append(self, thing):
        if type(thing) is Attribute:
            for i in reversed(self):
                if type(i is Phrase):
                    i.add_attribute(thing)
                    break

        elif type(thing) is Annotation:
            if type(self[-1]) is Phrase:
                self[-1].append(thing)
            else:
                super(Flow, self).append(thing)
        elif type(thing) is Citation:
            if type(self[-1]) is Phrase:
                self[-1].append(thing)
            else:
                super(Flow, self).append(thing)
        elif not thing == '':
            super(Flow, self).append(thing)

    def find_last_annotation(self, text):
        for i in reversed(self):

            if type(i) is Phrase:
                c = i.child
                while c:
                    if type(c) is Annotation:
                        if i.text == text:
                            return c
                    c=c.child


            # if type(i) is Annotation:
            #     if i.text == text:
            #         return i
        return None

    def serialize_xml(self):
        for x in self:
            try:
                yield from x.serialize_xml()
            except AttributeError:
                yield escape_for_xml(x)


class Pre(Flow):
    def __init__(self, text_block):
        raw_lines = []
        for line in text_block.lines:
            if not line.isspace():
                raw_lines.append((line, len(line) - len(line.lstrip())))
        try:
            min_indent = min(raw_lines, key=lambda t: t[1])[1]
        except ValueError:
            min_indent = 0
        self.lines = [x[min_indent:] if len(x) > min_indent else x for x in text_block.lines]

    def serialize_xml(self):
        for x in self.lines:
            yield escape_for_xml(x)



class EmbeddedXML(Block):
    def __init__(self, text, indent):
        self.text = text
        self.indent = indent
        self.namespace = None

    def serialize_xml(self):
        yield self.text


class DocStructure:
    def __init__(self):
        self.doc = None
        self.fields = None
        self.current_record = None
        self.current_block = None
        self.default_namespace = None
        self.ids = []
        self.indent=0

    def context(self, context_block=None):
        context = []
        if context_block is None:
            context_block = self.current_block
        try:
            while True:
                context.append(context_block.name)
                context_block = context_block.parent
        finally:
            return context

    def in_context(self, context_query):
        c = self.context()
        for i, cq in enumerate(context_query):
            if c[i] != cq:
                return False
        return True

    def context_at_indent(self, indent):
        c = self.current_block
        if c.indent < indent:
            return []
        try:
            while True:
                if c.indent == indent:
                    return self.context(c)
                c = c.parent
        except AttributeError:
            raise SAMParserError("Indentation error found at " + str(self.current_block))

    def new_root(self, match):
        if match.group('schema') is not None:
            pass
        elif match.group('namespace') is not None:
            self.default_namespace = match.group('namespace')
        r = Root()
        self.doc = r
        self.current_block = r

    def new_include(self, href, indent):

        reader = codecs.getreader("utf-8")

        href = pathlib.Path(os.path.abspath(href)).as_uri()
        SAM_parser_info("Parsing include " + href)
        try:
            includeparser = SamParser()
            with urllib.request.urlopen(href) as response:
                includeparser.parse(reader(response))
            include = Include(includeparser.doc.doc.children, indent)
            self.add_block(include)

        except SAMParserError as e:
            SAM_parser_warning("Unable to parse " + href + " because " + str(e))
        finally:
            SAM_parser_info("Finished parsing include " + href)

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
        try:
            if 'id' in block.attributes:
                if block.attributes['id'] in self.ids:
                    raise SAMParserError("Duplicate ID found: " + block.attributes['id'])
                self.ids.append(block.attributes['id'])
        except (TypeError, AttributeError):
            pass

        if block.namespace is None and self.default_namespace is not None:
            block.namespace = self.default_namespace

        if self.doc is None:
            raise SAMParserError('No root element found.')
        elif self.current_block.indent < block.indent:
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

    def new_paragraph(self, attributes, text, indent):
        b = Paragraph(attributes, text, None, indent)
        self.add_block(b)
        return b

    def new_unordered_list_item(self, attributes, indent):
        uli = Block('li', attributes, '', None, indent + .1)
        if self.context_at_indent(indent + .1)[:2] == ['li', 'ul']:
            self.add_block(uli)
        else:
            ul = Block('ul', None, '', None, indent)
            self.add_block(ul)
            self.add_block(uli)
        p = Paragraph(None, '', None, indent + .2)
        self.add_block(p)

    def new_ordered_list_item(self, attributes, indent):
        oli = Block('li', attributes, '', None, indent + .1)
        if self.context_at_indent(indent + .1)[:2] == ['li', 'ol']:
            self.add_block(oli)
        else:
            ol = Block('ol', None, '', None, indent)
            self.add_block(ol)
            self.add_block(oli)
        p = Paragraph(None, '', None, indent + .2)
        self.add_block(p)

    def new_labeled_list_item(self, attributes, indent, label):
        lli = Block('li', attributes, '', None, indent + .2)
        lli.add_child(Block('label', None, para_parser.parse(label, self.doc), None, indent))
        if self.current_block.name == 'li':
            self.current_block.add_sibling(lli)
        else:
            ll = Block('ll', None, '', None, indent)
            self.add_block(ll)
            ll.add_child(lli)

        # Assign the paragraph a fractional indent so that any following
        # element that is not an ll we be at same indent as ll, causing
        # ll to end. Because indent is fractional, and block child will
        # be more indented, which is illegal and will trigger an error.
        p = Paragraph(None, '', None, indent + .5)
        lli.add_child(p)
        self.current_block = p

    def new_flow(self, flow):
        ids=[f._id for f in flow if type(f) is Phrase and f._id is not None]
        for id in ids:
            if id in self.ids:
                raise SAMParserError("Duplicate ID found: " + ids[0])
            self.ids.append(id)
        self.current_block.add_child(flow)
        self.current_block = self.current_block.parent

    def new_comment(self, comment):
        self.current_block.add_child(comment)

    def new_embedded_xml(self, text, indent):
        b = EmbeddedXML(text=text, indent=indent)
        self.add_block(b)

    def new_string_def(self, string_name, value, indent):
        s = StringDef(string_name, value, indent)
        self.add_block(s)

    def new_record_set(self, name, attributes, field_names, indent):
        b = Block(name, attributes, None, None, indent)
        self.add_block(b)
        self.current_record = {'local_element': name, 'local_indent': indent}
        self.fields = field_names

    def new_record(self, record, indent):
        b = Block('row', None, '', None, indent)
        if self.current_block.indent == b.indent:
            self.current_block.add_sibling(b)
        else:
            self.current_block.add_child(b)

        self.current_block = b
        for name, content in record:
            b = Block(name, None, para_parser.parse(content, self.doc), None, self.current_block.indent + 4)
            self.current_block.add_child(b)

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


class Include(Block):
    def __init__(self, doc, indent):
        self.children=doc
        self.indent = indent
        self.namespace = None

    def serialize_xml(self):
        for x in self.children:
            yield from x.serialize_xml()


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


# Flow regex component expressions
re_single_quote_close = '(?<=[\w\.\,\"\)}])\'((?=[\.\s"}])|$)'
re_single_quote_open = '(^|(?<=[\s\"{]))\'(?=[\w"{])'
re_double_quote_close = '(?<=[\w\.\,\'\)\}])"((?=[\.\s\'\)},!:;])|$)'
re_double_quote_open = '(^|(?<=[\s\'{\(]))"(?=[\w\'{])'
re_apostrophe = "(?<=[\w`\*_])'(?=\w)"

smart_quote_subs = {re_double_quote_close:'”',
                    re_double_quote_open: '“',
                    re_single_quote_close:'’',
                    re_single_quote_open: '‘',
                    re_apostrophe: '’'}

class SamParaParser:
    def __init__(self):
        # These attributes are set by the parse method
        self.doc = None
        self.para = None
        self.current_string = None
        self.flow = None
        self.smart_quotes = False

        self.stateMachine = StateMachine()
        self.stateMachine.add_state("PARA", self._para)
        self.stateMachine.add_state("ESCAPE", self._escape)
        self.stateMachine.add_state("END", None, end_state=1)
        self.stateMachine.add_state("PHRASE-START", self._phrase_start)
        self.stateMachine.add_state("ANNOTATION-START", self._annotation_start)
        self.stateMachine.add_state("CITATION-START", self._citation_start)
        self.stateMachine.add_state("BOLD-START", self._bold_start)
        self.stateMachine.add_state("ITALIC-START", self._italic_start)
        self.stateMachine.add_state("CODE-START", self._code_start)
        self.stateMachine.add_state("DOUBLE_QUOTE", self._double_quote)
        self.stateMachine.add_state("SINGLE_QUOTE", self._single_quote)
        self.stateMachine.add_state("INLINE-INSERT", self._inline_insert)
        self.stateMachine.add_state("CHARACTER-ENTITY", self._character_entity)
        self.stateMachine.set_start("PARA")
        self.patterns = {
            'escape': re.compile(r'\\', re.U),
            'escaped-chars': re.compile('[\\\(\)\{\}\[\]_\*,\.\*`"&\<\>' + "']", re.U),
            'phrase': re.compile(r'(?<!\\)\{(?P<text>.*?)(?<!\\)\}'),
            'annotation': re.compile(
                r'(\(\s*(?P<type>\S*?\s*[^\\"\']?)(["\'](?P<specifically>.*?)["\'])??\s*(\((?P<namespace>\w+)\))?\))',
                re.U),
            'bold': re.compile(r'\*(?P<text>((?<=\\)\*|[^\*])*)(?<!\\)\*', re.U),
            'italic': re.compile(r'_(?P<text>((?<=\\)_|[^_])*)(?<!\\)_', re.U),
            'code': re.compile(r'`(?P<text>(``|[^`])*)`', re.U),
            'apostrophe': re.compile(re_apostrophe, re.U),
            'single_quote_close': re.compile(re_single_quote_close, re.U),
            'single_quote_open': re.compile(re_single_quote_open, re.U),
            'double_quote_close': re.compile(re_double_quote_close, re.U),
            'double_quote_open': re.compile(re_double_quote_open, re.U),
            'inline-insert': re.compile(r'>(?P<insert>\((.*?(?<!\\))\))' + re_attributes, re.U),

            'character-entity': re.compile(r'&(\#[0-9]+|#[xX][0-9a-fA-F]+|[\w]+);'),
            'citation': re.compile(
                r'((\[\s*\*(?P<id>\S+)(\s+(?P<id_extra>.+?))?\])|(\[\s*\#(?P<name>\S+)(\s+(?P<name_extra>.+?))?\])|(\[\s*(?P<citation>.*?)\]))',
                re.U)
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
            return "PHRASE-START", para
        elif char == '[':
            return "CITATION-START", para
        elif char == "*":
            return "BOLD-START", para
        elif char == "_":
            return "ITALIC-START", para
        elif char == "`":
            return "CODE-START", para
        elif char == '"':
            return "DOUBLE_QUOTE", para
        elif char == "'":
            return "SINGLE_QUOTE", para
        elif char == ">":
            return "INLINE-INSERT", para
        elif char == "&":
            return "CHARACTER-ENTITY", para
        else:
            self.current_string += char
            return "PARA", para

    def _phrase_start(self, para):
        match = self.patterns['phrase'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            text = self._unescape(match.group("text"))
            if self.smart_quotes:
                text=multi_replace(text, smart_quote_subs)
            # FIXME: Scan text for smart quotes
            self.flow.append(Phrase(text))
            para.advance(len(match.group(0)))

            if self.patterns['annotation'].match(para.rest_of_para):
                return "ANNOTATION-START", para
            elif self.patterns['citation'].match(para.rest_of_para):
                return "CITATION-START", para
            else:
                # If there is an annotated phrase with no annotation, look back
                # to see if it has been annotated already, and if so, copy the
                # closest preceding annotation.
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

                    # Else output a warning.
                    else:
                        SAM_parser_warning(
                            "Unannotated phrase found: {" +
                            text + "} " +
                            "If you are trying to insert curly braces " +
                            "into the document, use \{" + text + "}."
                        )
                para.retreat(1)
                return "PARA", para
        else:
            self.current_string += '{'
            return "PARA", para

    def _annotation_start(self, para):
        match = self.patterns['annotation'].match(para.rest_of_para)
        if match:
            annotation_type = match.group('type')

            # Check for link shortcut
            if urlparse(annotation_type, None).scheme is not None:
                specifically = annotation_type
                annotation_type = 'link'
            else:
                specifically = match.group('specifically') if match.group('specifically') is not None else None
            namespace = match.group('namespace').strip() if match.group('namespace') is not None else None
            if annotation_type[0] == '!':
                self.flow.append(Attribute('language', self._unescape(annotation_type[1:])))
            elif annotation_type[0] == '*':
                self.flow.append(Attribute('id', self._unescape(annotation_type[1:])))
            elif annotation_type[0] == '#':
                self.flow.append(Attribute('name', self._unescape(annotation_type[1:])))
            elif annotation_type[0] == '?':
                self.flow.append(Attribute('condition', self._unescape(annotation_type[1:])))
            else:
                self.flow.append(Annotation(annotation_type, self._unescape(specifically), namespace))
            para.advance(len(match.group(0)))
            if self.patterns['annotation'].match(para.rest_of_para):
                return "ANNOTATION-START", para
            elif self.patterns['citation'].match(para.rest_of_para):
                return "CITATION-START", para
            else:
                para.retreat(1)
                return "PARA", para
        else:
            self.current_string += '{'
            return "PARA", para

    def _citation_start(self, para):
        match = self.patterns['citation'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''

            try:
                idref = match.group('id')
            except IndexError:
                idref = None
            try:
                nameref = match.group('name')
            except IndexError:
                nameref = None
            try:
                citation = match.group('citation')
            except IndexError:
                citation = None

            if idref:
                citation_type = 'idref'
                citation_value = idref.strip()
                extra = match.group('id_extra')
            elif nameref:
                citation_type = 'nameref'
                citation_value = nameref.strip()
                extra = match.group('name_extra')
            else:
                citation_type = 'citation'
                citation_value = citation.strip()
                extra = None

            self.flow.append(Citation(citation_type, citation_value, extra))
            para.advance(len(match.group(0)))
            if self.patterns['annotation'].match(para.rest_of_para):
                return "ANNOTATION-START", para
            elif self.patterns['citation'].match(para.rest_of_para):
                return "CITATION-START", para
            else:
                para.retreat(1)
                return "PARA", para
        else:
            self.current_string += '['
            return "PARA", para

    def _bold_start(self, para):
        match = self.patterns['bold'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            self.flow.append(Phrase(self._unescape(match.group("text"))))
            self.flow.append(Annotation('bold'))
            para.advance(len(match.group(0)) - 1)
        else:
            self.current_string += '*'
        return "PARA", para

    def _italic_start(self, para):
        match = self.patterns['italic'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            self.flow.append(Phrase(self._unescape(match.group("text"))))
            self.flow.append(Annotation('italic'))
            para.advance(len(match.group(0)) - 1)
        else:
            self.current_string += '_'
        return "PARA", para

    def _code_start(self, para):
        match = self.patterns['code'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            self.flow.append(Phrase((match.group("text")).replace("``", "`")))
            self.flow.append(Annotation('code'))
            para.advance(len(match.group(0)) - 1)
        else:
            self.current_string += '`'
        return "PARA", para

    def _double_quote(self, para):
        if self.smart_quotes:
            if self.patterns['double_quote_close'].search(para.para, para.currentCharNumber,
                                                          para.currentCharNumber + 2):
                self.current_string += '”'
            elif self.patterns['double_quote_open'].search(para.para, para.currentCharNumber,
                                                           para.currentCharNumber + 2):
                self.current_string += '“'
            else:
                self.current_string += '"'
                SAM_parser_warning(
                    'Detected straight double quote that was not recognized by smart quote rules in: "' + para.para + '" at position ' + str(
                        para.currentCharNumber))
        else:
            self.current_string += '"'
        return "PARA", para

    def _single_quote(self, para):
        if self.smart_quotes:
            if self.patterns['single_quote_close'].search(para.para, para.currentCharNumber,
                                                          para.currentCharNumber + 2):
                self.current_string += '’'
            elif self.patterns['single_quote_open'].search(para.para, para.currentCharNumber,
                                                           para.currentCharNumber + 2):
                self.current_string += '‘'
            elif self.patterns['apostrophe'].search(para.para, para.currentCharNumber, para.currentCharNumber + 2):
                self.current_string += '’'
            else:
                self.current_string += "'"
                SAM_parser_warning(
                    'Detected straight single quote that was not recognized by smart quote rules in: "' + para.para + '" at position ' + str(
                        para.currentCharNumber))
        else:
            self.current_string += "'"
        return "PARA", para

    def _inline_insert(self, para):
        match = self.patterns['inline-insert'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            attributes = parse_insert(match.group("insert"))
            attributes.update( parse_attributes(match.group("attributes")))

            self.flow.append(InlineInsert(attributes))
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

    def _character_entity(self, para):
        match = self.patterns['character-entity'].match(para.rest_of_para)
        if match:
            self.current_string += self.patterns['character-entity'].sub(self._replace_charref, match.group(0))
            para.advance(len(match.group(0)) - 1)
        else:
            self.current_string += '&'
        return "PARA", para

    def _replace_charref(self, match):
        try:
            charref = match.group(0)
        except AttributeError:
            charref = match
        character = html.unescape(charref)
        if character == charref:  # Escape not recognized
            raise SAMParserError("Unrecognized character entity found: " + charref)
        return character

    def _escape(self, para):
        char = para.next_char
        if self.patterns['escaped-chars'].match(char):
            self.current_string += char
        else:
            self.current_string += '\\' + char
        return "PARA", para

    def _unescape(self, string):
        result = ''
        try:
            e = enumerate(string)
            for pos, char in e:
                try:
                    if char == '\\' and self.patterns['escaped-chars'].match(string[pos + 1]):
                        result += string[pos + 1]
                        next(e, None)
                    elif char == '&':
                        match = self.patterns['character-entity'].match(string[pos:])
                        if match:
                            result += self.patterns['character-entity'].sub(self._replace_charref, match.group(0))
                            for i in range(1, len(match.group(0))):
                                next(e, None)
                        else:
                            result += char
                    else:
                        result += char
                except IndexError:
                    result += char
            return result
        except TypeError:
            return string


class Phrase:
    def __init__(self, text):
        self.text = text
        self.child = None
        self._id = None
        self._name = None
        self._language = None
        self._conditions = []

    def __str__(self):
        return u'{{{0:s}}}'.format(self.text)

    def add_attribute(self,attr):
        if attr.type == 'id':
            self.id = attr.value
        elif attr.type == 'name':
            self.name = attr.value
        elif attr.type == 'language':
            self.language = attr.value
        elif attr.type == 'condition':
            self.condition = attr.value


    def setid(self, id):
        if self._id is not None:
            raise SAMParserError("A phrase cannot have more than one ID: "+ self._id + ',' + id)
        self._id = id

    id = property(None,setid)

    def setname(self, name):
        if self._name is not None:
            raise SAMParserError("A phrase cannot have more than one name: "+ self._name + ',' + name)
        self._name = name

    name = property(None,setname)

    def setlanguage(self, language):
        if self._language is not None:
            raise SAMParserError("A phrase cannot have more than one language: "+ self._language + ',' + language)
        self._language = language

    language = property(None,setlanguage)

    def setcondition(self, condition):
        self._conditions.append(condition)

    condition = property(None,setcondition)

    def serialize_xml(self):
        yield '<phrase'
        if self._id:
            yield ' id="' + escape_for_xml_attribute(self._id) + '"'
        if self._conditions:
            yield ' conditions="' + ",".join(self._conditions) + '"'
        if self._name:
            yield ' name="' + escape_for_xml_attribute(self._name) + '"'
        if self._language:
            yield ' xml:lang="' + escape_for_xml_attribute(self._language) + '"'
        yield '>'
        if self.child:
            yield from self.child.serialize_xml(escape_for_xml(self.text))
        else:
            yield escape_for_xml(self.text)
        yield '</phrase>'

    def append(self, thing):
        if not self.child:
            self.child = thing
        else:
            self.child.append(thing)


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

    def retreat(self, count):
        self.currentCharNumber -= count


class Attribute:
    def __init__(self, type, value):
        self.type = type
        self.value = value

    def __str__(self):
        return '%s ="%s" ' % (self.type, self.value)

    def serialize_xml(self):
        if self.type == 'language':
             yield ' xml:lang ="%s"' % (escape_for_xml_attribute(self.value))
        else:
            yield ' %s ="%s"' % (self.type, escape_for_xml_attribute(self.value))


class Annotation:
    def __init__(self, annotation_type, specifically='', namespace='', language=''):
        self.annotation_type = annotation_type.strip()
        self.specifically = specifically
        self.namespace = namespace
        self.language = language
        self.child = None

    def __str__(self):
        return '(%s "%s" (%s))' % (self.annotation_type, self.specifically, self.namespace)

    def serialize_xml(self, payload=None):
        yield '<annotation'
        if self.annotation_type:
            yield ' type="{0}"'.format(self.annotation_type)
        if self.specifically:
            yield ' specifically="{0}"'.format(escape_for_xml_attribute(self.specifically))
        if self.namespace:
            yield ' namespace="{0}"'.format(self.namespace)
        if self.language:
            yield ' xml:lang="{0}"'.format(self.language)
        if self.child:
            yield '>'
            yield from self.child.serialize_xml(payload)
            yield '</annotation>'
        elif payload:
            yield '>'
            yield payload
            yield '</annotation>'
        else:
            yield '/>'

    def append(self, thing):
        if not self.child:
            self.child = thing
        else:
            self.child.append(thing)


class Citation:
    def __init__(self, citation_type, citation_value, citation_extra):
        self.citation_type = citation_type
        self.citation_value = citation_value
        self.citation_extra = citation_extra
        self.child = None

    def __str__(self):
        cit_extra = self.citation_extra if self.citation_extra else ''
        return u'[{0:s} {1:s} {2:s}]'.format(self.citation_type, self.citation_value,
                                             cit_extra)

    def serialize_xml(self, payload=None):
        yield '<citation type="{0}" value="{1}"'.format(self.citation_type, escape_for_xml_attribute(self.citation_value))
        if self.citation_extra is not None:
            if self.citation_extra:
                yield ' extra="{0}"'.format(escape_for_xml_attribute(self.citation_extra))
        if self.child:
            yield '>'
            yield from self.child.serialize_xml(payload)
            yield '</citation>'
        elif payload:
            yield '>'
            yield payload
            yield '</citation>'
        else:
            yield '/>'

    def append(self, thing):
        if not self.child:
            self.child = thing
        else:
            self.child.append(thing)


class InlineInsert:
    def __init__(self, attributes):
        self.attributes = attributes

    def __str__(self):
        return "[#insert:'%s']" % self.attributes

    def serialize_xml(self):
        yield '<insert'
        for key, value in sorted(self.attributes.items()):
            yield " {0}=\"{1}\"".format(key, escape_for_xml_attribute(value))
        yield '/>'


class SAMParserError(Exception):
    """
    Raised if the SAM parser encounters an error.
    """

def parse_attributes(attributes_string, flagged="?#*!", unflagged=None):
    result = {}
    try:
        #attributes_list = attributes_string.split()
        attributes_list = [x[1:-1].strip() for x in re.findall(r"(\(.*?(?<!\\)\))", attributes_string)]
    except AttributeError:
        return None
    unflagged_attributes = [x for x in attributes_list if not (x[0] in '?#*!')]
    if unflagged_attributes:
        if unflagged is None:
            raise SAMParserError("Unexpected attribute(s): {0}".format(', '.join(unflagged_attributes)))
        else:
            result[unflagged] = " ".join(unflagged_attributes)
    ids = [x[1:] for x in attributes_list if x[0] == '*']
    if ids and not '*' in flagged:
        raise SAMParserError("IDs not allowed in this context. Found: *{0}".format(', *'.join(ids)))
    if len(ids) > 1:
        raise SAMParserError("More than one ID specified: " + ", ".join(ids))
    names = [x[1:] for x in attributes_list if x[0] == '#']
    if names and not '#' in flagged:
        raise SAMParserError("Names not allowed in this context. Found: #{0}".format(', #'.join(names)))
    if len(names) > 1:
        raise SAMParserError("More than one name specified: " + ", ".join(names))
    language = [x[1:] for x in attributes_list if x[0] == '!']
    if language and not '!' in flagged:
        raise SAMParserError("Language specification not allowed in this context. Found: !{0}".format(', !'.join(language)))
    if len(language) > 1:
        raise SAMParserError("More than one language specified: " + ", ".join(language))
    conditions = [x[1:] for x in attributes_list if x[0] == '?']
    if ids:
        # if ids[0] in self.doc.ids:
        #     raise SAMParserError("Duplicate ID found: " + ids[0])
        # self.doc.ids.extend(ids)
        result["id"] = "".join(ids)
    if names:
        result["name"] = "".join(names)
    if language:
        result["xml:lang"] = "".join(language)
    if conditions:
        result["conditions"] = ",".join(conditions)
    return result


def parse_insert(annotation_string):
    result = {}

    insert_annotation = re.match(r'(\(.*?(?<!\\)\))', annotation_string)
    attributes_list = insert_annotation.group(0)[1:-1].split()
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
        raise SAMParserError("SAM parser error: More than one ID specified: " + ", ".join(insert_ids))
    if len(insert_names) > 1:
        raise SAMParserError("SAM parser error: More than one name specified: " + ", ".join(insert_names))
    if unexpected_attributes:
        raise SAMParserError("SAM parser error: Unexpected insert attribute(s): {0}".format(unexpected_attributes))
    result['type'] = insert_type
    # strip unnecessary quotes from insert item
    insert_item = re.sub(r'^(["\'])|(["\'])$', '', insert_item)
    result['item'] = insert_item
    return result


def escape_for_xml(s):
    t = dict(zip([ord('<'), ord('>'), ord('&')], ['&lt;', '&gt;', '&amp;']))
    try:
        return s.translate(t)
    except AttributeError:
        return s

def escape_for_xml_attribute(s):
    t = dict(zip([ord('<'), ord('>'), ord('&'), ord('"')], ['&lt;', '&gt;', '&amp;', '&quot;']))
    try:
        return s.translate(t)
    except AttributeError:
        return s


def multi_replace(string, subs):
    for pattern, sub in subs.items():
        r = re.compile(pattern)
        string= r.sub(sub, string)
    return string


def SAM_parser_warning(warning):
    print("SAM parser warning: " + warning, file=sys.stderr)

def SAM_parser_info(info):
    print("SAM parser information: " + info, file=sys.stderr)


para_parser = SamParaParser()

if __name__ == "__main__":

    import glob
    import os.path
    argparser = argparse.ArgumentParser()

    argparser.add_argument("infile", help="the SAM file to be parsed")
    outputgroup = argparser.add_mutually_exclusive_group()
    outputgroup.add_argument("-outfile", "-o", help="the name of the output file")
    outputgroup.add_argument("-outdir", "-od", help="the name of output directory")
    argparser.add_argument("-xslt", "-x", help="name of xslt file for postprocessing output")
    intermediategroup = argparser.add_mutually_exclusive_group()
    intermediategroup.add_argument("-intermediatefile", "-i", help="name of file to dump intermediate XML to when using -xslt")
    intermediategroup.add_argument("-intermediatedir", "-id", help="name of directory to dump intermediate XML to when using -xslt")
    argparser.add_argument("-smartquotes", "-q", help="turn on smart quotes processing",
                           action="store_true")
    argparser.add_argument("-xsd", help="Specify an XSD schema to validate generated XML")
    argparser.add_argument("-outputextension", "-oext",  nargs='?', const='.xml', default='.xml')
    argparser.add_argument("-intermediateextension", "-iext",  nargs='?', const='.xml', default='.xml')


    args = argparser.parse_args()
    transformed = None

    samParser = SamParser()

    if args.smartquotes:
        para_parser.smart_quotes = True

    if (args.intermediatefile or args.intermediatedir) and not args.xslt:
        raise SAMParserError("Do not specify an intermediate file or directory if an XSLT file is not specified.")

    if args.infile == args.outfile:
        raise SAMParserError('Input and output files cannot have the same name.')

    for inputfile in glob.glob(args.infile):
        SAM_parser_info("Parsing " + inputfile)
        try:
            with open(inputfile, "r", encoding="utf-8-sig") as inf:
                samParser.parse(inf)


                xml_string = "".join(samParser.serialize('xml')).encode('utf-8')
                xml_doc = etree.fromstring(xml_string)

                if args.xslt:
                    try:
                        with open(args.xslt, "r") as xsltf:
                            transform = etree.XSLT(etree.parse(xsltf))
                    except FileNotFoundError as e:
                        raise SAMParserError(e.strerror + ' ' + e.filename)

                    transformed = transform(xml_doc)

                if args.outdir:
                    outputfile=os.path.join(args.outdir, os.path.splitext(os.path.basename(inputfile))[0] + args.outputextension)
                else:
                    outputfile=args.outfile

                if outputfile:
                    if transformed:
                        with open(outputfile, "wb") as outf:
                            outf.write(str(transformed).encode(encoding='utf-8'))

                        if transform.error_log:
                            SAM_parser_warning("Messages from the XSLT transformation:")
                        for entry in transform.error_log:
                            print('message from line %s, col %s: %s' % (
                                entry.line, entry.column, entry.message), file=sys.stderr)
                            print('domain: %s (%d)' % (entry.domain_name, entry.domain), file=sys.stderr)
                            print('type: %s (%d)' % (entry.type_name, entry.type), file=sys.stderr)
                            print('level: %s (%d)' % (entry.level_name, entry.level), file=sys.stderr)

                    else:
                        with open(outputfile, "wb") as outf:
                            outf.write(xml_string)
                else:
                    if transformed:
                        sys.stdout.buffer.write(transformed)
                    else:
                        for i in samParser.serialize('xml'):
                            sys.stdout.buffer.write(i.encode('utf-8'))

                if args.intermediatedir:
                    intermediatefile=os.path.join(args.intermediatedir, os.path.splitext(os.path.basename(inputfile))[0] + args.intermediateextension)
                else:
                    intermediatefile=args.intermediatefile

                if intermediatefile:
                    with open(intermediatefile, "wb") as intermediate:
                        intermediate.write(xml_string)

                if args.xsd:
                    try:
                        xmlschema = etree.XMLSchema(file=args.xsd)
                    except etree.XMLSchemaParseError as e:
                        print(e, file=sys.stderr)
                        exit(1)

                    try:
                        xmlschema.assertValid(xml_doc)
                    except etree.DocumentInvalid as e:
                        print('STRUCTURE ERROR: ' + str(e), file=sys.stderr)
                        #exit(1)



        except FileNotFoundError:
            raise SAMParserError("No input file specified.")

        except SAMParserError as e:
            sys.stderr.write('SAM parser ERROR: ' + str(e) + "\n")
            #sys.exit(1)
            continue
