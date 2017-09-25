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


block_patterns = {
            'comment': re.compile(re_indent + re_comment, re.U),
            'remark-start': re.compile(
                re_indent + r'(?P<flag>!!!)(' + re_attributes + ')?\s*(?P<unexpected>.*)',
                re.U),
            'declaration': re.compile(re_indent + '!' + re_name + r'(?<!\\):' + re_content + r'?', re.U),
            'block-start': re.compile(re_indent + re_name + r'(?<!\\):' + re_attributes + '\s' + re_content + r'?', re.U),
            'codeblock-start': re.compile(
                re_indent + r'(?P<flag>```)(' + re_attributes + ')?\s*(?P<unexpected>.*)',
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
            'string-def': re.compile(re_indent + r'\$' + re_name + '\s*=\s*' + re_content, re.U)
        }

# Flow regex component expressions
re_single_quote_close = '(?<=[\w\.\,\"\)}\?-])\'((?=[\.\s"},\?!:;\[])|$)'
re_single_quote_open = '(^|(?<=[\s\"{]))\'(?=[\w"{-])'
re_double_quote_close = '(?<=[\w\.\,\'\)\}\?-])\"((?=[\.\s\'\)},\?!:;\[-])|$)'
re_double_quote_open = '(^|(?<=[\s\'{\(]))"(?=[\w\'{-])'
re_apostrophe = "(?<=[\w`\*_\}\)])'(?=\w)"
re_en_dash = "(?<=[\w\*_`\"\'\.\)\}]\s)--(?=\s[\w\*_`\"\'\{\(])"
re_em_dash = "(?<=[\w\*_`\"\'\.\)\}])---(?=[\w\*_`\"\'\{\(])"


flow_patterns = {
            'escape': re.compile(r'\\', re.U),
            'phrase': re.compile(r'(?<!\\)\{(?P<text>.*?)(?<!\\)\}'),
            'annotation': re.compile(
                r'''
                (
                    (?P<plus>\+?)                            #conditional flag
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
                r'((\[\s*\*(?P<id>\S+?)(\s+(?P<id_extra>.+?))?\])|(\[\s*\%(?P<key>\S+?)(\s+(?P<key_extra>.+?))?\])|(\[\s*\#(?P<name>\S+?)(\s+(?P<name_extra>.+?))?\])|(\[\s*(?P<citation>.*?)\]))',
                re.U)
        }

smart_quote_subs = {re_double_quote_close:'”',
                    re_double_quote_open: '“',
                    re_single_quote_close:'’',
                    re_single_quote_open: '‘',
                    re_apostrophe: '’',
                    re_en_dash: '–',
                    re_em_dash: '—'}

included_files = []

class SamParser:
    def __init__(self):

        self.stateMachine = StateMachine()
        self.stateMachine.add_state("SAM", self._sam)
        self.stateMachine.add_state("BLOCK", self._block)
        self.stateMachine.add_state("CODEBLOCK-START", self._codeblock_start)
        self.stateMachine.add_state("CODEBLOCK", self._codeblock)
        self.stateMachine.add_state("REMARK-START", self._remark_start)
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
        self.stateMachine.add_state("END", None, end_state=1)
        self.stateMachine.set_start("SAM")
        self.current_text_block = None
        self.doc = None
        self.source = None
        self.sourceurl = None
        self.smart_quotes = False


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
        except SAMParserStructureError as err:
            raise SAMParserError("Structure error: {0} at line {1}:\n\n {2}\n".format(' '.join(err.args), self.source.current_line_number,  self.source.current_line))
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
            raise SAMParserStructureError('Unexpected characters in codeblock header. Found "{0}"'.format(match.group("unexpected")))
        indent = match.end("indent")

        attributes, citations = parse_attributes(match.group("attributes"), flagged="*#?!=", unflagged="language")

        language=attributes.pop(0) if attributes else None
        if language and language.type == 'encoding':
            b = Embedblock(indent, language.value, attributes, citations)
        elif language:
            b = Codeblock(indent, language.value, attributes, citations)
        else:
            b = Codeblock(indent, None, attributes, citations)
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
        if block_patterns['blank-line'].match(line):
            self.current_text_block.append(line)
            return "CODEBLOCK", context
        if indent <= self.doc.ancestor_or_self_type([Codeblock, Embedblock]).indent:
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

        if block_patterns['blank-line'].match(line):
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
            if block_patterns['list-item'].match(line) or block_patterns['num-list-item'].match(line) or block_patterns[
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
        type, item = parse_insert(match.group("insert"))
        b = BlockInsert(indent, type, item, attributes, citations)
        self.doc.add_block(b)
        return "SAM", context

    def _include(self, context):
        source, match = context
        indent = match.end("indent")
        href=match.group("attributes")[1:-1]

        if href.strip() == "":
            SAM_parser_warning("No HREF specified for include.")
            return "SAM", context
        elif bool(urllib.parse.urlparse(href).netloc):  # An absolute URL
            fullhref = href
        elif os.path.isabs(href):  # An absolute file path
            fullhref = pathlib.Path(href).as_uri()
        elif self.sourceurl:
            fullhref = urllib.parse.urljoin(self.sourceurl, href)
        else:
            SAM_parser_warning("Unable to resolve relative URL of include as source of parsed document not known.")
            return "SAM", context

        if fullhref in included_files:
            raise SAMParserError("Duplicate file inclusion detected with file: " + fullhref)
        else:
            included_files.append(fullhref)

        reader = codecs.getreader("utf-8")
        SAM_parser_info("Parsing include " + href)
        try:
            includeparser = SamParser()
            with urllib.request.urlopen(fullhref) as response:
                includeparser.parse(reader(response))
            include = Include(includeparser.doc, href, fullhref, indent)
            self.doc.add_block(include)
            SAM_parser_info("Finished parsing include " + href)
        except FileNotFoundError as e:
            SAM_parser_warning(str(e))
        except urllib.error.URLError as e:
            SAM_parser_warning(str(e))

        included_files.pop()



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
        if block_patterns['blank-line'].match(line):
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
        if block_patterns['blank-line'].match(line):
            return "GRID", context
        elif indent <= self.doc.ancestor_or_self_type(Grid).indent:
            source.return_line()
            return "SAM", context
        else:
            cell_values = [x.strip() for x in re.split(r'(?<!\\)\|', line)]
            if self.doc.current_block.name == 'row':
                if len(self.doc.current_block.children) != len(cell_values):
                    raise SAMParserStructureError('Uneven number of cells in grid row')
            b = Row(indent)
            self.doc.add_block(b)

            for content in cell_values:
                b = Cell(indent)
                self.doc.add_block(b)

                self.doc.add_flow(flow_parser.parse(content, self.doc))
            # Test for consistency with previous rows?

            return "GRID", context

    def _sam(self, context):
        source, match = context
        try:
            line = source.next_line
        except EOFError:
            return "END", context

        match = block_patterns['declaration'].match(line)
        if match is not None:
            name = match.group('name').strip()
            content = match.group('content').strip()
            if self.doc.root.children:
                raise SAMParserStructureError("Declarations must come before all other content.")
            if name == 'namespace':
                self.doc.default_namespace = content
            if name == 'annotation-lookup':
                self.doc.annotation_lookup = content
            else:
                raise SAMParserStructureError("Unknown declaration.")

            return "SAM", (source, match)

        match = block_patterns['remark-start'].match(line)
        if match is not None:
            return "REMARK-START", (source, match)

        match = block_patterns['comment'].match(line)
        if match is not None:
            c = Comment(match.group('comment'), match.end('indent'))
            self.doc.add_block(c)

            return "SAM", (source, match)

        match = block_patterns['record-start'].match(line)
        if match is not None:
            return "RECORD-START", (source, match)

        match = block_patterns['blank-line'].match(line)
        if match is not None:
            return "SAM", (source, match)

        match = block_patterns['codeblock-start'].match(line)
        if match is not None:
            return "CODEBLOCK-START", (source, match)

        match = block_patterns['blockquote-start'].match(line)
        if match is not None:
            return "BLOCKQUOTE-START", (source, match)

        match = block_patterns['fragment-start'].match(line)
        if match is not None:
            return "FRAGMENT-START", (source, match)

        match = block_patterns['grid-start'].match(line)
        if match is not None:
            return "GRID-START", (source, match)

        match = block_patterns['list-item'].match(line)
        if match is not None:
            return "LIST-ITEM", (source, match)

        match = block_patterns['num-list-item'].match(line)
        if match is not None:
            return "NUM-LIST-ITEM", (source, match)

        match = block_patterns['labeled-list-item'].match(line)
        if match is not None:
            return "LABELED-LIST-ITEM", (source, match)

        match = block_patterns['block-insert'].match(line)
        if match is not None:
            return "BLOCK-INSERT", (source, match)

        match = block_patterns['include'].match(line)
        if match is not None:
            return "INCLUDE", (source, match)

        match = block_patterns['string-def'].match(line)
        if match is not None:
            return "STRING-DEF", (source, match)

        match = block_patterns['line-start'].match(line)
        if match is not None:
            return "LINE-START", (source, match)

        match = block_patterns['block-start'].match(line)
        if match is not None:
            return "BLOCK", (source, match)

        match = block_patterns['paragraph-start'].match(line)
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
            raise SAMParserStructureError('Invalid block name "{0}"'.format(name))

        self.name = name
        self.namespace = namespace
        self.attributes = attributes
        self.content = content
        self.indent = indent
        self.parent = None
        self.children = []
        self.citations = citations

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
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield "%s:" % (self.name)
        if self.attributes:
            for a in self.attributes:
                yield from a.regurgitate()

        for y in [x for x in self.citations]:
            yield from y.regurgitate()

        if self.content:
            yield " %s" % (self.content)
        yield "\n"
        for z in [x for x in self.children]:
            yield from z.regurgitate()


    def serialize_xml(self):
        yield '<{0}'.format(self.name)

        if self.namespace is not None:
            if type(self.parent) is Root or self.namespace != self.parent.namespace:
                yield ' xmlns="{0}"'.format(self.namespace)

        if self.attributes:
            if any([x.value for x in self.attributes if x.type == 'condition']):
                conditions = Attribute('conditions', ','.join([x.value for x in self.attributes if x.type == 'condition']))
                attrs = [x for x in self.attributes if x.type != 'condition']
                attrs.append(conditions)
                for att in sorted(attrs, key=lambda x: x.type):
                    yield from att.serialize_xml()
            else:
                for att in sorted(self.attributes, key=lambda x: x.type):
                    yield from att.serialize_xml()

        if self.children or self.citations:
            yield ">"

            if self.citations:
                for x in self.citations:
                    yield '\n'
                    yield from x.serialize_xml()

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
    def __init__(self, indent, type, item, attributes=None, citations=None, namespace=None):
        super().__init__(name='insert', indent=indent, attributes=attributes, citations=citations, namespace=namespace)
        self.type =type
        self.item = item

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        type_symbol = Attribute.attribute_symbols.get(self.type)
        if type_symbol:
            yield '>>>({0}{1})'.format(type_symbol, self.item)
        else:
            yield '>>>({0} {1})'.format(self.type, self.item)
        for x in self.attributes:
            yield from x.regurgitate()
        yield '\n\n'

    def serialize_xml(self):

        attrs=[Attribute('type', self.type), Attribute('item', self.item)]

        yield '<insert'
        if self.attributes:
            if any([x.value for x in self.attributes if x.type == 'condition']):
                conditions = Attribute('conditions', ','.join([x.value for x in self.attributes if x.type == 'condition']))
                attrs.append(conditions)
                attrs.extend([x for x in self.attributes if x.type != 'condition'])

        for att in sorted(attrs, key=lambda x: x.type):
            yield from att.serialize_xml()

        if self.citations or self.children:
            yield '>\n'
            for cit in self.citations:
                yield from cit.serialize_xml()

            for c in self.children:
                yield from c.serialize_xml()
            yield '</insert>'
        else:
            yield '/>\n'


class Codeblock(Block):
    def __init__(self, indent, language=None, attributes=None, citations=None, namespace=None):
        super().__init__(name='codeblock', indent=indent, attributes=attributes, citations=citations,namespace=namespace)
        self.language = language

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield '```'
        if self.language:
            yield "({0})".format(self.language)
        for x in self.attributes:
            yield from x.regurgitate()
        for x in self.citations:
            yield from x.regurgitate()
        yield '\n'
        for x in self.children:
            yield from x.regurgitate()
        yield '\n'

    def serialize_xml(self):
        attrs = []
        yield '<codeblock'

        if self.namespace is not None:
            if type(self.parent) is Root or self.namespace != self.parent.namespace:
                yield ' xmlns="{0}"'.format(self.namespace)
        if self.language:
            attrs.append(Attribute('language', self.language))
        if self.attributes:
            attrs.extend(self.attributes)
        if attrs:
            if any([x.value for x in attrs if x.type == 'condition']):
                conditions = Attribute('conditions',
                                       ','.join([x.value for x in attrs if x.type == 'condition']))
                attrs = [x for x in attrs if x.type != 'condition']
                attrs.append(conditions)
                for att in sorted(attrs, key=lambda x: x.type):
                    yield from att.serialize_xml()
            else:
                for att in sorted(attrs, key=lambda x: x.type):
                    yield from att.serialize_xml()

        if self.citations or self.children:
            yield ">\n"
        if self.citations:
            for x in self.citations:
                yield from x.serialize_xml()
                yield '\n'
        if self.children:
            for x in self.children:
                if x is not None:
                    yield from x.serialize_xml()
            yield "</codeblock>\n"
        else:
            yield '/>'

class Embedblock(Codeblock):

    def regurgitate(self):
        yield " " * int(self.indent)
        yield '```'
        if self.language:
            yield "(={0})".format(self.language)
        for x in self.attributes:
            yield from x.regurgitate()
        for x in self.citations:
            yield from x.regurgitate()
        yield '\n'
        for x in self.children:
            yield from x.regurgitate()
        yield '\n'

    def serialize_xml(self):
        attrs = []
        yield '<embedblock'

        if self.namespace is not None:
            if type(self.parent) is Root or self.namespace != self.parent.namespace:
                yield ' xmlns="{0}"'.format(self.namespace)
        if self.language:
            attrs.append(Attribute('encoding', self.language))
        if self.attributes:
            attrs.extend(self.attributes)
        if attrs:
            if any([x.value for x in attrs if x.type == 'condition']):
                conditions = Attribute('conditions',
                                       ','.join([x.value for x in attrs if x.type == 'condition']))
                attrs = [x for x in attrs if x.type != 'condition']
                attrs.append(conditions)
                for att in sorted(attrs, key=lambda x: x.type):
                    yield from att.serialize_xml()
            else:
                for att in sorted(attrs, key=lambda x: x.type):
                    yield from att.serialize_xml()

        if self.children:
            yield ">"

            if type(self.children[0]) is not Flow:
                yield "\n"

            for x in self.children:
                if x is not None:
                    yield from x.serialize_xml()
            yield "</embedblock>\n"
        else:
            yield '/>'

class Remark(Block):
    def __init__(self, indent, attributes=None, citations=None, namespace=None):
        super().__init__(name='remark', indent=indent, attributes=attributes, citations=citations, namespace=namespace)

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield '!!!({0})'.format(next(x.value for x in self.attributes if x.type == 'attribution'))
        for x in self.attributes:
            if x.type not in ['attribution']:
                yield from   x.regurgitate()
        yield '\n'
        for x in self.children:
            yield from x.regurgitate()
        yield '\n'


class Grid(Block):
    def __init__(self, indent, attributes=None, citations=None, namespace=None):
        super().__init__(name='grid', indent=indent, attributes=attributes,  citations=citations, namespace=namespace)

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield "+++"
        for x in self.attributes:
            yield from x.regurgitate()
        yield "\n"
        for x in self.children:
            yield from x.regurgitate()
        yield '\n'

class Row(Block):
    def __init__(self, indent,  namespace=None):
        super().__init__(name='row', indent=indent, namespace=namespace)

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield ' | '.join([''.join(x.regurgitate()).replace('|', '\\|') for x in self.children]) + '\n'

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

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        for x in self.children:
            yield from x.regurgitate()

class Line(Block):
    def __init__(self, indent, attributes, content, citations=None, namespace=None):
        super().__init__(name='line', indent=indent, attributes=attributes, content=content, citations=citations, namespace=namespace)

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent) \
               + '|' + ''.join(str(x) for x in self.attributes) \
               + ' ' \
               + str(self.content) \
               + "\n"

    def add(self, b):
        if b.indent > self.indent:
            raise SAMParserStructureError('A Line cannot have children.')
        else:
            self.parent.add(b)

class Fragment(Block):
    def __init__(self, indent, attributes=None, citations=None, namespace=None):
        super().__init__(name='fragment', indent=indent, attributes=attributes, citations=citations, namespace=namespace)

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield '~~~'
        for x in self.attributes:
            yield from x.regurgitate()
        yield '\n'
        for x in self.children:
            yield from x.regurgitate()
        yield '\n'

class Blockquote(Block):
    def __init__(self, indent, attributes=None, citations=None, namespace=None):
        super().__init__(name='blockquote', indent=indent, attributes=attributes, citations=citations, namespace=namespace)

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield '"""'
        for x in self.attributes:
            yield from x.regurgitate()
        if self.citations:
            for x in self.citations:
                yield from x.regurgitate()
        yield '\n'
        for x in self.children:
            yield from x.regurgitate()
        yield '\n'

class RecordSet(Block):
    def __init__(self, name, field_names, indent, attributes=None, citations=None, namespace=None):
        super().__init__(name=name, indent=indent, attributes=attributes,  citations=citations, namespace=namespace)
        self.field_names = field_names

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield '{0}{1}::'.format(" " * int(self.indent), self.name)
        for x in self.attributes:
            yield from x.regurgitate()
        yield '{0}\n'.format(', '.join(self.field_names))
        for x in self.children:
            yield from x.regurgitate()


    def add(self, b):
        if b.indent <= self.indent:
            self.parent.add(b)
        elif not type(b) is Record:
            raise SAMParserStructureError('A RecordSet can only have Record children.')
        elif len(b.field_values) != len(self.field_names):
            raise SAMParserStructureError('Record length does not match record set header.')
        else:
            b.parent = self
            self.children.append(b)

class Record(Block):
    def __init__(self, field_values, indent, namespace=None):
        self.name='record'
        self.field_values = field_values
        self.content = None
        self.namespace = namespace
        self.indent = indent

    def __str__(self):
        return

    def regurgitate(self):
        yield " " * int(self.indent)
        yield ', '.join([''.join(x.regurgitate()).replace(',', '\\,') for x in self.field_values]) + '\n'

    def serialize_xml(self):
        record = list(zip(self.parent.field_names, self.field_values))
        yield '<record'

        if self.namespace is not None:
            if type(self.parent) is Root or self.namespace != self.parent.namespace:
                yield ' xmlns="{0}"'.format(self.namespace)
        yield ">\n"

        if record:
            for name, value in zip(self.parent.field_names, self.field_values):
                yield "<{0}>".format(name)
                yield from value.serialize_xml()
                yield "</{0}>\n".format(name)
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

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        for x in self.children:
            yield from x.regurgitate()

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

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield '{0}.'.format(str(self.parent.children.index(self) + 1))
        for x in self.attributes:
            yield from x.regurgitate()
        yield ' '
        for x in self.children:
            yield from x.regurgitate()
        yield "\n"


class UnorderedListItem(ListItem):
    def __init__(self, indent, attributes=None, citations=None,  namespace=None):
        super().__init__(name =  "li", indent = indent, attributes = attributes,  namespace = namespace)

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield '*'
        for x in self.attributes:
            yield from x.regurgitate()
        yield ' '
        for x in self.children:
            yield from x.regurgitate()

class LabeledListItem(ListItem):
    def __init__(self, indent, label, attributes=None, citations=None,  namespace=None):
        super().__init__(name="li", indent=indent, attributes=attributes, citations=citations,  namespace=namespace)
        self.label = label

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield '|{0}|'.format(self.label)
        for x in self.attributes:
            yield from x.regurgitate()
        yield ' '
        for x in self.children:
            yield from x.regurgitate()

    def serialize_xml(self):
        yield "<{0}".format(self.name)

        if self.namespace is not None:
            if type(self.parent) is Root or self.namespace != self.parent.namespace:
                yield ' xmlns="{0}"'.format(self.namespace)


        if self.attributes:
            if any([x.value for x in self.attributes if x.type == 'condition']):
                conditions = Attribute('conditions', ','.join([x.value for x in self.attributes if x.type == 'condition']))
                attrs = [x for x in self.attributes if x.type != 'condition']
                attrs.append(conditions)
                for att in sorted(attrs, key=lambda x: x.type):
                    yield from att.serialize_xml()
            else:
                for att in sorted(self.attributes, key=lambda x: x.type):
                    yield from att.serialize_xml()
        yield '>\n'
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
        * Raise error if asked to add anything else

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

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        if type(self.parent) in [Block, Blockquote, Remark, Fragment]:
            yield " " * int(self.indent)
            for x in self.children:
                yield from x.regurgitate()
            yield "\n\n"
        elif self.parent is None:
            for x in self.children:
                yield from x.regurgitate()
            yield "\n"
        elif self.parent.children.index(self) == 0:
            for x in self.children:
                yield from x.regurgitate()
            yield "\n"
        else:
            yield " " * int(self.indent)
            for x in self.children:
                yield from x.regurgitate()
            yield "\n"


    def _add_child(self, b):
        if type(b) is Flow:
            b.parent = self
            self.children.append(b)
        elif self.parent.name == 'li' and b.name in ['ol', 'ul', '#comment']:
            b.parent = self.parent
            self.parent.children.append(b)
        else:
            raise SAMParserStructureError(
                'A paragraph cannot have block children.')


class Comment(Block):
    def __init__(self, content, indent):
        self.content=content
        self.indent=indent
        self.name='#comment'
        self.namespace=None
        self.attributes=[]
        self.children=[]

    def _add_child(self, b):
        if self.parent.name == 'li' and b.name in ['ol', 'ul', '#comment']:
            b.parent = self.parent
            self.parent.children.append(b)
        else:
            raise SAMParserStructureError('A comment cannot have block children.')

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield u"#{0}\n".format(self.content)

    def serialize_xml(self):
        yield '<!-- {0} -->\n'.format(self.content.replace('--', '-\-'))


class StringDef(Block):
    def __init__(self, string_name, value, indent=0):
        super().__init__(name=string_name, content=value, indent=indent)

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield "{0}${1}={2}\n".format(" " * int(self.indent), self.name, self.content)

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

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        for x in self.children:
            yield from x.regurgitate()

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
            raise SAMParserStructureError('A SAM document can only have one root. Found "{0}".'.format(str(b)))
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
        return ''.join(self.regurgitate())

    def regurgitate(self):

        for i, x in enumerate(self):
            if hasattr(x, 'regurgitate'):
                yield from x.regurgitate()
            elif i == 0:
                match = block_patterns['block-start'].match(x)
                if match is not None:
                    yield escape_for_sam(x).replace(':', '\\:')
                else:
                    yield escape_for_sam(x)
            else:
                yield escape_for_sam(x)


    def append(self, thing):
        if type(thing) is Attribute:
            for i in reversed(self):
                if type(i is Phrase):
                    i.add_attribute(thing)
                    break

        elif isinstance(thing, Annotation):
            if type(self[-1]) is Phrase:
                self[-1].append(thing)
            else:
                super().append(thing)

        elif type(thing) is Citation:
            try:
                if type(self[-1]) is Phrase:
                    self[-1].annotations.append(thing)
                else:
                    super().append(thing)
            except IndexError:
                super().append(thing)

        elif not thing == '':
            super().append(thing)

    def find_last_annotation(self, text, mode):

        try:
            return annotation_lookup_modes[mode](self, text)
        except KeyError:
            raise SAMParserError("Unknown annotation lookup mode: " + mode)
        # if mode=='case insensitive':
        #     for i in reversed(self):
        #         if type(i) is Phrase:
        #             if [x for x in i.annotations if not x.local] and i.text.lower() == text.lower():
        #                 return [x for x in i.annotations if not x.local]
        # else:
        #     for i in reversed(self):
        #         if type(i) is Phrase:
        #             if [x for x in i.annotations if not x.local] and i.text == text:
        #                 return [x for x in i.annotations if not x.local]
        # return None

    def serialize_xml(self):
        for x in self:
            try:
                yield from x.serialize_xml()
            except AttributeError:
                yield escape_for_xml(x)

def _annotation_lookup_case_sensitive(flow, text):
    for i in reversed(flow):
        if type(i) is Phrase:
            if [x for x in i.annotations if not x.local] and i.text == text:
                return [x for x in i.annotations if not x.local]
    return None

def _annotation_lookup_case_insensitive(flow, text):
    for i in reversed(flow):
        if type(i) is Phrase:
            if [x for x in i.annotations if not x.local] and i.text.lower() == text.lower():
                return [x for x in i.annotations if not x.local]
    return None


annotation_lookup_modes = {
    'case sensitive': _annotation_lookup_case_sensitive,
    'case insensitive': _annotation_lookup_case_insensitive
}



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
        self.indent = min_indent

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        for x in self.lines:
            yield " " * int(self.indent)
            yield x

    def serialize_xml(self):
        for x in self.lines:
            yield escape_for_xml(x)

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
        self.annotation_lookup = "case insensitive"
        self.ids = []

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield from self.root.regurgitate()

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

    def ancestor_or_self(self, ancestor_name, block=None):
        """
        Returns a block that is the reference block or it ancestor based on its name.
        
        For SAM's concrete types is it better to use ancestor_or_self_type as
        the names of concrete types could be changed in the schema. 
        
        :param ancestor_name: The name or names of the block to return.
        :param block: The reference block. If not specified, the current block is used.
        :return: The block requested, nor None if no block matches.
        """
        if block is None:
            block = self.current_block
        try:
            while True:
                if block.name in ancestor_name:
                    return block
                block = block.parent
        except(AttributeError):
            return None

    def ancestor_or_self_type(self,ancestor_type, block=None):
        """
        Returns a block that is the reference block or it ancestor based on its type.

        For named blocks is it better to use ancestor_or_self as
        all named blocks are of type Block. 

        :param ancestor_name: The type or names of the block to return.
        :param block: The reference block. If not specified, the current block is used.
        :return: The block requested, nor None if no block matches.
        """

        test_list = []
        try:
            test_list.extend(ancestor_type)
        except TypeError:
            test_list.append(ancestor_type)
        if block is None:
            block = self.current_block
        try:
            while True:
                if type(block) in test_list:
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
                    raise SAMParserStructureError('Duplicate ID found "{0}".'.format(block.attributes['id']))
                self.ids.append(block.attributes['id'])
        except (TypeError, AttributeError):
            pass

        # Check IDs from included files
        try:
            overlapping_ids = set(block.ids) & set(self.ids)
            if overlapping_ids:
                raise SAMParserStructureError('Duplicate ID found "{0}".'.format(', '.join(overlapping_ids)))
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
        declared IDs for the document and raises a SAMParserStructureError "Duplicate ID found"
        if there is a duplicate. 
        :param flow: The Flow object to add.
        :return: None.
        """

        # Check for duplicate IDs in the flow
        # Add any ids found to list of ids
        ids=[f.id for f in flow if type(f) is Phrase and f.id is not None]
        for id in ids:
            if id in self.ids:
                raise SAMParserStructureError('Duplicate ID found "{0}".'.format(ids[0]))
            self.ids.append(id)

        self.current_block._add_child(flow)


    def find_last_annotation(self, text, node=None):
        """
        Finds the last annotation in the current document with the specified text. 
        In this case, "last" means the most recent instance of that annotation text 
        in document order. In other words, the method searches backwards through the 
        document and stops at the first occurrence of an annotation with that text that
        it encounters.

        Annotations can only exist inside flows, so the flow version of find_last_annotation()
        does all the work. The block version just passes the call on to child blocks
        so that their flows get searched. That is why we only need to pass the annotation_lookup
        mode parameter to the flow version.
        
        :param text: The annotation text to search for. 
        :param node: The node in the document tree to start the search from. If not specified, 
        the seach defaults to self.root, meaning the entire document is searched.
        :return: The last matching annotation object, or None. 
        """
        if node is None:
            node = self.root
        if type(node) is Flow:
            result = node.find_last_annotation(text, mode=self.annotation_lookup)
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
    def __init__(self, doc, content, href, indent):
        self.children=doc.root.children
        self.indent = indent
        self.namespace = None
        self.ids = doc.ids
        self.name = "<<<"
        self.content = content
        self.href= href

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield "<<<(" + self.content + ")\n\n"

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
        self.current_line_number=0

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
        self.current_line_number += 1
        return self.current_line

    def return_line(self):
        self.pending_line = self.current_line
        self.current_line = self.previous_line
        self.current_line_number -= 1




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
        self.stateMachine.add_state("PHRASE-END", self._phrase_end)
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
        match = flow_patterns['phrase'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            text = unescape(match.group("text"))
            if self.smart_quotes:
                text = multi_replace(text, smart_quote_subs)
            p = Phrase(text)
            self.flow.append(p)
            para.advance(len(match.group(0)))

            if flow_patterns['annotation'].match(para.rest_of_para):
                return "ANNOTATION-START", para
            elif flow_patterns['citation'].match(para.rest_of_para):
                return "CITATION-START", para
            else:
                # If there is an annotated phrase with no annotation, look back
                # to see if it has been annotated already, and if so, copy the
                # closest preceding annotation.
                # First look back in the current flow
                # (which is not part of the doc structure yet).
                previous = self.flow.find_last_annotation(text, self.doc.annotation_lookup)
                if previous is not None:
                    p.annotations.extend(previous)
                else:
                    # Then look back in the document.
                    previous = self.doc.find_last_annotation(text)
                    if previous is not None:
                        p.annotations.extend(previous)

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

    def _phrase_end(self, para):
        phrase = self.flow[-1]
        if not phrase.annotated:
            # If there is a phrase with no annotation, look back
            # to see if it has been annotated already, and if so, copy the
            # closest preceding annotation.
            # First look back in the current flow
            # (which is not part of the doc structure yet).
            previous = self.flow.find_last_annotation(phrase.text, self.doc.annotation_lookup)
            if previous is not None:
                phrase.annotations.extend(previous)
            else:
                # Then look back in the document.
                previous = self.doc.find_last_annotation(phrase.text)
                if previous is not None:
                    phrase.annotations.extend(previous)

                # Else output a warning.
                else:
                    SAM_parser_warning(
                        "Unannotated phrase found: {" +
                        phrase.text + "} " +
                        "If you are trying to insert curly braces " +
                        "into the document, use \{" + phrase.text + "}."
                    )

        return "PARA", para

    def _annotation_start(self, para):
        match = flow_patterns['annotation'].match(para.rest_of_para)
        phrase = self.flow[-1]
        if match:
            annotation_type = match.group('type')
            is_local = bool(match.group('plus'))

            # Check for link shortcut
            if urlparse(annotation_type, None).scheme is not None:
                specifically = annotation_type
                annotation_type = 'link'
            else:
                specifically = match.group('specifically') if match.group('specifically') is not None else None
            namespace = match.group('namespace').strip() if match.group('namespace') is not None else None

            if annotation_type[0] == '=':
                if type(phrase) is Code:
                    phrase.add_attribute(Attribute('encoding', unescape(annotation_type[1:]), is_local))
                else:
                    raise SAMParserStructureError("Only code can have an embed attribute.")
            elif annotation_type[0] == '!':
                phrase.add_attribute(Attribute('xml:lang', unescape(annotation_type[1:]), is_local))
            elif annotation_type[0] == '*':
                phrase.add_attribute(Attribute('id', unescape(annotation_type[1:]), is_local))
            elif annotation_type[0] == '#':
                phrase.add_attribute(Attribute('name', unescape(annotation_type[1:]), is_local))
            elif annotation_type[0] == '?':
                phrase.add_attribute(Attribute('condition', unescape(annotation_type[1:]), is_local))
            else:
                if type(self.flow[-1]) is Code:
                    phrase.add_attribute(Attribute('language', unescape(annotation_type), is_local))
                else:
                    phrase.annotations.append(Annotation(annotation_type, unescape(specifically), namespace, is_local))
            para.advance(len(match.group(0)))
            if flow_patterns['annotation'].match(para.rest_of_para):
                return "ANNOTATION-START", para
            elif flow_patterns['citation'].match(para.rest_of_para):
                return "CITATION-START", para
            else:
                para.retreat(1)
                return "PHRASE-END", para
        else:
            self.current_string += '('
            return "PARA", para

    def _citation_start(self, para):
        match = flow_patterns['citation'].match(para.rest_of_para)
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
                keyref = match.group('key')
            except IndexError:
                keyref = None
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
            elif keyref:
                citation_type = 'keyref'
                citation_value = keyref.strip()
                extra = match.group('key_extra')
            else:
                citation_type = 'value'
                citation_value = citation.strip()
                extra = None

            self.flow.append(Citation(citation_type, citation_value, extra))
            para.advance(len(match.group(0)))
            if flow_patterns['annotation'].match(para.rest_of_para):
                return "ANNOTATION-START", para
            elif flow_patterns['citation'].match(para.rest_of_para):
                return "CITATION-START", para
            else:
                para.retreat(1)
                return "PARA", para
        else:
            self.current_string += '['
            return "PARA", para

    def _bold_start(self, para):
        match = flow_patterns['bold'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            p = Phrase(unescape(match.group("text")))
            self.flow.append(p)
            p.annotations.append(Annotation('bold'))
            para.advance(len(match.group(0)))
        else:
            self.current_string += '*'
            return "PARA", para

        if flow_patterns['annotation'].match(para.rest_of_para):
            return "ANNOTATION-START", para
        elif flow_patterns['citation'].match(para.rest_of_para):
            return "CITATION-START", para
        else:
            para.retreat(1)
            return "PARA", para

    def _italic_start(self, para):
        match = flow_patterns['italic'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            p = Phrase(unescape(match.group("text")))
            self.flow.append(p)
            p.annotations.append(Annotation('italic'))
            para.advance(len(match.group(0)))
        else:
            self.current_string += '_'
            return "PARA", para

        if flow_patterns['annotation'].match(para.rest_of_para):
            return "ANNOTATION-START", para
        elif flow_patterns['citation'].match(para.rest_of_para):
            return "CITATION-START", para
        else:
            para.retreat(1)
            return "PARA", para

    def _code_start(self, para):
        match = flow_patterns['code'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            self.flow.append(Code((match.group("text")).replace("``", "`")))
            para.advance(len(match.group(0)))
        else:
            self.current_string += '`'
            return "PARA", para

        if flow_patterns['annotation'].match(para.rest_of_para):
            return "ANNOTATION-START", para
        elif flow_patterns['citation'].match(para.rest_of_para):
            return "CITATION-START", para
        else:
            para.retreat(1)
            return "PARA", para

    def _dash_start(self, para):
        if self.smart_quotes:
            if flow_patterns['en-dash'].search(para.para, para.currentCharNumber,
                                                          para.currentCharNumber + 5):
                self.current_string += '–'
                self.flow_source.advance(1)

            elif flow_patterns['em-dash'].search(para.para, para.currentCharNumber,
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
            if flow_patterns['double_quote_close'].search(para.para, para.currentCharNumber,
                                                          para.currentCharNumber + 2):
                self.current_string += '”'
            elif flow_patterns['double_quote_open'].search(para.para, para.currentCharNumber,
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
            if flow_patterns['single_quote_close'].search(para.para, para.currentCharNumber,
                                                          para.currentCharNumber + 2):
                self.current_string += '’'
            elif flow_patterns['single_quote_open'].search(para.para, para.currentCharNumber,
                                                           para.currentCharNumber + 2):
                self.current_string += '‘'
            elif flow_patterns['apostrophe'].search(para.para, para.currentCharNumber, para.currentCharNumber + 2):
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
        match = flow_patterns['inline-insert'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            attributes, citations = parse_attributes(match.group("attributes"))
            type, item =parse_insert(match.group("insert"))

            self.flow.append(InlineInsert(type, item, attributes, citations))
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
        self.annotations = []
        self.attributes = []

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield u'{{{0:s}}}'.format(escape_for_sam(self.text))
        for x in self.attributes:
            yield from x.regurgitate()
        for x in self.annotations:
            yield from x.regurgitate()



    def add_attribute(self, attr):
        if attr.type == "condition":
            self.attributes.append(attr)
        elif any(x.type == attr.type for x in self.attributes):
            raise SAMParserStructureError("A phrase cannot have more than one {0}: {1}".format(attr.type, attr.value))
        else:
            self.attributes.append(attr)

    @property
    def id(self):
        for x in self.attributes:
            if x.type == 'id':
                return x.value
        return None

    @property
    def annotated(self):
        return len([x for x in self.annotations if not x.local]) > 0 or \
               len([x for x in self.attributes if not x.local]) > 0


    def serialize_xml(self):
        yield '<phrase'
        if any([x.value for x in self.attributes if x.type == 'condition']):
            conditions = Attribute('conditions', ','.join([x.value for x in self.attributes if x.type == 'condition']))
            attrs = [x for x in self.attributes if x.type != 'condition']
            attrs.append(conditions)
            for att in sorted(attrs, key=lambda x: x.type):
                yield from att.serialize_xml()
        else:
            for att in sorted(self.attributes, key=lambda x: x.type):
                yield from att.serialize_xml()
        yield '>'

        #Nest attributes for serialization
        if self.annotations:
            ann, *rest = self.annotations
            yield from ann.serialize_xml(rest, escape_for_xml(self.text))
        else:
            yield escape_for_xml(self.text)
        yield '</phrase>'

    def append(self, thing):
        if not self.child:
            self.child = thing
        else:
            self.child.append(thing)

class Code(Phrase):

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield '`{0}`'.format(self.text.replace('`', '``'))
        for x in self.annotations:
            yield from x.regurgitate()
        for x in self.attributes:
            yield from x.regurgitate()

    def serialize_xml(self):

        if any(x for x in self.attributes if x.type == "encoding"):
            tag = "embed"
        else:
            tag = "code"

        yield '<' + tag
        if any([x.value for x in self.attributes if x.type == 'condition']):
            conditions = Attribute('conditions',
                                   ','.join([x.value for x in self.attributes if x.type == 'condition']))
            attrs = [x for x in self.attributes if x.type != 'condition']
            attrs.append(conditions)
            for att in sorted(attrs, key=lambda x: x.type):
                yield from att.serialize_xml()
        else:
            for att in sorted(self.attributes, key=lambda x: x.type):
                yield from att.serialize_xml()
        yield '>'
        yield escape_for_xml(self.text)
        yield '</' + tag + '>'

    def append(self, thing):
        raise SAMParserStructureError("Inline code cannot have typed annotations.")

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
    attribute_symbols = {'language': '',
                         'name': '#',
                         'condition': '?',
                         'id': '*',
                         'xml:lang': '!',
                         'encoding': '=',
                         'attribution': '',
                         'type': '',
                         'item': '',
                         'key': '%'}

    def __init__(self, type, value, local=False):
        self.type = type
        self.value = value
        self.local = local

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield '(%s%s)' % (Attribute.attribute_symbols[self.type], self.value)

    def serialize_xml(self):
        yield ' %s="%s"' % (self.type, escape_for_xml_attribute(self.value))


class Annotation:
    def __init__(self, annotation_type, specifically='', namespace='', local=False):
        self.annotation_type = annotation_type.strip()
        self.specifically = specifically
        self.namespace = namespace
        self.local = local

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield '({0}'.format(self.annotation_type)
        yield (' "{0}"'.format(self.specifically.replace('"','\\"')) if self.specifically else '')
        yield (' ({0})'.format(self.namespace) if self.namespace else '')
        yield ')'

    def serialize_xml(self, annotations=None, payload=None):
        yield '<annotation'
        if self.annotation_type:
            yield ' type="{0}"'.format(self.annotation_type)
        if self.specifically:
            yield ' specifically="{0}"'.format(escape_for_xml_attribute(self.specifically))
        if self.namespace:
            yield ' namespace="{0}"'.format(self.namespace)

        #Nest annotations for serialization
        if annotations:
            anns, *rest = annotations
            yield '>'
            yield from anns.serialize_xml(rest, payload)
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
        self.citation_extra = None if citation_extra is None else citation_extra.strip()
        self.local=True
        self.child = None

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield '['
        if self.citation_type == 'value':
            pass
        elif self.citation_type == 'idref':
            yield '*'
        elif self.citation_type == 'nameref':
            yield '#'
        else:
            yield '{0} '.format(self.citation_type)
        yield self.citation_value
        if self.citation_extra:
            yield ' {0}'.format(self.citation_extra)
        yield ']'


        #u'[{0:s} {1:s} {2:s}]'.format(self.citation_type, self.citation_value, cit_extra)

    def serialize_xml(self, attrs=None, payload=None):
        yield '<citation'
        if self.citation_extra is not None:
            if self.citation_extra:
                yield ' extra="{0}"'.format(escape_for_xml_attribute(self.citation_extra))
        yield ' {0}="{1}"'.format(self.citation_type, escape_for_xml_attribute(self.citation_value))
        #Nest attributes for serialization
        if attrs:
            attr, *rest = attrs
            yield '>'
            yield from attr.serialize_xml(rest, payload)
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
    def __init__(self, type, item, attributes=None, citations=None):
        self.type = type
        self.item = item
        self.attributes = attributes
        self.citations = citations

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        type_symbol = Attribute.attribute_symbols.get(self.type)
        if type_symbol:
            yield '>({0}{1})'.format(type_symbol, self.item)
        else:
            yield '>({0} {1})'.format(self.type, self.item)
        for x in self.attributes:
            yield from x.regurgitate()


    def serialize_xml(self):

        attrs=[Attribute('type', self.type), Attribute('item', self.item)]

        yield '<inline-insert'

        if self.attributes:
            if any([x.value for x in self.attributes if x.type == 'condition']):
                conditions = Attribute('conditions', ','.join([x.value for x in self.attributes if x.type == 'condition']))
                attrs.append(conditions)
                attrs.extend([x for x in self.attributes if x.type != 'condition'])

        for att in sorted(attrs, key=lambda x: x.type):
            yield from att.serialize_xml()

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

class SAMParserStructureError(Exception):
    """
    Raised if the DocStructure encounters an invalid structure.
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
            raise SAMParserStructureError('Unrecognized character "{0}" found in attributes list.'.format(x.group('bad')))

    unflagged_attributes = [x for x in attributes_list if not (x[0] in '?#*!=')]
    if unflagged_attributes:
        if unflagged is None:
            raise SAMParserStructureError("Unexpected attribute(s). Found: {0}".format(', '.join(unflagged_attributes)))
        elif len(unflagged_attributes) > 1:
            raise SAMParserStructureError("More than one {0} attribute specified. Found: {1}".format(unflagged, ', '.join(unflagged_attributes)))
        else:
            attributes.append(Attribute(unescape(unflagged), unescape(unflagged_attributes[0])))
    ids = [x[1:] for x in attributes_list if x[0] == '*']
    if ids and not '*' in flagged:
        raise SAMParserStructureError('IDs not allowed in this context. Found: {0}'.format(', *'.join(ids)))
    if len(ids) > 1:
        raise SAMParserStructureError('More than one ID specified. Found: "{0}".'.format(", ".join(ids)))
    names = [x[1:] for x in attributes_list if x[0] == '#']
    if names and not '#' in flagged:
        raise SAMParserStructureError('Names not allowed in this context. Found: #{0}'.format(', #'.join(names)))
    if len(names) > 1:
        raise SAMParserStructureError('More than one name specified. Found: #{0}'.format(", #".join(names)))
    language_tag = [x[1:] for x in attributes_list if x[0] == '!']
    if language_tag and not '!' in flagged:
        raise SAMParserStructureError('Language tag not allowed in this context. Found: !{0}'.format(', !'.join(language_tag)))
    if len(language_tag) > 1:
        raise SAMParserStructureError('More than one language tag specified. Found: !{0}'.format(", !".join(language_tag)))
    embed = [x[1:] for x in attributes_list if x[0] == '=']
    if embed and not '=' in flagged:
        raise SAMParserStructureError('Embeded encoding specification not allowed in this context. Found: !{0}'.format(', !'.join(embed)))
    if len(embed) > 1:
        raise SAMParserStructureError('More than one embedded encoding specified. Found: {0}.',format(", ".join(embed)))
    conditions = [x[1:] for x in attributes_list if x[0] == '?']
    if embed:
        attributes.append(Attribute("encoding", unescape(embed[0])))
    if language_tag:
        attributes.append(Attribute("xml:lang", unescape(language_tag[0])))
    if ids:
        attributes.append(Attribute("id", unescape(ids[0])))
    if names:
        attributes.append(Attribute("name", unescape(names[0])))
    if conditions:
        for c in conditions:
            attributes.append(Attribute("condition", unescape(c)))

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
            citation_type = 'value'
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
    #result.append(Attribute('type', unescape(insert_type)))
    # strip unnecessary quotes from insert item
    insert_item = re.sub(r'^(["\'])|(["\'])$', '', insert_item)
    if insert_item == '':
        raise SAMParserStructureError ("Insert item not specified in: {0}".format(annotation_string))
    #result.append(Attribute('item', unescape(insert_item)))
    return insert_type, insert_item


def escape_for_sam(s):
    t = dict(zip([ord('['), ord('{'), ord('&'), ord('\\')], ['\\[', '\\{', '\\&', '\\\\']))
    try:
        return s.translate(t)
    except AttributeError:
        return s

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
        raise SAMParserStructureError("Unrecognized character entity found: {0}".format(charref))
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
    argparser.add_argument("-regurgitate", "-r", help="regurgitate the input in normalized form",
                           action="store_true")

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

                if args.outdir:
                    outputfile = os.path.join(args.outdir,
                                              os.path.splitext(os.path.basename(inputfile))[0] + args.outputextension)
                else:
                    outputfile = args.outfile

                if args.intermediatedir:
                    intermediatefile=os.path.join(args.intermediatedir, os.path.splitext(os.path.basename(inputfile))[0] + args.intermediateextension)
                else:
                    intermediatefile=args.intermediatefile


                xml_string = "".join(samParser.serialize('xml')).encode('utf-8')


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
                    except etree.XSLTError as e:
                        raise SAMParserError("XSLT processor reported error: " + str(e))
                    finally:
                        if transform.error_log:
                            SAM_parser_warning("Messages from the XSLT transformation:")
                            for entry in transform.error_log:
                                print('message from line %s, col %s: %s' % (
                                    entry.line, entry.column, entry.message), file=sys.stderr)
                                print('domain: %s (%d)' % (entry.domain_name, entry.domain), file=sys.stderr)
                                print('type: %s (%d)' % (entry.type_name, entry.type), file=sys.stderr)
                                print('level: %s (%d)' % (entry.level_name, entry.level), file=sys.stderr)


                    if transform.error_log:
                        SAM_parser_warning("Messages from the XSLT transformation:")
                        for entry in transform.error_log:
                            print('message from line %s, col %s: %s' % (
                                entry.line, entry.column, entry.message), file=sys.stderr)
                            print('domain: %s (%d)' % (entry.domain_name, entry.domain), file=sys.stderr)
                            print('type: %s (%d)' % (entry.type_name, entry.type), file=sys.stderr)
                            print('level: %s (%d)' % (entry.level_name, entry.level), file=sys.stderr)

                if outputfile:
                    with open(outputfile, "wb") as outf:
                        if args.regurgitate:
                            for i in samParser.doc.regurgitate():
                                outf.write(i.encode('utf-8'))
                        elif transformed:
                            outf.write(str(transformed).encode(encoding='utf-8'))
                        else:
                            for i in samParser.serialize('xml'):
                                outf.write(i.encode('utf-8'))
                else:
                    if args.regurgitate:
                        for i in samParser.doc.regurgitate():
                            sys.stdout.buffer.write(i.encode('utf-8'))
                    elif transformed:
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