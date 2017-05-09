import sys
from statemachine import StateMachine
from lxml import etree
import xml.parsers.expat
import html
import argparse
import urllib.request
import pathlib
import codecs
import os
from abc import ABC, abstractmethod

from urllib.parse import urlparse

try:
    import regex as re
except ImportError:
    import re

# Block regex component expressions
re_indent = r'(?P<indent>\s*)'
re_attributes = r'(?P<attributes>((\((.*?(?<!\\))\))|(\[(.*?(?<!\\])\])))*)'
re_content = r'(?P<content>.*)'
re_remainder = r'(?P<remainder>.*)'
re_name = r'(?P<name>\w[^\s`]*?)'
re_ul_marker = r'(?P<marker>\*)'
re_ol_marker = r'(?P<marker>[0-9]+\.)'
re_ll_marker = r'\|(?P<label>\S.*?)(?<!\\)\|'
re_spaces = r'\s+'
re_one_space = r'\s'
re_comment = r'#(?P<comment>.*)'
re_citation = r'(\[\s*\*(?P<id>\S+)(?P<id_extra>.*?)\])|(\[\s*\#(?P<name>\S+)(?P<name_extra>.*?)\])|(\[\s*(?P<citation>.*?)\])'

class SamParser:
    def __init__(self):

        self.stateMachine = StateMachine()
        self.stateMachine.add_state("SAM", self._sam)
        self.stateMachine.add_state("BLOCK", self._block)
        self.stateMachine.add_state("CODEBLOCK-START", self._codeblock_start)
        self.stateMachine.add_state("CODEBLOCK", self._codeblock)
        self.stateMachine.add_state("REMARK-START", self._remark_start)
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
        self.stateMachine.set_start("SAM")
        self.current_text_block = None
        self.doc = None
        self.source = None
        self.sourceurl = None
        self.smart_quotes = False
        self.patterns = {
            'comment': re.compile(re_indent + re_comment, re.U),
            'remark-start': re.compile(
                re_indent + r'(?P<flag>!!!)(' + re_attributes + ')?\s*(?P<unexpected>.*)',
                re.U),
            'declaration': re.compile(re_indent + '!' + re_name + r'(?<!\\):' + re_content + r'?', re.U),
            'block-start': re.compile(re_indent + re_name + r'(?<!\\):' + re_attributes + '\s' + re_content + r'?', re.U),
            'codeblock-start': re.compile(
                re_indent + r'(?P<flag>```)(' + re_attributes + ')?\s*(?P<unexpected>.*)',
                re.U),
            'embed-start': re.compile(
                re_indent + r'(?P<flag>===)(' + re_attributes + ')?\s*(?P<unexpected>.*)',
                re.U),
            'grid-start': re.compile(re_indent + r'\+\+\+' + re_attributes, re.U),
            'blockquote-start': re.compile(
                re_indent + r'("""|\'\'\')(' + re_remainder + r')?',
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
        self.doc = DocStructure()
        try:
            self.sourceurl = source.geturl()
        except AttributeError:
            try:
                self.sourceurl = pathlib.Path(os.path.abspath(source.name)).as_uri()
            except AttributeError:
                self.sourceurl = None
        try:
            self.stateMachine.run((self.source, None))
        except EOFError:
            raise SAMParserError("Document ended before structure was complete.")
        return self.doc

    def _block(self, context):
        source, match = context
        indent = match.end("indent")
        block_name = match.group("name").strip()
        attributes, citations = parse_attributes(match.group("attributes"))
        content = match.group("content").strip()
        parsed_content = None if content == '' else flow_parser.parse(content, self.doc)
        b = Block(block_name, indent, attributes, parsed_content, citations)
        self.doc.add_block(b)
        return "SAM", context

    def _codeblock_start(self, context):
        source, match = context
        if match.group("unexpected"):
            raise SAMParserError("Unexpected characters in codeblock header. Found: " + match.group("unexpected"))
        indent = match.end("indent")

        attributes, citations = parse_attributes(match.group("attributes"), flagged="*#?", unflagged="language")

        b = Codeblock(indent, attributes, citations)
        self.doc.add_block(b)
        self.current_text_block = UnparsedTextBlock()
        return "CODEBLOCK", context

    def _codeblock(self, context):
        source, match = context
        try:
            line = source.next_line
        except EOFError:
            self.doc.add_flow(Pre(self.current_text_block))
            self.current_text_block = None
            return "END", context

        indent = len(line) - len(line.lstrip())
        if self.patterns['blank-line'].match(line):
            self.current_text_block.append(line)
            return "CODEBLOCK", context
        if indent <= self.doc.ancestor_or_self_type(Codeblock).indent:
            source.return_line()
            self.doc.add_flow(Pre(self.current_text_block.strip()))
            self.current_text_block = None
            return "SAM", context
        else:
            self.current_text_block.append(line)
            return "CODEBLOCK", context

    def _remark_start(self, context):
        source, match = context
        if match.group("unexpected"):
            raise SAMParserError("Unexpected characters in remark header. Found: " + match.group("unexpected"))
        indent = match.end("indent")

        attributes, citations = parse_attributes(match.group("attributes"), flagged="*!", unflagged="attribution")

        b = Remark(indent, attributes, citations)
        self.doc.add_block(b)
        return "SAM", context

    def _embed_start(self, context):
        source, match = context
        if match.group("unexpected"):
            raise SAMParserError("Unexpected characters in embed header. Found: " + match.group("unexpected"))
        indent = match.end("indent")

        attributes, citations = parse_attributes(match.group("attributes"), flagged="*#?", unflagged="language")

        b = Embed(indent, attributes, citations)
        self.doc.add_block(b)
        self.current_text_block = UnparsedTextBlock()
        return "EMBED", context

    def _embed(self, context):
        source, match = context
        try:
            line = source.next_line
        except EOFError:
            self.doc.add_flow(Pre(self.current_text_block))
            self.current_text_block = None
            return "END", context

        indent = len(line) - len(line.lstrip())
        if self.patterns['blank-line'].match(line):
            self.current_text_block.append(line)
            return "EMBED", context
        if indent <= self.doc.ancestor_or_self_type(Embed).indent:
            source.return_line()
            self.doc.add_flow(Pre(self.current_text_block.strip()))
            self.current_text_block = None
            return "SAM", context
        else:
            self.current_text_block.append(line)
            return "EMBED", context

    def _blockquote_start(self, context):
        source, match = context
        indent = match.end("indent")
        attributes, citations = parse_attributes(match.group("remainder"))
        b = Blockquote(indent, attributes, citations)
        self.doc.add_block(b)
        return "SAM", context

    def _fragment_start(self, context):
        source, match = context
        indent = match.end("indent")
        attributes, citations =  parse_attributes(match.group("attributes"))
        b = Fragment(indent, attributes, citations)
        self.doc.add_block(b)
        return "SAM", context

    def _paragraph_start(self, context):
        source, match = context
        line = source.current_line
        local_indent = len(line) - len(line.lstrip())
        b = Paragraph(local_indent)
        self.doc.add_block(b)
        self.current_text_block = UnparsedTextBlock(line)
        return "PARAGRAPH", context

    def _paragraph(self, context):
        source, match = context
        try:
            line = source.next_line
        except EOFError:
            f = flow_parser.parse(self.current_text_block.text, self.doc)
            self.current_text_block = None
            self.doc.add_flow(f)
            return "END", context

        para_indent = self.doc.current_block.indent
        first_line_indent = len(match.string) - len(match.string.lstrip())
        this_line_indent = len(line) - len(line.lstrip())

        if self.patterns['blank-line'].match(line):
            f = flow_parser.parse(self.current_text_block.text, self.doc)
            self.current_text_block = None
            self.doc.add_flow(f)
            return "SAM", context

        if this_line_indent < para_indent:
            f = flow_parser.parse(self.current_text_block.text, self.doc)
            self.current_text_block = None
            self.doc.add_flow(f)
            source.return_line()
            return "SAM", context

        if self.doc.in_context(['p', 'li']):
            if self.patterns['list-item'].match(line) or self.patterns['num-list-item'].match(line) or self.patterns[
                'labeled-list-item'].match(line):
                f = flow_parser.parse(self.current_text_block.text, self.doc)
                self.current_text_block = None
                self.doc.add_flow(f)
                source.return_line()
                return "SAM", context

        self.current_text_block.append(line)
        return "PARAGRAPH", context

    def _list_item(self, context):
        source, match = context
        indent = match.end("indent")
        content_start=match.start("content")
        attributes, citations = parse_attributes(match.group("attributes"))
        uli = UnorderedListItem(indent, attributes, citations)
        self.doc.add_block(uli)
        p = Paragraph(content_start)
        self.doc.add_block(p)
        self.current_text_block = UnparsedTextBlock(str(match.group("content")).strip())
        return "PARAGRAPH", context

    def _num_list_item(self, context):
        source, match = context
        indent = match.end("indent")
        content_start=match.start("content")
        attributes, citations = parse_attributes(match.group("attributes"))
        oli = OrderedListItem(indent, attributes, citations)
        self.doc.add_block(oli)
        p = Paragraph(content_start)
        self.doc.add_block(p)

        self.current_text_block = UnparsedTextBlock(str(match.group("content")).strip())
        return "PARAGRAPH", context

    def _labeled_list_item(self, context):
        source, match = context
        indent = match.end("indent")
        label = match.group("label")
        content_start = match.start("content")
        attributes, citations = parse_attributes(match.group("attributes"))
        lli = LabeledListItem(indent, flow_parser.parse(label, self.doc), attributes, citations)
        self.doc.add_block(lli)
        p = Paragraph(content_start)
        self.doc.add_block(p)
        self.current_text_block = UnparsedTextBlock(str(match.group("content")).strip())
        return "PARAGRAPH", context

    def _block_insert(self, context):
        source, match = context
        if match.group("unexpected"):
            raise SAMParserError("Unexpected characters in block insert. Found: " + match.group("unexpected"))
        indent = match.end("indent")
        attributes, citations = parse_attributes(match.group("attributes"), flagged="*#?")
        attributes.extend(parse_insert(match.group("insert")))
        b = BlockInsert(indent, attributes, citations)
        self.doc.add_block(b)
        return "SAM", context

    def _include(self, context):
        source, match = context
        indent = match.end("indent")
        href=match.group("attributes")[1:-1]
        # FIXME: Should validate attributes.
        if bool(urllib.parse.urlparse(href).netloc):  # An absolute URL
            fullhref = href
        elif os.path.isabs(href):  # An absolute file path
            fullhref = pathlib.Path(href).as_uri()
        elif self.sourceurl:
            fullhref = urllib.parse.urljoin(self.sourceurl, href)
        else:
            SAM_parser_warning("Unable to resolve relative URL of include as source of parsed document not known.")
            return

        reader = codecs.getreader("utf-8")
        SAM_parser_info("Parsing include " + href)
        try:
            includeparser = SamParser()
            with urllib.request.urlopen(fullhref) as response:
                includeparser.parse(reader(response))
            include = Include(includeparser.doc, fullhref, indent)
            self.doc.add_block(include)
            SAM_parser_info("Finished parsing include " + href)
        except SAMParserError as e:
            SAM_parser_warning("Unable to parse " + href + " because " + str(e))
        except FileNotFoundError as e:
            SAM_parser_warning(str(e))
        except urllib.error.URLError as e:
            SAM_parser_warning(str(e))

        return "SAM", context

    def _string_def(self, context):
        source, match = context
        indent = match.end("indent")
        s = StringDef(match.group('name'), flow_parser.parse(match.group('content'), self.doc), indent=indent)
        self.doc.add_block(s)
        return "SAM", context

    def _line_start(self, context):
        source, match = context
        indent = match.end("indent")
        attributes, citations = parse_attributes(match.group("attributes"))
        b=Line(indent, attributes,
               flow_parser.parse(match.group('content'), self.doc, strip=False), citations)
        self.doc.add_block(b)
        return "SAM", context

    def _record_start(self, context):
        source, match = context
        indent = match.end("indent")
        record_name = match.group("name").strip()
        attributes, citations = parse_attributes(match.group('attributes'))
        field_names = [x.strip() for x in match.group("field_names").split(',')]
        rs = RecordSet(record_name, field_names, indent, attributes, citations)
        self.doc.add_block(rs)

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
            #FIXME: splitting field values belongs to record object
            field_values = [flow_parser.parse(x.strip(), self.doc) for x in re.split(r'(?<!\\),', line)]
            r = Record(field_values, indent)
            self.doc.add_block(r)

            return "RECORD", context

    def _grid_start(self, context):
        source, match = context
        indent = match.end("indent")
        attributes, citations = parse_attributes(match.group("attributes"))
        b = Grid(indent, attributes, citations)
        self.doc.add_block(b)
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
        elif indent <= self.doc.ancestor_or_self_type(Grid).indent:
            source.return_line()
            return "SAM", context
        else:
            cell_values = [x.strip() for x in re.split(r'(?<!\\)\|', line)]
            if self.doc.current_block.name == 'row':
                if len(self.doc.current_block.children) != len(cell_values):
                    raise SAMParserError('Uneven number of cells in grid row at: "' + line + '"')
            b = Row(indent)
            self.doc.add_block(b)

            for content in cell_values:
                b = Cell(indent)
                self.doc.add_block(b)

                self.doc.add_flow(flow_parser.parse(content, self.doc))
            # Test for consistency with previous rows?

            return "GRID", context

    def _embedded_xml(self, context):
        source, match = context
        indent = match.end("indent")
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
                b = EmbeddedXML(xml_text, indent)
                self.doc.add_block(b)
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

        match = self.patterns['declaration'].match(line)
        if match is not None:
            name = match.group('name').strip()
            content = match.group('content').strip()
            if self.doc.root.children:
                raise SAMParserError("Declarations must come before all other content. Found:" + match.group(0))
            if name == 'namespace':
                self.doc.default_namespace = content
            else:
                raise SAMParserError("Unknown declaration: " + match.group(0))

            return "SAM", (source, match)

        match = self.patterns['remark-start'].match(line)
        if match is not None:
            return "REMARK-START", (source, match)

        match = self.patterns['comment'].match(line)
        if match is not None:
            c = Comment(match.group('comment'), match.end('indent'))
            self.doc.add_block(c)

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



class Block(ABC):
    def __init__(self, name, indent, attributes=None, content=None, citations=None, namespace=None):

        # Test for a valid block name. Must be valid XML name.
        try:
            x = etree.Element(name)
        except ValueError:
            raise SAMParserError("Invalid block name: " + name)

        self.name = name
        self.namespace = namespace
        self.attributes = attributes
        self.content = content
        self.indent = indent
        self.parent = None
        self.children = []
        if citations:
            self.children.extend(citations)

    def add(self, b):
        """
        Add a block to the the current block or hand it off to the parent block.
        If the block is more indented than self, add it as a child.
        Otherwise call add on the parent block of self. This will recurse until
        the block finds it rightful home in the hierarchy.

        :param b: The block to add.

        """
        if b.indent <= self.indent:
            self.parent.add(b)
        else:
            if type(b) is OrderedListItem:
                ol = OrderedList(indent=b.indent)
                self.add(ol)
                ol.add(b)
            elif type(b) is UnorderedListItem:
                ul = UnorderedList(indent=b.indent)
                self.add(ul)
                ul.add(b)
            elif type(b) is LabeledListItem:
                ll = LabeledList(indent=b.indent)
                self.add(ll)
                ll.add(b)
            else:
                self._add_child(b)

    def _add_child(self, b):
        """
        Adds a child block to the current block.
        The main reason for this being separated from the add method is so that
        block types that override add can sill inherit add_child, ensuring that
        they do not forget to update the block's parent attribute.
        :param b: The block to add.
        :return: None
        """
        b.parent = self
        self.children.append(b)


    def ancestor_at_indent(self, indent):
        x = self.parent
        while x.indent >= indent:
            x = x.parent
        return x

    def __str__(self):
        return ''.join(self._output_block())

    def _output_block(self):
        yield " " * int(self.indent)
        yield "[%s:" % (self.name)
        if self.content:
            yield "['%s'" % (self.content)
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
            newlist = sorted(self.attributes, key=lambda x: x.type)

            for a in newlist:
                yield from a.serialize_xml()

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


class BlockInsert(Block):
    def __init__(self, indent, attributes=None, citations=None, namespace=None):
        super().__init__(name='insert', indent=indent, attributes=attributes, citations=citations, namespace=namespace)


class Codeblock(Block):
    def __init__(self, indent, attributes=None, citations=None, namespace=None):
        super().__init__(name='codeblock', indent=indent, attributes=attributes, citations=citations,namespace=namespace)


class Remark(Block):
    def __init__(self, indent, attributes=None, citations=None, namespace=None):
        super().__init__(name='remark', indent=indent, attributes=attributes, citations=citations, namespace=namespace)


class Embed(Block):
    def __init__(self, indent, attributes=None, citations=None, namespace=None):
        super().__init__(name='embed', indent=indent, attributes=attributes, citations=citations, namespace=namespace)


class Grid(Block):
    def __init__(self, indent, attributes=None, citations=None, namespace=None):
        super().__init__(name='grid', indent=indent, attributes=attributes,  citations=citations, namespace=namespace)


class Row(Block):
    def __init__(self, indent,  namespace=None):
        super().__init__(name='row', indent=indent, namespace=namespace)

    def add(self, b):
        """
        Override the Block add method to:
        * Accept Cell blocks as children
        * Raise error is asked to add anything else

        :param b: The block to add.

        """
        if b.indent < self.indent:
            self.parent.add(b)
        else:
            if type(b) is Cell:
                self._add_child(b)
            else:
                self.parent.add(b)

class Cell(Block):
    def __init__(self, indent, namespace=None):
        super().__init__(name='cell', indent=indent, namespace=namespace)


class Line(Block):
    def __init__(self, indent, attributes, content, citations=None, namespace=None):
        super().__init__(name='line', indent=indent, attributes=attributes, content=content, citations=citations, namespace=namespace)

    def add(self, b):
        if b.indent > self.indent:
            raise SAMParserError('A Line cannot have children. At \"{0}\".'.format(
                str(self)))
        else:
            self.parent.add(b)

class Fragment(Block):
    def __init__(self, indent, attributes=None, citations=None, namespace=None):
        super().__init__(name='fragment', indent=indent, attributes=attributes, citations=citations, namespace=namespace)


class Blockquote(Block):
    def __init__(self, indent, attributes=None, citations=None, namespace=None):
        super().__init__(name='blockquote', indent=indent, attributes=attributes, citations=citations, namespace=namespace)


class RecordSet(Block):
    def __init__(self, name, field_names, indent, attributes=None, citations=None, namespace=None):
        super().__init__(name=name, indent=indent, attributes=attributes,  citations=citations, namespace=namespace)
        self.field_names = field_names

    def add(self, b):
        if b.indent <= self.indent:
            self.parent.add(b)
        elif not type(b) is Record:
            raise SAMParserError('A RecordSet can only have Record children. At \"{0}\".'.format(
                    str(self)))
        elif len(b.field_values) != len(self.field_names):
            raise SAMParserError('Record length does not match record set header. At: \n{0}\n'.format(
                    str(self)))
        else:
            b.record = list(zip(self.field_names, b.field_values))
            b.parent = self
            self.children.append(b)

class Record(Block):
    def __init__(self, field_values, indent, content=None, namespace=None):
        self.name='record'
        self.field_values = field_values
        self.content = content
        self.namespace = namespace
        self.indent = indent
        self.record=None

    def _output_block(self):
        yield " " * int(self.indent)
        yield "[record:'%s'" % (self.content) + '\n'
        for x in self.record:
            yield " " * int(self.indent + 4) + x[0] + ' = ' + x[1] + "\n"
        yield "]"

    def serialize_xml(self):
        yield '<record'

        if self.namespace is not None:
            if type(self.parent) is Root or self.namespace != self.parent.namespace:
                yield ' xmlns="{0}"'.format(self.namespace)
        yield ">\n"

        for x in self.record:
            yield "<{0}>".format(x[0])
            yield from x[1].serialize_xml()
            yield "</{0}>\n".format(x[0])
        yield "</record>\n"


class List(Block):
    @abstractmethod
    def __init__(self,*args, **kwargs):
        super().__init__(*args, **kwargs)

    def add_sibling(self, b):
        if type(b) is Comment:
            self._add_child(b)
        if b.name == 'li':
            self._add_child(b)
        else:
            self.parent._add_child(b)


class UnorderedList(List):
    def __init__(self, indent, namespace=None):
        super().__init__(name='ul', indent=indent, content=None, namespace=namespace)

    def add(self, b):
        """
        Override the Block add method to:
        * Accept UnorderedListItems as children
        * Raise error is asked to add anything else

        :param b: The block to add.

        """
        if b.indent < self.indent:
            self.parent.add(b)
        else:
            if type(b) is UnorderedListItem:
                self._add_child(b)
            else:
                self.parent.add(b)

class OrderedList(List):
    def __init__(self, indent, namespace=None):
        super().__init__(name='ol', indent=indent, namespace=namespace)

    def add(self, b):
        """
        Override the Block add method to:
        * Accept OrderedListItems as children
        * Raise error is asked to add anything else

        :param b: The block to add.

        """
        if b.indent < self.indent:
            self.parent.add(b)
        else:
            if type(b) is OrderedListItem:
                self._add_child(b)
            elif type(b) is Comment:
                self._add_child(b)
            else:
                self.parent.add(b)

class ListItem(Block):
    @abstractmethod
    def __init__(self, name, indent, attributes=None, citations=None,  namespace=None):
        super().__init__(name=name, indent=indent, attributes=attributes, citations=citations, namespace=namespace)


class OrderedListItem(ListItem):
    def __init__(self, indent, attributes=None, citations=None,  namespace=None):
        super().__init__(name = "li", indent=indent, attributes=attributes, citations=citations,  namespace=namespace)


class UnorderedListItem(ListItem):
    def __init__(self, indent, attributes=None, citations=None,  namespace=None):
        super().__init__(name =  "li", indent = indent, attributes = attributes,  namespace = namespace)


class LabeledListItem(ListItem):
    def __init__(self, indent, label, attributes=None, citations=None,  namespace=None):
        super().__init__(name = "li", indent = indent, attributes = attributes, citations=citations,  namespace = namespace)
        self.label = label

    def serialize_xml(self):
        yield "<{0}>\n".format(self.name)

        if self.namespace is not None:
            if type(self.parent) is Root or self.namespace != self.parent.namespace:
                yield ' xmlns="{0}"'.format(self.namespace)

        if self.attributes:
            newlist = sorted(self.attributes, key=lambda x: x.type, reverse=True)
            for a in newlist:
                yield from a.serialize_xml()

        yield "<label>"
        yield from self.label.serialize_xml()
        yield "</label>\n"
        for x in self.children:
            if x is not None:
                yield from x.serialize_xml()
        yield "</{0}>\n".format(self.name)


class LabeledList(List):
    def __init__(self, indent, attributes=None, citations=None,  namespace=None):
        super().__init__(name='ll', indent=indent, attributes=attributes,  namespace=namespace)

    def add(self, b):
        """
        Override the Block add method to:
        * Accept LabeledListItems as children
        * Raise error is asked to add anything else

        :param b: The block to add.

        """
        if b.indent < self.indent:
            self.parent.add(b)
        else:
            if type(b) is LabeledListItem:
                self._add_child(b)
            else:
                self.parent.add(b)

class Paragraph(Block):
    def __init__(self, indent,  namespace=None):
        super().__init__(name='p', indent=indent, namespace=namespace)

    def _add_child(self, b):
        if type(b) is Flow:
            b.parent = self
            self.children.append(b)
        elif self.parent.name == 'li' and b.name in ['ol', 'ul', '#comment']:
            b.parent = self.parent
            self.parent.children.append(b)
        else:
            raise SAMParserError(
                'A paragraph cannot have block children. Following \"{0}\".'.format(
                    str(self)))


class Comment(Block):
    def __init__(self, content, indent):
        self.content=content
        self.indent=indent
        self.name='#comment'
        self.namespace=None

    def _add_child(self, b):
        if self.parent.name == 'li' and b.name in ['ol', 'ul', '#comment']:
            b.parent = self.parent
            self.parent.children.append(b)
        else:
            raise SAMParserError(
                'A comment cannot have block children. Following \"{0}\".'.format(
                    str(self)))

    def __str__(self):
        return u"[#{0}]".format(self.content)

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

    def _add_child(self, b):
        # This is a hack to catch the creation of a second root-level block.
        # It is not good because people can add to the children list without
        # calling this function. Not sure what the options are. Could detect
        # the error at the XML output stage, I suppose, but would rather
        # catch it earlier and give feedback.
        if type(b) is not Comment and any( type(x) is not Comment for x in self.children):
            raise SAMParserError("A SAM document can only have one root. Found: "+ str(b))
        b.parent = self
        self.children.append(b)


class UnparsedTextBlock:
    """
    A class for creating text block objects for accumulating blocks of text
    that span multiple lines in the SAM source document, such as paragraphs 
    and codeblocks. This is simply a container that we can add lines to one
    at a time until we have a complete block of text that we can hand off to
    the flow parser (in the case of a paragraph) or turn into a Pre object 
    in the case of a codeblock. 
    """
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
                super().append(thing)
        elif type(thing) is Citation:
            try:
                if type(self[-1]) is Phrase:
                    self[-1].append(thing)
                else:
                    super().append(thing)
            except IndexError:
                super().append(thing)

        elif not thing == '':
            super().append(thing)

    def find_last_annotation(self, text):
        for i in reversed(self):

            if type(i) is Phrase:
                c = i.child
                while c:
                    if type(c) is Annotation:
                        if i.text == text:
                            return c
                    c=c.child
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
        self.content = text
        self.indent = indent
        self.namespace = None
        self.name = "<?xml?>"
        self.children = []

    def serialize_xml(self):
        yield self.content


class DocStructure:
    """
    Class to define a document structure object. The SAM source document is parsed 
    to create a document structure object. The document structured object can then
    be queried directly by programs or can output an XML representation of the 
    SAM document. 
    
    The document structure object is a tree of objects starting with a Root object. 
    Each part of the SAM concrete syntax, such as Grids, RecordSets, and Lines has
    its own object type. Names blocks are represented by a generic Block object. 
    """
    def __init__(self):
        self.root = Root()
        self.current_block = self.root
        self.default_namespace = None
        self.ids = []


    def _cur_blk(self):
        """
        Calculates the current block by recursing the doc structure to find the last node.
        
        Should not be needed as the self.current_block should be updated whenever a block is 
        added. 
        
        :return: The current block. That is, the last node of the doc structure. 
        """
        cur = self.root
        try:
            while True:
                cur = cur.children[-1]
        except(IndexError):
            return cur
        except(AttributeError):
            return cur

    def context(self, context_block=None):
        """
        Calculate the context of a given block in the document hierarchy. 
        :param context_block: The block to start from as an instance of a Block object. 
        If not given, the current block is used.
        :return: Returns a list containing the names of the specified block and its ancestors 
        back to the root, with the name of the given node first.
        """
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
        """
        Determines if the current context matches a context query. The context query is a list
        of block names consisting of the current block and as many of its parents as are of 
        interest. For example::
        
            self.doc.in_context(['p', 'li'])
            
         would determine if the current block is a 'p' inside an 'li'.   
        :param context_query: The context to query as a list of block names from the leaf node 
        backwards through as many parent blocks as desired. 
        :return: True is the context_query matches the current context; False otherwise.
        """
        c = self.context()
        for i, cq in enumerate(context_query):
            if c[i] != cq:
                return False
        return True

    def ancestor_or_self(self,ancestor_name, block=None):
        """
        Returns a block that is the reference block or it ancestor based on its name.
        
        For SAM's concrete types is it better to use ancestor_or_self_type as
        the names of concrete types could be changed in the schema. 
        
        :param ancestor_name: The name of the block to return.
        :param block: The reference block. If not specified, the current block is used.
        :return: The block requested, nor None if no block matches.
        """
        if block is None:
            block = self.current_block
        try:
            while True:
                if block.name == ancestor_name:
                    return block
                block = block.parent
        except(AttributeError):
            return None

    def ancestor_or_self_type(self,ancestor_type, block=None):
        """
        Returns a block that is the reference block or it ancestor based on its type.

        For named blocks is it better to use ancestor_or_self as
        all named blocks are of type Block. 

        :param ancestor_name: The type of the block to return.
        :param block: The reference block. If not specified, the current block is used.
        :return: The block requested, nor None if no block matches.
        """
        if block is None:
            block = self.current_block
        try:
            while True:
                if type(block) is ancestor_type:
                    return block
                block = block.parent
        except(AttributeError):
            return None


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

        # ID check
        try:

            if 'id' in block.attributes:
                if block.attributes['id'] in self.ids:
                    raise SAMParserError("Duplicate ID found: " + block.attributes['id'])
                self.ids.append(block.attributes['id'])
        except (TypeError, AttributeError):
            pass

        # Check IDs from included files
        try:
            overlapping_ids = set(block.ids) & set(self.ids)
            if overlapping_ids:
                raise SAMParserError("Duplicate ID found: " + ', '.join(overlapping_ids))
            self.ids.extend(block.ids)
        except (TypeError, AttributeError):
            pass

        if block.namespace is None and self.default_namespace is not None:
            block.namespace = self.default_namespace

        self.current_block.add(block)
        self.current_block = block

    def add_flow(self, flow):
        """
        Add a flow object as a child of the current object.
        
        The method checks the IDs declared in the flow against the list of 
        declared IDs for the document and raises a SAMParserError "Duplicate ID found" 
        if there is a duplicate. 
        :param flow: The Flow object to add.
        :return: None.
        """

        # Check for duplicate IDs in the flow
        # Add any ids found to list of ids
        ids=[f._id for f in flow if type(f) is Phrase and f._id is not None]
        for id in ids:
            if id in self.ids:
                raise SAMParserError("Duplicate ID found: " + ids[0])
            self.ids.append(id)

        self.current_block._add_child(flow)


    def find_last_annotation(self, text, node=None):
        """
        Finds the last annotation in the current document with the specified text. 
        In this case, "last" means the most recent instance of that annotation text 
        in document order. In other words, the method searches backwards through the 
        document and stops at the first occurrence of an annotation with that text that
        it encounters. 
        
        :param text: The annotation text to search for. 
        :param node: The node in the document tree to start the search from. If not specified, 
        the seach defaults to self.root, meaning the entire document is searched.
        :return: The last matching annotation object, or None. 
        """
        if node is None:
            node = self.root
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
        """
        Creates an serialization of the document structure in the specified format. At present, 
        the only serialization format supported is XML.
        :param serialize_format: Must be "XML"
        :return: A generator that generates the serialized output. 
        """
        if serialize_format.upper() == 'XML':
            yield from self.root.serialize_xml()
        else:
            raise SAMParserError("Unknown serialization protocol {0}".format(serialize_format))


class Include(Block):
    def __init__(self, doc, href, indent):
        self.children=doc.root.children
        self.indent = indent
        self.namespace = None
        self.ids = doc.ids
        self.name = "<<<"
        self.content = href

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
re_single_quote_close = '(?<=[\w\.\,\"\)}\?-])\'((?=[\.\s"},\?!:;\[])|$)'
re_single_quote_open = '(^|(?<=[\s\"{]))\'(?=[\w"{-])'
re_double_quote_close = '(?<=[\w\.\,\'\)\}\?-])\"((?=[\.\s\'\)},\?!:;\[-])|$)'
re_double_quote_open = '(^|(?<=[\s\'{\(]))"(?=[\w\'{-])'
re_apostrophe = "(?<=[\w`\*_\}\)])'(?=\w)"
re_en_dash = "(?<=[\w\*_`\"\'\)\}]\s)--(?=\s[\w\*_`\"\'\{\(])"
re_em_dash = "(?<=[\w\*_`\"\'\)\}])---(?=[\w\*_`\"\'\{\(])"

smart_quote_subs = {re_double_quote_close:'”',
                    re_double_quote_open: '“',
                    re_single_quote_close:'’',
                    re_single_quote_open: '‘',
                    re_apostrophe: '’',
                    re_en_dash: '–',
                    re_em_dash: '—'}


class FlowParser:
    def __init__(self):
        # These attributes are set by the parse method
        self.doc = None
        self.flow_source = None
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
        self.stateMachine.add_state("DASH-START", self._dash_start)
        self.stateMachine.add_state("INLINE-INSERT", self._inline_insert)
        self.stateMachine.add_state("CHARACTER-ENTITY", self._character_entity)
        self.stateMachine.set_start("PARA")
        self.patterns = {
            'escape': re.compile(r'\\', re.U),
            'phrase': re.compile(r'(?<!\\)\{(?P<text>.*?)(?<!\\)\}'),
            'annotation': re.compile(
                r'''
                (
                    \(                                       #open paren
                        \s*                                  #any spaces
                        (?P<type>\S*?)                       #any non-space characters = annotation type
                        \s*                                  #any spaces
                        (                                    #specifically attribute
                            (?P<quote>["\'])                 #open quote
                            (?P<specifically>.*?)            #any text = specifically
                            (?<!\\)(?P=quote)                #close matching quote if not preceded by backslash
                        )??                                  #end specifically attribute
                        \s*                                  #any spaces
                        (\((?P<namespace>\w+)\))?            #any text in parens = namespace
                    (?<!\\)\)                                #closing paren if not preceded by backslash
                )
                ''',
                re.VERBOSE | re.U),
            'bold': re.compile(r'\*(?P<text>((?<=\\)\*|[^\*])*)(?<!\\)\*', re.U),
            'italic': re.compile(r'_(?P<text>((?<=\\)_|[^_])*)(?<!\\)_', re.U),
            'code': re.compile(r'`(?P<text>(``|[^`])*)`', re.U),
            'apostrophe': re.compile(re_apostrophe, re.U),
            'single_quote_close': re.compile(re_single_quote_close, re.U),
            'single_quote_open': re.compile(re_single_quote_open, re.U),
            'double_quote_close': re.compile(re_double_quote_close, re.U),
            'double_quote_open': re.compile(re_double_quote_open, re.U),
            'inline-insert': re.compile(r'>(?P<insert>\((.*?(?<!\\))\))' + re_attributes, re.U),
            'en-dash': re.compile(re_en_dash, re.U),
            'em-dash': re.compile(re_em_dash, re.U),
            'citation': re.compile(
                r'((\[\s*\*(?P<id>\S+?)(\s+(?P<id_extra>.+?))?\])|(\[\s*\#(?P<name>\S+?)(\s+(?P<name_extra>.+?))?\])|(\[\s*(?P<citation>.*?)\]))',
                re.U)
        }

    def parse(self, flow_source, doc, strip=True):
        if flow_source is None:
            return None
        self.doc = doc
        self.flow_source = FlowSource(flow_source, strip)
        self.current_string = ''
        self.flow = Flow()
        self.stateMachine.run(self.flow_source)
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
        elif char == "-":
            return "DASH-START", para
        else:
            self.current_string += char
            return "PARA", para

    def _phrase_start(self, para):
        match = self.patterns['phrase'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            text = unescape(match.group("text"))
            if self.smart_quotes:
                text = multi_replace(text, smart_quote_subs)
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
                self.flow.append(Attribute('language', unescape(annotation_type[1:])))
            elif annotation_type[0] == '*':
                self.flow.append(Attribute('id', unescape(annotation_type[1:])))
            elif annotation_type[0] == '#':
                self.flow.append(Attribute('name', unescape(annotation_type[1:])))
            elif annotation_type[0] == '?':
                self.flow.append(Attribute('condition', unescape(annotation_type[1:])))
            else:
                self.flow.append(Annotation(annotation_type, unescape(specifically), namespace))
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
            self.flow.append(Phrase(unescape(match.group("text"))))
            self.flow.append(Annotation('bold'))
            para.advance(len(match.group(0)))
        else:
            self.current_string += '*'
            return "PARA", para

        if self.patterns['annotation'].match(para.rest_of_para):
            return "ANNOTATION-START", para
        elif self.patterns['citation'].match(para.rest_of_para):
            return "CITATION-START", para
        else:
            para.retreat(1)
            return "PARA", para

    def _italic_start(self, para):
        match = self.patterns['italic'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            self.flow.append(Phrase(unescape(match.group("text"))))
            self.flow.append(Annotation('italic'))
            para.advance(len(match.group(0)))
        else:
            self.current_string += '_'
            return "PARA", para

        if self.patterns['annotation'].match(para.rest_of_para):
            return "ANNOTATION-START", para
        elif self.patterns['citation'].match(para.rest_of_para):
            return "CITATION-START", para
        else:
            para.retreat(1)
            return "PARA", para

    def _code_start(self, para):
        match = self.patterns['code'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            self.flow.append(Phrase((match.group("text")).replace("``", "`")))
            self.flow.append(Annotation('code'))
            para.advance(len(match.group(0)))
        else:
            self.current_string += '`'
            return "PARA", para

        if self.patterns['annotation'].match(para.rest_of_para):
            return "ANNOTATION-START", para
        elif self.patterns['citation'].match(para.rest_of_para):
            return "CITATION-START", para
        else:
            para.retreat(1)
            return "PARA", para

    def _dash_start(self, para):
        if self.smart_quotes:
            if self.patterns['en-dash'].search(para.para, para.currentCharNumber,
                                                          para.currentCharNumber + 5):
                self.current_string += '–'
                self.flow_source.advance(1)

            elif self.patterns['em-dash'].search(para.para, para.currentCharNumber,
                                                           para.currentCharNumber + 5):
                self.current_string += '—'
                self.flow_source.advance(2)
            else:
                self.current_string += '-'
        else:
            self.current_string += '-'
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
            attributes, citations = parse_attributes(match.group("attributes"))
            attributes.extend(parse_insert(match.group("insert")) )

            self.flow.append(InlineInsert(attributes, citations))
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
        if re_escaped_chars.match(char):
            self.current_string += char
        else:
            self.current_string += '\\' + char
        return "PARA", para

    def _character_entity(self, para):
        match = re_character_entity.match(para.rest_of_para)
        if match:
            self.current_string += re_character_entity.sub(replace_charref, match.group(0))
            para.advance(len(match.group(0)) - 1)
        else:
            self.current_string += '&'
        return "PARA", para


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


class FlowSource:
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
        yield '<citation'
        if self.citation_extra is not None:
            if self.citation_extra:
                yield ' extra="{0}"'.format(escape_for_xml_attribute(self.citation_extra.strip()))
        yield ' type = "{0}" value = "{1}"'.format(self.citation_type, escape_for_xml_attribute(self.citation_value))
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
    def __init__(self, attributes, citations):
        self.attributes = attributes
        self.citations = citations

    def __str__(self):
        return "[#insert:'%s' '%s']" % self.attributes, self.citations

    def serialize_xml(self):
        newlist = sorted(self.attributes, key=lambda x: x.type)
        yield '<inline-insert'
        for a in newlist:
            yield from a.serialize_xml()
        if self.citations:
            yield '>'
            for c in self.citations:
                yield from c.serialize_xml()
            yield '</inline-insert>'
        else:
            yield '/>'


class SAMParserError(Exception):
    """
    Raised if the SAM parser encounters an error.
    """

def parse_attributes(attributes_string, flagged="?#*!", unflagged=None):
    attributes = []
    citations =[]
    attributes_list=[]
    citations_list=[]

    re_att = re.compile(r"(\(.*?(?<!\\)\))")
    re_cit = re.compile(r"(\[.*?(?<!\\)\])")

    re_all = re.compile(r'(\((?P<att>.*?(?<!\\))\))|(\[((?P<cit>.*?(?<!\\))\])|(?P<bad>.))')

    for x in re_all.finditer(attributes_string.rstrip()):
        if x.group('att') is not None:
            attributes_list.append(x.group('att').strip())
        elif x.group("cit") is not None:
            citations_list.append(x.group("cit").strip())
        else:
            raise SAMParserError("Unrecognized character '" + x.group('bad') + "' found in attributes list at: " + attributes_string)

    unflagged_attributes = [x for x in attributes_list if not (x[0] in '?#*!')]
    if unflagged_attributes:
        if unflagged is None:
            raise SAMParserError("Unexpected attribute(s): {0}".format(', '.join(unflagged_attributes)))
        elif len(unflagged_attributes) > 1:
            raise SAMParserError("More than one " + unflagged + " attribute specified: {0}".format(', '.join(unflagged_attributes)))
        else:
            attributes.append(Attribute(unescape(unflagged), unescape(unflagged_attributes[0])))
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
        attributes.append(Attribute("id", unescape(ids[0])))
    if names:
        attributes.append(Attribute("name", unescape(names[0])))
    if language:
        attributes.append(Attribute("xml:lang", unescape(language[0])))
    if conditions:
        attributes.append(Attribute("conditions", ",".join([unescape(x) for x in conditions])))

    re_citbody = r'(\s*\*(?P<id>\S+)(?P<id_extra>.*))|(\s*\#(?P<name>\S+)(?P<name_extra>.*))|(\s*(?P<citation>.*))'

    for c in citations_list:
        match = re.compile(re_citbody).match(c)
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
            extra=None
        else:
            citation_type = None
        if citation_type:
            citations.append(Citation(citation_type, citation_value, extra))
    return attributes, citations


def parse_insert(annotation_string):
    result = []

    insert_annotation = re.match(r'(\(.*?(?<!\\)\))', annotation_string)
    attributes_list = insert_annotation.group(0)[1:-1].partition(' ')
    insert_type = attributes_list[0]
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
    elif insert_type[0] == '%':
        insert_item = insert_type[1:]
        insert_type = 'key'
    else:
        insert_item = attributes_list[2].strip()
    result.append(Attribute('type', unescape(insert_type)))
    # strip unnecessary quotes from insert item
    insert_item = re.sub(r'^(["\'])|(["\'])$', '', insert_item)
    if insert_item == '':
        raise SAMParserError ("Insert item not specified in: " + annotation_string)
    result.append(Attribute('item', unescape(insert_item)))
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


re_escaped_chars = re.compile('[:\\\(\)\{\}\[\]_\*,\.\*`"&\<\>' + "']", re.U)
re_character_entity = re.compile(r'&(\#[0-9]+|#[xX][0-9a-fA-F]+|[\w]+);', re.U)

def unescape(string):
    result = ''
    try:
        e = enumerate(string)
        for pos, char in e:
            try:
                if char == '\\' and re_escaped_chars.match(string[pos + 1]):
                    result += string[pos + 1]
                    next(e, None)
                elif char == '&':
                    match = re_character_entity.match(string[pos:])
                    if match:
                        result += re_character_entity.sub(replace_charref, match.group(0))
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

def replace_charref(match):
    try:
        charref = match.group(0)
    except AttributeError:
        charref = match
    character = html.unescape(charref)
    if character == charref:  # Escape not recognized
        raise SAMParserError("Unrecognized character entity found: " + charref)
    return character


flow_parser = FlowParser()

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
        flow_parser.smart_quotes = True

    if (args.intermediatefile or args.intermediatedir) and not args.xslt:
        raise SAMParserError("Do not specify an intermediate file or directory if an XSLT file is not specified.")

    if args.xslt and not (args.intermediatefile or args.intermediatedir):
        raise SAMParserError("An intermediate file or directory must be specified if an XSLT file is specified.")

    if args.infile == args.outfile:
        raise SAMParserError('Input and output files cannot have the same name.')

    error_count = 0
    for inputfile in glob.glob(args.infile):
        try:
            with open(inputfile, "r", encoding="utf-8-sig") as inf:

                SAM_parser_info("Parsing " + os.path.abspath(inf.name))
                samParser.parse(inf)


                xml_string = "".join(samParser.serialize('xml')).encode('utf-8')

                if args.intermediatedir:
                    intermediatefile=os.path.join(args.intermediatedir, os.path.splitext(os.path.basename(inputfile))[0] + args.intermediateextension)
                else:
                    intermediatefile=args.intermediatefile

                if intermediatefile:
                    with open(intermediatefile, "wb") as intermediate:
                        intermediate.write(xml_string)

                if args.xslt:
                    try:
                        transform = etree.XSLT(etree.parse(args.xslt))
                    except FileNotFoundError as e:
                        raise SAMParserError(e.strerror + ' ' + e.filename)

                    xml_input = etree.parse(open(intermediatefile, 'r', encoding="utf-8-sig"))
                    try:
                        transformed = transform(xml_input)
                    except etree.XSLTApplyError as e:
                        raise SAMParserError("XSLT processor reported error: " + str(e))

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


                if args.xsd:
                    try:
                        xmlschema = etree.XMLSchema(file=args.xsd)
                    except etree.XMLSchemaParseError as e:
                        print(e, file=sys.stderr)
                        exit(1)
                    SAM_parser_info("Validating output using " + args.xsd)
                    xml_doc = etree.fromstring(xml_string)
                    try:
                        xmlschema.assertValid(xml_doc)
                    except etree.DocumentInvalid as e:
                        print('STRUCTURE ERROR: ' + str(e), file=sys.stderr)
                        error_count += 1
                    else:
                        SAM_parser_info("Validation successful.")


        except FileNotFoundError:
            raise SAMParserError("No input file specified.")

        except SAMParserError as e:
            sys.stderr.write('SAM parser ERROR: ' + str(e) + "\n")
            error_count += 1
            continue

    print('Process completed with %d errors.' % error_count, file=sys.stderr)
    if error_count > 0:
        sys.exit(1)