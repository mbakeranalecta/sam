import sys
from statemachine import StateMachine
from lxml import etree
import xml.parsers.expat
import html
import argparse
import urllib.request
from urllib.parse import urljoin
import pathlib
import codecs
import os
import io
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
re_citation = r'(\[\s*(?P<citation>.*?)\])'


block_patterns = {
            'comment': re.compile(re_indent + re_comment, re.U),
            'remark-start': re.compile(
                re_indent + r'(?P<flag>!!!)(' + re_attributes + ')?\s*(?P<unexpected>.*)',
                re.U),
            'declaration': re.compile(re_indent + '!' + re_name + r'(?<!\\):' + re_content + r'?', re.U),
            'block-start': re.compile(re_indent + re_name + r'(?<!\\):' + re_attributes +
                                      '((\s' + re_content + r'?)|$)', re.U),
            'codeblock-start': re.compile(
                re_indent + r'(?P<flag>```)(' + re_attributes + ')?\s*(?P<unexpected>.*)',
                re.U),
            'grid-start': re.compile(re_indent + r'\+\+\+' + re_attributes, re.U),
            'blockquote-start': re.compile(
                re_indent + r'"""(' + re_remainder + r')?',
                re.U),
            'alt-blockquote-start': re.compile(
                re_indent + r"'''(" + re_remainder + r')?',
                re.U),
            'fragment-start': re.compile(re_indent + r'~~~' + re_attributes, re.U),
            'paragraph-start': re.compile(r'\w*', re.U),
            'line-start': re.compile(re_indent + r'\|' + re_attributes + re_one_space + re_content, re.U),
            'blank-line': re.compile(r'^\s*$'),
            'record-start': re.compile(re_indent + re_name + r'(?<!\\)::' + re_attributes +
                                       '(?P<field_names>.*)', re.U),
            'list-item': re.compile(re_indent + re_ul_marker + re_attributes + re_spaces + re_content, re.U),
            'num-list-item': re.compile(re_indent + re_ol_marker + re_attributes + re_spaces + re_content, re.U),
            'labeled-list-item': re.compile(re_indent + re_ll_marker + re_attributes + re_spaces + re_content, re.U),
            'block-insert': re.compile(re_indent + r'>>>((\((?P<insert>.+?)\))|(\[(?P<ref>.*?(?<!\\))\]))'
                                                   r'(' + re_attributes + ')?\s*(?P<unexpected>.*)', re.U),
            'include': re.compile(re_indent + r'<<<' + re_attributes, re.U),
            'variable-def': re.compile(re_indent + r'\$' + re_name + '\s*=\s*' + re_content, re.U)
        }



# Flow patterns
flow_patterns = {
            'escape': re.compile(r'\\', re.U),
            'phrase': re.compile(r'(?<!\\)\{(?P<text>.*?)(?<!\\)\}'),
            'annotation': re.compile(
                r'''
                (
                    (?P<flag>[-\+]?)                         #flag
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
            'inline-insert': re.compile(r'>((\((?P<insert>.+?)\)))' + re_attributes, re.U),
            'citation': re.compile(
                r'(\[\s*(?P<citation>.*?)\])',
                re.U)
        }

insert_reference_symbols = {'nameref': '#',
                            'idref': '*',
                            'keyref': '%',
                            'variableref': '$'}

insert_reference_methods = {'#': 'nameref',
                            '*': 'idref',
                            '%': 'keyref',
                            '$': 'variableref'}

citation_reference_symbols = {'nameref': '#',
                              'idref': '*',
                              'keyref': '%',
                              'value': ''}

citation_reference_methods = {'#': 'nameref' ,
                              '*':'idref' ,
                              '%':'keyref'}

#smart quote patterns
re_single_quote_close = '(?<=[\w\.\,\"!:;)}\?-])\'((?=[\.\s"},\?!:;\[])|$)'
re_single_quote_open = '(^|(?<=[\s\"{]))\'(?=[\w"{-])'
re_double_quote_close = '(?<=[\w\.\,\'\)\}\?!:;-])\"((?=[\.\s\'\)},\?!:;\[-])|$)'
re_double_quote_open = '(^|(?<=[\s\'{\(]))"(?=[\w\'{-])'
re_apostrophe = "(?<=[\w`\*_\}\)])'(?=\w)"
re_en_dash = "(?<=[\w\*_`\"\'\.\)\}\]]\s)--(?=\s[\w\*_`\"\'\{\(\[])"
re_em_dash = "(?<=[\w\*_`\"\'\.\)\}\]])---(?=[\w\*_`\"\'\{\(\[])"

smart_quote_subs = {re.compile(re_double_quote_close):'”',
                    re.compile(re_double_quote_open): '“',
                    re.compile(re_single_quote_close):'’',
                    re.compile(re_single_quote_open): '‘',
                    re.compile(re_apostrophe): '’',
                    re.compile(re_en_dash): '–',
                    re.compile(re_em_dash): '—'}

smart_quote_sets = {'on': smart_quote_subs}

known_insert_types = ["image", "video", "audio", "feed", "app", "object"]
known_file_types = [".gif", ".jpeg", ".jpg", ".png",
                    ".apng", ".bmp", ".svg", ".ico",
                    ".ogv", ".ogg", ".mp4", ".m4a",
                    ".m4p", ".m4b", ".m4r", ".m4v",
                    ".webm", ".oga", ".l16", ".wav",
                    ".aiff", ".au", ".pcm", ".mp3",
                    ".m4a", ".mp4", ".3gp", ".m4a",
                    ".m4b", ".m4p", ".m4r", ".m4v",
                    ".aac", ".spx", ".opus", ".atom",
                    ".rss", ".jar"]
# XML in not included in the above list because it can be used for indirect identification of resources

# The following functions are intended for use with the find_all() or find_(first) functions.
# The find_all and find_first functions iterate over the document tree executing a find function
# on each node. The find_first function returns at the first non-None item returned by the find function.
# The find_all function returns a list of all the items returned by the execution of the find funciton.

def get_ids(this):
    """
    Gets a list of the ids present in the document. Designed to be called using the
    find_all() function of the DocStructure object or of any object in the document tree.
    :param this: The 'self' variable of the object to be searched. This is passed to the get_ids()
    function by find_all()
    :return: Returns a list of the id found in the document as strings. This list is concatenated with
    lists returned by executing get_ids() on other objects to compile a complete list of ids in
    the document or the part of the tree the find_all() function is called on.
    """
    result = []
    if hasattr(this, 'ID'):
        if this.ID:
            result.append(this.ID)
    return result

def get_idrefs(this):
    """
    Gets a list of the idrefs present in the document. Designed to be called using the
    find_all() function of the DocStructure object or of any object in the document tree.
    :param this: The 'self' variable of the object to be searched. This is passed to the get_idrefs()
    function by find_all()
    :return: Returns a list of the idrefs found in the document as strings. This list is concatenated with
    lists returned by executing get_idrefs() on other objects to compile a complete list of idrefs in
    the document or the part of the tree the find_all() function is called on.
    """
    result = []
    if hasattr(this, 'idrefs'):
        result.extend(this.idrefs)
    if hasattr(this, 'citations'):
        for x in this.citations:
            result.extend(x.idrefs)
    return result

def get_object_with_id(this, ID):
    """
    Gets the first object in the document structure with the id matching the ID parameter.
    Designed to be called using the
    find_first() function of the DocStructure object or of any object in the document tree.
    :param this: The 'self' variable of the object to be searched. This is passed to the get_object_with_id()
    function by find_all()
    :param ID: The id of the object to be returned.
    :return: The first object found with the corresponding ID.
    """
    result = None
    if hasattr(this, 'ID'):
        if this.ID == ID:
            result = this
    return result


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
        self.stateMachine.add_state("VARIABLE-DEF", self._variable_def)
        self.stateMachine.add_state("LINE-START", self._line_start)
        self.stateMachine.add_state("END", None, end_state=1)
        self.stateMachine.set_start("SAM")
        self.current_text_block = None
        self.doc = None
        self.source = None
        self.source_url = None
        self.flow_parser = FlowParser()

    def parse(self, source):
        self.source = StringSource(source)
        try:
            self.source_url = source.geturl()
        except AttributeError:
            try:
                self.source_url = pathlib.Path(os.path.abspath(source.name)).as_uri()
            except AttributeError:
                self.source_url = None
        self.doc = DocStructure(self.source_url)
        try:
            self.stateMachine.run((self.source, None))
        except SAMParserStructureError as err:
            raise SAMParserError("Structure error: {0} at line {1}:\n\n {2}\n".format(
                ' '.join(err.args), self.source.current_line_number,  self.source.current_line))
        except EOFError:
            raise SAMParserError("Document ended before structure was complete.")
        all_id_refs = self.doc.find_all(get_idrefs)
        unmatched_idrefs = set(all_id_refs) - set(self.doc.ids)
        if unmatched_idrefs:
            raise SAMParserError("Idrefs found with no corresponding IDs: {0}".format(", ".join(unmatched_idrefs)))
        return self.doc

    def parse_file(self, inputfile):
        try:
            with open(inputfile, "r", encoding="utf-8-sig") as inf:
                SAM_parser_info("Parsing " + os.path.abspath(inf.name), blank_line=True)
                self.parse(inf)
        except FileNotFoundError:
            raise SAMParserError("No input file specified.")

    def _block(self, context):
        source, match = context
        indent = match.end("indent")
        block_name = match.group("name").strip()
        attributes, citations = parse_attributes(match.group("attributes"))
        content = match.group("content").strip()
        parsed_content = None if content == '' else self.flow_parser.parse(content, self.doc)
        b = Block(block_name, indent, attributes, parsed_content, citations)
        self.doc.add_block(b)
        return "SAM", context

    def _codeblock_start(self, context):
        source, match = context
        if match.group("unexpected"):
            raise SAMParserStructureError('Unexpected characters in codeblock header. '
                                          'Found "{0}"'.format(match.group("unexpected")))
        indent = match.end("indent")

        attributes, citations = parse_attributes(match.group("attributes"), flagged="*#?!=", unflagged="code_language")

        if "encoding" in attributes and "code_language" in attributes:
            raise SAMParserError("A codeblock cannot have both an encoding attribute and a code_language attribute. At:{0}".format(match.group(0).strip()))
        if 'encoding' in attributes:
            b = Embedblock(indent, attributes, citations)
        else:
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
            f = self.flow_parser.parse(self.current_text_block.text, self.doc)
            self.current_text_block = None
            self.doc.add_flow(f)
            return "END", context

        para_indent = self.doc.current_block.indent
        first_line_indent = len(match.string) - len(match.string.lstrip())
        this_line_indent = len(line) - len(line.lstrip())

        if block_patterns['blank-line'].match(line):
            f = self.flow_parser.parse(self.current_text_block.text, self.doc)
            self.current_text_block = None
            self.doc.add_flow(f)
            return "SAM", context

        if this_line_indent < para_indent:
            f = self.flow_parser.parse(self.current_text_block.text, self.doc)
            self.current_text_block = None
            self.doc.add_flow(f)
            source.return_line()
            return "SAM", context

        if self.doc.in_context(['p', 'li']):
            if block_patterns['list-item'].match(line) or block_patterns['num-list-item'].match(line) or block_patterns[
                'labeled-list-item'].match(line):
                f = self.flow_parser.parse(self.current_text_block.text, self.doc)
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
        lli = LabeledListItem(indent, self.flow_parser.parse(label, self.doc), attributes, citations)
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
        if match.group("attributes"):
            attributes, citations = parse_attributes(match.group("attributes"), flagged="*#?")
        else:
            attributes, citations = {},[]
        b = BlockInsert(indent, parse_insert(match.group("insert")), attributes, citations)
        self.doc.add_block(b)
        return "SAM", context

    def _include(self, context):
        source, match = context
        indent = match.end("indent")
        href=match.group("attributes")[1:-1]

        try:
            fullhref = urllib.parse.urljoin(self.source_url, href)
        except SAMParserFileError as e:
            raise SamParserError (" at ".join(str(e), match.group(0)))

        if fullhref in included_files:
            raise SAMParserError("Duplicate file inclusion detected with file: " + fullhref)
        else:
            included_files.append(fullhref)

        reader = codecs.getreader("utf-8")
        SAM_parser_info("Parsing include " + fullhref)
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

    def _variable_def(self, context):
        source, match = context
        indent = match.end("indent")
        s = VariableDef(match.group('name'), self.flow_parser.parse(match.group('content'), self.doc), indent=indent)
        self.doc.add_block(s)
        return "SAM", context

    def _line_start(self, context):
        source, match = context
        indent = match.end("indent")
        attributes, citations = parse_attributes(match.group("attributes"))
        b=Line(indent, attributes,
               self.flow_parser.parse(match.group('content'), self.doc, strip=False), citations)
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
            field_values = [self.flow_parser.parse(x.strip(), self.doc) for x in re.split(r'(?<!\\),', line)]
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

                self.doc.add_flow(self.flow_parser.parse(content, self.doc))
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
            elif name == 'annotation-lookup':
                self.doc.annotation_lookup = content
            elif name == 'smart-quotes':
                self.flow_parser.smart_quotes = content
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

        match = block_patterns['alt-blockquote-start'].match(line)
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

        match = block_patterns['variable-def'].match(line)
        if match is not None:
            return "VARIABLE-DEF", (source, match)

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


class Block(ABC):
    _attribute_serialization_xml = [('conditions', 'conditions'),
                                    ('ID', 'id'),
                                    ('name', 'name'),
                                    ('namespace', 'xmlns'),
                                    ('language_code', 'xml:lang')]

    _attribute_regurgitation = [('conditions', '?'),
                                ('ID', '*'),
                                ('name', '#'),
                                ('language_code', '!')]

    _attribute_serialization_html = [('conditions', 'data-conditions'),
                                     ('ID', 'id'),
                                     ('name', 'data-name'),
                                     ('language_code', 'lang')]
    html_tag = "div"

    def __init__(self, block_type, indent, attributes={}, content=None, citations=[], namespace=None):

        # Test for a valid block block_type. Must be valid XML block_type.
        try:
            x = etree.Element(block_type)
        except ValueError:
            raise SAMParserStructureError('Invalid block name "{0}"'.format(block_type))
        self.block_type = block_type
        self.namespace = namespace
        self.content = content
        self.indent = indent
        self.parent = None
        self.children = []
        self.citations = citations
        self.ID = None
        self.name = None
        self.conditions = []
        self.language_code = None
        for key, value in attributes.items():
            setattr(self, key, value)


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

    def find_all(self, find_function, **kwargs):
        result = []
        result.extend(find_function(self, **kwargs))
        for x in self.children:
            result.extend(x.find_all(find_function, **kwargs))
        return result

    def find_first(self, find_function, **kwargs):
        result = None
        result = find_function(self, **kwargs)
        if not result:
            for x in self.children:
                result = x.find_first(find_function, **kwargs)
                if result:
                    break
        return result

    def ancestor_at_indent(self, indent):
        x = self.parent
        while x.indent >= indent:
            x = x.parent
        return x

    def ancestors_and_self(self):
        ancestors_and_self=[]
        x=self
        while type(x.parent) is not DocStructure:
            ancestors_and_self.append(x)
            x=x.parent
        return ancestors_and_self

    def preceding_sibling(self):
        my_pos= [i for i, x in enumerate(self.parent.children) if x is self][0]
        if my_pos > 0:
            return self.parent.children[my_pos - 1]
        else:
            return None

    def following_sibling(self):
        my_pos= [i for i,x in enumerate(self.parent.children) if x is self][0]
        if my_pos == len(self.parent.children)-1:
            return None
        else:
            return self.parent.children[my_pos + 1]


    def object_by_id(self, id):
        """
        Get an object with a given id.
        :return: The object with the specified id or None.
        """
        if self.ID == id:
            return self
        else:
            for x in self.children:
                y = x.object_by_id(id)
                if y is not None:
                    return y
        return None

    def object_by_name(self, name):
        """
        Get an object with a given id.
        :return: The object with the specified id or None.
        """
        if self.name == name:
            return self
        else:
            for x in self.children:
                y = x.object_by_name(name)
                if y is not None:
                    return y
        return None

    @property
    def docstructure(self):
        return self.parent.docstructure

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield "%s:" % (self.block_type)
        yield from self._regurgitate_attributes(self._attribute_regurgitation)
        for y in [x for x in self.citations]:
            yield from y.regurgitate()

        if self.content:
            yield " %s" % (self.content)
        yield "\n"
        for z in [x for x in self.children]:
            yield from z.regurgitate()

    def _regurgitate_attributes(self, attribute_dict):
        for attr_name, symbol in attribute_dict:
            try:
                attr_value = getattr(self, attr_name)
                if attr_value:
                    if type(attr_value) is list:
                        for x in attr_value:
                            yield '(%s%s)' % (symbol, x)
                    else:
                        yield '(%s%s)' % (symbol, attr_value)
            except AttributeError:
                pass


    def _serialize_attributes(self, attribute_dict, duplicate=False):
        for attr_name, tag in attribute_dict:
            try:
                attr_value = getattr(self, attr_name)
                if attr_value:
                    if duplicate and attr_name == "ID":
                        yield ' data-copied-from-id="{1}"'.format(tag, escape_for_xml_attribute(attr_value)).encode('utf-8')
                    elif type(attr_value) is list:
                        yield ' {0}="'.format(tag).encode('utf-8')
                        yield ','.join([escape_for_xml_attribute(x) for x in attr_value]).encode('utf-8')
                        yield b'"'
                    else:
                        yield ' {0}="'.format(tag).encode('utf-8')
                        yield escape_for_xml_attribute(attr_value).encode('utf-8')
                        yield b'"'
            except AttributeError:
                pass

    def serialize_xml(self):

        yield '<{0}'.format(self.block_type).encode('utf-8')

        yield from self._serialize_attributes(self._attribute_serialization_xml)

        if not self.children and not self.content:
            SAM_parser_warning("Block with neither content not children detected. "
                               "Are you sure this is what you meant? "
                               "Perhaps this was intended as plain text:\n\n{0}".format(self))

        if self.children or self.citations:
            yield b">"

            if self.citations:
                for x in self.citations:
                    yield b'\n'
                    yield from x.serialize_xml()

            if self.content:
                yield b"\n<title>"
                yield from self.content.serialize_xml()
                yield "</title>\n".format(self.content).encode('utf-8')

            if type(self.children[0]) is not Flow:
                yield b"\n"

            for x in self.children:
                if x is not None:
                    yield from x.serialize_xml()
            yield "</{0}>\n".format(self.block_type).encode('utf-8')
        else:
            if self.content is None:
                yield b"/>\n"
            else:
                yield b'>'
                yield from self.content.serialize_xml()
                yield "</{0}>\n".format(self.block_type).encode('utf-8')

    def serialize_html(self, duplicate=False, variables=[]):
        yield '<{0} class="{1}"'.format(self.html_tag, self.block_type).encode('utf-8')

        yield from self._serialize_attributes(self._attribute_serialization_html, duplicate)

        yield b'>'

        if not self.children and not self.content:
            SAM_parser_warning("Block with neither content not children detected. "
                               "Are you sure this is what you meant? "
                               "Perhaps this was intended as plain text:\n\n{0}".format(self))

        if self.citations:
            for x in self.citations:
                yield b'\n'
                yield from x.serialize_html()

        if self.content:
            if self.children:
                title_depth = len(list(x for x in self.ancestors_and_self() if x.content))
                heading_level = title_depth if title_depth < 6 else 6
                yield '\n<h{0} class="title">'.format(heading_level).encode('utf-8')
                yield from self.content.serialize_html(duplicate, variables)
                yield "</h{0}>\n".format(heading_level).encode('utf-8')
            else:
                yield from self.content.serialize_html(duplicate, variables)

        if self.children:
            if type(self.children[0]) is not Flow:
                yield b"\n"

            for x in self.children:
                if x is not None:
                    yield from x.serialize_html(duplicate, variables)
        yield '</{0}>\n'.format(self.html_tag).encode('utf-8')

class BlockInsert(Block):
    def __init__(self, indent, reference_parts, attributes={}, citations=[], namespace=None):
        super().__init__(block_type='insert', indent=indent, attributes=attributes,
                         citations=citations, namespace=namespace)
        self.reference_parts = reference_parts

    def __str__(self):
        return ''.join(self.regurgitate())

    @property
    def idrefs(self):
        return [x[1] for x in self.reference_parts if x[0] == 'idref']

    def regurgitate(self):
        yield " " * int(self.indent)
        if self.reference_parts[0][0] in insert_reference_symbols:
            yield '>>>('
            yield '/'.join(['{0}{1}'.format(insert_reference_symbols[m], v) for m, v in self.reference_parts])
            yield ')'
        else:
            yield '>>>({0} {1})'.format(self.reference_parts[0][0], self.reference_parts[0][1])
        yield from self._regurgitate_attributes(self._attribute_regurgitation)
        yield '\n'
        for c in self.children:
            yield from c.regurgitate()
        yield '\n'

    def serialize_xml(self, attrs=None, payload=None):
        attributes = {}
        if self.reference_parts[0][0] in insert_reference_symbols:
            attributes[self.reference_parts[0][0]] = self.reference_parts[0][1]
        else:
            attributes['type'] = self.reference_parts[0][0]
            if self.docstructure.expand_relative_paths:
                attributes['item'] = urllib.parse.urljoin(self.docstructure.source_url, self.reference_parts[0][1])
            else:
                attributes['item'] = self.reference_parts[0][1]

        if self.conditions:
            attributes['conditions'] =','.join(self.conditions)
        if self.ID:
            attributes['id'] = self.ID
        if self.name:
            attributes['name'] = self.name
        if self.namespace is not None:
            if type(self.parent) is Root or self.namespace != self.parent.namespace:
                attributes['xmlns']= self.namespace
        if self.language_code:
            attributes['xml:lang']= self.language_code

        yield b'<insert'

        for key, value in sorted(attributes.items()):
            yield ' {0}="'.format(key).encode('utf-8')
            yield escape_for_xml_attribute(value).encode('utf-8')
            yield b'"'

        if len(self.reference_parts) > 1:
            yield b'><reference-elements>'
            for method, value in self.reference_parts:
                yield '<reference-element method="{0}" value="{1}"/>'.format(method, escape_for_xml(value)).encode('utf-8')
            yield b'</reference-elements>'

        if self.citations or self.children:
            yield b'>\n'
            for cit in self.citations:
                yield from cit.serialize_xml()

            for c in self.children:
                yield from c.serialize_xml()
            yield b'</insert>\n'
        else:
            yield b'/>\n'


    def serialize_html(self, duplicate=False, variables=[]):

        if len(self.reference_parts) == 1:
            reference_method, reference_value = self.reference_parts[0]

            if reference_method in insert_reference_symbols:
                if reference_method == 'variableref':
                    SAM_parser_warning('Inserting variables with block inserts is not supported in HTML output mode. '
                                       'Variable will be omitted from HTML output. At: {0}'.format(reference_value))
                elif reference_method == 'idref':
                    ob = self.docstructure.object_by_id(reference_value)
                    if ob:
                        variables = [x for x in self.children if type(x) is VariableDef]
                        yield from ob.serialize_html(duplicate=True, variables=variables)
                    else:
                        SAM_parser_warning('ID reference "{0}" could not be resolved. '
                                           'It will be omitted from HTML output. At: {1}'.format(reference_value, str(self).strip()))
                elif reference_method == 'nameref':
                    ob = self.docstructure.object_by_name(reference_value)
                    if ob:
                        variables = [x for x in self.children if type(x) is VariableDef]
                        yield from ob.serialize_html(duplicate=True, variables=variables)
                    else:
                        SAM_parser_warning(
                            'Name reference "{0}" could not be resolved. '
                            'It will be omitted from HTML output. At: {1}'.format(
                                reference_value, str(self).strip()))
                else:
                    SAM_parser_warning("HTML output mode does not support block inserts that use name or key references. "
                                       "They will be omitted. At: {0}".format(str(self).strip))

            else:
                yield b'<div class="insert"'
                if self.conditions:
                    yield ' data-conditions="{0}"'.format(','.join(self.conditions)).encode('utf-8')
                if self.ID:
                    yield ' id="{0}"'.format(self.ID).encode('utf-8')
                if self.name:
                    yield ' data-name="{0}"'.format(self.name).encode('utf-8')
                if self.namespace is not None:
                    SAM_parser_warning("Namespaces are ignored in HTML output mode.")
                if self.language_code:
                    yield ' lang="{0}"'.format(self.language_code).encode('utf-8')
                yield b">"
                if self.citations or self.children:

                    for cit in self.citations:
                        yield from cit.serialize_html()

                    for c in self.children:
                        yield from c.serialize_html()

                _, item_extension = os.path.splitext(reference_value)
                if reference_method in known_insert_types and item_extension.lower() in known_file_types:
                    yield '<object data="{0}"></object>'.format(reference_value).encode('utf-8')
                else:
                    if not reference_method in known_insert_types:
                        SAM_parser_warning('HTML output mode does not support the "{0}" insert type. '
                                           'They will be omitted. At: {1}'.format(reference_method, str(self).strip()))
                    if not item_extension.lower() in known_file_types:
                        SAM_parser_warning('HTML output mode does not support the "{0}" file type. '
                                           'They will be omitted.At: {1}'.format(item_extension, str(self).strip()))

                yield b'</div>\n'

        else:
            SAM_parser_warning("HTML output mode does not support block inserts that use compound identifiers. "
                           "They will be omitted. At: {0}".format(str(self).strip()))


class Codeblock(Block):
    _attribute_serialization_xml = [('conditions', 'conditions'),
                                    ('ID', 'id'),
                                    ('code_language', 'language'),
                                    ('name', 'name'),
                                    ('namespace', 'xmlns'),
                                    ('language_code', 'xml:lang')]

    _attribute_regurgitation = [('code_language', ''),
                                ('conditions', '?'),
                                ('ID', '*'),
                                ('name', '#'),
                                ('language_code', '!')]

    _attribute_serialization_html = [('conditions', 'data-conditions'),
                                     ('ID', 'id'),
                                     ('code_language', 'data-language'),
                                     ('name', 'data-name'),
                                     ('language_code', 'lang')]
    def __init__(self, indent, attributes={}, citations=[], namespace=None):
        self.code_language=None
        super().__init__(block_type='codeblock', indent=indent, attributes=attributes,
                         citations=citations, namespace=namespace)



    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield '```'
        yield from self._regurgitate_attributes(self._attribute_regurgitation)
        for x in self.citations:
            yield from x.regurgitate()
        yield '\n'
        for x in self.children:
            yield from x.regurgitate()
        yield '\n'

    def serialize_xml(self):
        yield b'<codeblock'
        yield from self._serialize_attributes(self._attribute_serialization_xml)

        if self.citations or self.children:
            yield b">\n"
            if self.citations:
                for x in self.citations:
                    yield from x.serialize_xml()
                    yield b'\n'
            if self.children:
                for x in self.children:
                    if x is not None:
                        yield from x.serialize_xml()
            yield b"</codeblock>\n"
        else:
            yield b'/>'

    def serialize_html(self, duplicate=False, variables=[]):
        yield b'<pre class="codeblock"'
        yield from self._serialize_attributes(self._attribute_serialization_html, duplicate)
        if self.citations or self.children:
            yield b">"

        if self.citations:
            for x in self.citations:
                yield from x.serialize_html()
                yield b'\n'
        if self.children:
            if self.code_language:
                yield '<code class="codeblock" data-language="{0}">'.format(self.code_language).encode('utf-8')
            for x in self.children:
                if x is not None:
                    yield from x.serialize_html(duplicate, variables)
            if self.code_language:
                yield b'</code>'
            yield b"</pre>\n"
        else:
            yield b'/>\n'


class Embedblock(Block):
    _attribute_serialization_xml = [('conditions', 'conditions'),
                                    ('encoding', 'encoding'),
                                    ('ID', 'id'),
                                    ('name', 'name'),
                                    ('namespace', 'xmlns'),
                                    ('language_code', 'xml:lang')]

    _attribute_serialization_html = [('conditions', 'data-conditions'),
                                    ('encoding', 'data-encoding'),
                                    ('ID', 'id'),
                                    ('name', 'data-name'),
                                    ('language_code', 'lang')]

    _attribute_regurgitation = [('encoding', '='),
                                ('conditions', '?'),
                                ('ID', '*'),
                                ('name', '#'),
                                ('language_code', '!')]
    # No _attribute_serialization_html because embedded data is not supported in HTML output mode

    def __init__(self, indent, attributes={}, citations=[], namespace=None):
        self.encoding=None
        super().__init__(block_type='embedblock', indent=indent, attributes=attributes,
                         citations=citations, namespace=namespace)

    def regurgitate(self):
        yield " " * int(self.indent)
        yield '```'
        yield from self._regurgitate_attributes(self._attribute_regurgitation)
        yield '\n'
        for x in self.children:
            yield from x.regurgitate()
        yield '\n'

    def serialize_xml(self):
        attrs = []
        yield b'<embedblock'

        yield from self._serialize_attributes(self._attribute_serialization_xml)
        if self.children:
            yield b">"

            if type(self.children[0]) is not Flow:
                yield b"\n"

            for x in self.children:
                if x is not None:
                    yield from x.serialize_xml()
            yield b"</embedblock>\n"
        else:
            yield b'/>\n'

    def serialize_html(self, duplicate=False, variables=[]):
        yield b'<div class="embed" hidden '

        yield from self._serialize_attributes(self._attribute_serialization_html)
        if self.children:
            yield b">"

            if type(self.children[0]) is not Flow:
                yield b"\n"

            for x in self.children:
                if x is not None:
                    yield from x.serialize_html()
            yield b"</div>\n"
        else:
            yield b'/>\n'


class Remark(Block):
    _attribute_serialization_xml = [('attribution', 'attribution'),
                                    ('conditions', 'conditions'),
                                    ('ID', 'id'),
                                    ('name', 'name'),
                                    ('namespace', 'xmlns'),
                                    ('language_code', 'xml:lang')]

    _attribute_regurgitation = [('attribution', ''),
                                ('conditions', '?'),
                                ('ID', '*'),
                                ('name', '#'),
                                ('language_code', '!')]

    _attribute_serialization_html = [('attribution', 'data-attribution'),
                                     ('conditions', 'data-conditions'),
                                     ('ID', 'id'),
                                     ('code_language', 'data-language'),
                                     ('name', 'data-name'),
                                     ('language_code', 'lang')]
    html_name='div'
    def __init__(self, indent, attributes={}, citations=[], namespace=None):
        super().__init__(block_type='remark', indent=indent, attributes=attributes,
                         citations=citations, namespace=namespace)
        self.attribution=attributes['attribution']

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield '!!!'
        yield from self._regurgitate_attributes(self._attribute_regurgitation)
        yield '\n'
        for x in self.children:
            yield from x.regurgitate()
        yield '\n'


class Grid(Block):
    html_tag = 'table'
    def __init__(self, indent, attributes={}, citations=[], namespace=None):
        super().__init__(block_type='grid', indent=indent, attributes=attributes,
                         citations=citations, namespace=namespace)

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield "+++"
        yield from self._regurgitate_attributes(self._attribute_regurgitation)
        yield "\n"
        for x in self.children:
            yield from x.regurgitate()
        yield '\n'

class Row(Block):
    html_tag = 'tr'
    def __init__(self, indent,  namespace=None):
        super().__init__(block_type='row', indent=indent, namespace=namespace)

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
    html_tag = 'td'

    def __init__(self, indent, namespace=None):
        super().__init__(block_type='cell', indent=indent, namespace=namespace)

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        for x in self.children:
            yield from x.regurgitate()

class Line(Block):
    html_tag = 'pre'
    def __init__(self, indent, attributes, content, citations=[], namespace=None):
        super().__init__(block_type='line', indent=indent, attributes=attributes, content=content,
                         citations=citations, namespace=namespace)

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent) + '|'
        yield from self._regurgitate_attributes(self._attribute_regurgitation)
        yield ' {0}\n'.format(str(self.content))

    def add(self, b):
        if b.indent > self.indent:
            raise SAMParserStructureError('A Line cannot have children.')
        else:
            self.parent.add(b)

class Fragment(Block):
    def __init__(self, indent, attributes={}, citations=[], namespace=None):
        super().__init__(block_type='fragment', indent=indent, attributes=attributes,
                         citations=citations, namespace=namespace)

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield '~~~'
        yield from self._regurgitate_attributes(self._attribute_regurgitation)
        yield '\n'
        for x in self.children:
            yield from x.regurgitate()
        yield '\n'

class Blockquote(Block):
    html_tag = "blockquote"
    def __init__(self, indent, attributes={}, citations=[], namespace=None):
        super().__init__(block_type='blockquote', indent=indent, attributes=attributes,
                         citations=citations, namespace=namespace)

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield '"""'
        yield from self._regurgitate_attributes(self._attribute_regurgitation)
        if self.citations:
            for x in self.citations:
                yield from x.regurgitate()
        yield '\n'
        for x in self.children:
            yield from x.regurgitate()
        yield '\n'

class RecordSet(Block):
    html_tag = "table"
    def __init__(self, block_type, field_names, indent, attributes={}, citations=[], namespace=None):
        super().__init__(block_type=block_type, indent=indent, attributes=attributes,
                         citations=citations, namespace=namespace)
        self.field_names = field_names

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield '{0}{1}::'.format(" " * int(self.indent), self.block_type)
        yield from self._regurgitate_attributes(self._attribute_regurgitation)
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
    _attribute_serialization_xml = [('namespace', 'xmlns')]

    _attribute_serialization_html = []

    def __init__(self, field_values, indent, namespace=None):
        super().__init__(block_type='record', indent=indent, attributes={}, citations=[], namespace=namespace)
        self.field_values = field_values

    def __str__(self):
        return

    def regurgitate(self):
        yield " " * int(self.indent)
        yield ', '.join([''.join(x.regurgitate()).replace(',', '\\,') for x in self.field_values]) + '\n'

    def serialize_xml(self):
        record = list(zip(self.parent.field_names, self.field_values))
        yield b'<record'
        yield from self._serialize_attributes(self._attribute_serialization_xml)
        yield b">\n"
        if record:
            for name, value in zip(self.parent.field_names, self.field_values):
                yield "<{0}>".format(name).encode('utf-8')
                yield from value.serialize_xml()
                yield "</{0}>\n".format(name).encode('utf-8')
        yield b"</record>\n"

    def serialize_html(self, duplicate=False, variables=[]):
        if not self.preceding_sibling():
            yield b'<thead class="recordset-header">\n<tr class="recordset-header-row">\n'
            for fn in self.parent.field_names:
                yield '<th class ="recordset-field" data-field-name="{0}"></th >\n'.format(fn).encode('utf-8')
            yield b'</tr>\n</thead>\n<tbody class="recordset-body">\n'

        record = list(zip(self.parent.field_names, self.field_values))
        yield b'<tr class="record"'
        yield from self._serialize_attributes(self._attribute_serialization_html, duplicate)
        yield b">\n"

        if record:
            for name, value in zip(self.parent.field_names, self.field_values):
                yield '<td class="record-field" data-field-name="{0}">'.format(name).encode('utf-8')
                yield from value.serialize_html()
                yield b"</td>\n"
        yield b"</tr>\n"

        if not self.following_sibling():
            yield b"</tbody>\n"


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
    html_tag = "ul"

    def __init__(self, indent, namespace=None):
        super().__init__('ul', indent=indent, content=None, namespace=namespace)

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
    html_tag = "ol"

    def __init__(self, indent, namespace=None):
        super().__init__('ol', indent=indent, namespace=namespace)

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
    html_tag = "li"
    @abstractmethod
    def __init__(self, block_type, indent, attributes={}, citations=[], namespace=None):
        super().__init__(block_type=block_type, indent=indent, attributes=attributes,
                         citations=citations, namespace=namespace)


class OrderedListItem(ListItem):
    def __init__(self, indent, attributes={}, citations=[],  namespace=None):
        super().__init__(block_type="li", indent=indent, attributes=attributes,
                         citations=citations, namespace=namespace)

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield '{0}.'.format(str(self.parent.children.index(self) + 1))
        yield from self._regurgitate_attributes(self._attribute_regurgitation)
        yield ' '
        for x in self.children:
            yield from x.regurgitate()
        yield "\n"


class UnorderedListItem(ListItem):
    def __init__(self, indent, attributes={}, citations=[],  namespace=None):
        super().__init__(block_type="li", indent = indent, attributes = attributes, namespace = namespace)

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield '*'
        yield from self._regurgitate_attributes(self._attribute_regurgitation)
        yield ' '
        for x in self.children:
            yield from x.regurgitate()

class LabeledListItem(ListItem):
    def __init__(self, indent, label, attributes={}, citations=[],  namespace=None):
        super().__init__(block_type="li", indent=indent, attributes=attributes,
                         citations=citations, namespace=namespace)
        self.label = label

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield '|{0}|'.format(self.label)
        yield from self._regurgitate_attributes(self._attribute_regurgitation)
        yield ' '
        for x in self.children:
            yield from x.regurgitate()

    def serialize_xml(self):
        yield '<{0}'.format(self.block_type).encode('utf-8')
        yield from self._serialize_attributes(self._attribute_serialization_xml)
        yield b">\n<label>"
        yield from self.label.serialize_xml()
        yield b"</label>\n"

        if self.citations:
            for x in self.citations:
                yield b'\n'
                yield from x.serialize_xml()

        if self.content:
            yield b"\n<title>"
            yield from self.content.serialize_xml()
            yield b"</title>\n".format(self.content)

        if type(self.children[0]) is not Flow:
            yield b"\n"

        for x in self.children:
            if x is not None:
                yield from x.serialize_xml()
        yield "</{0}>\n".format(self.block_type).encode('utf-8')


    def serialize_html(self, duplicate=False, variables=[]):
        yield b'<div class="ll.li"'
        yield from self._serialize_attributes(self._attribute_serialization_html, duplicate)
        yield b'>\n'
        yield b'<dt class="ll.li.label">'
        yield from self.label.serialize_html()
        yield b'</dt>\n<dd class="ll.li.item">'
        for x in self.children:
            if x is not None:
                yield from x.serialize_html(duplicate, variables)
        yield b"</dd>\n"
        yield b"</div>\n"


class LabeledList(List):
    html_tag = "dl"
    def __init__(self, indent, attributes={}, citations=[],  namespace=None):
        super().__init__('ll', indent=indent, attributes=attributes,  namespace=namespace)

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
    html_tag = "p"
    def __init__(self, indent,  namespace=None):
        super().__init__(block_type='p', indent=indent, namespace=namespace)

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
            yield "\n\n"
        elif self.parent.children.index(self) == 0:
            for x in self.children:
                yield from x.regurgitate()
            yield "\n\n"
        else:
            parent_indent = self.parent.indent
            parent_leader = len(str(self.parent.parent.children.index(self.parent)+1))+2


            yield " " * (parent_indent + parent_leader)
            for x in self.children:
                yield from x.regurgitate()
            yield "\n\n"

    def _add_child(self, b):
        if type(b) is Flow:
            b.parent = self
            self.children.append(b)
        elif self.parent.block_type == 'li' and b.block_type in ['ol', 'ul', 'comment']:
            b.parent = self.parent
            self.parent.children.append(b)
        else:
            raise SAMParserStructureError(
                'A paragraph cannot have block children.')


class Comment(Block):
    def __init__(self, content, indent):
        super().__init__(block_type='comment', content=content, indent=indent,namespace=None)

    def _add_child(self, b):
        if self.parent.block_type == 'li' and b.block_type in ['ol', 'ul', 'comment']:
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
        yield '<!-- {0} -->\n'.format(self.content.replace('--', '-\-')).encode('utf-8')

    def serialize_html(self, duplicate=False, variables=[]):
        yield '<!-- {0} -->\n'.format(self.content.replace('--', '-\-')).encode('utf-8')


class VariableDef(Block):
    def __init__(self, variable_name, value, indent=0):
        super().__init__(block_type=variable_name, content=value, indent=indent)

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield "{0}${1}={2}\n".format(" " * int(self.indent), self.block_type, self.content)

    def serialize_xml(self):
        yield '<variable name="{0}">'.format(self.block_type).encode('utf-8')
        yield from self.content.serialize_xml()
        yield b"</variable>\n"

    def serialize_html(self, duplicate=False, variables=[]):
        yield '<div class="variable" data-name="{0}" hidden>'.format(self.block_type, self.content).encode('utf-8')
        yield from self.content.serialize_html()
        yield b"</div>\n"

class Root(Block):
    def __init__(self, doc):
        super().__init__(block_type='root', attributes={}, content=None, indent=-1)
        self.parent = doc
        self.children = []

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        for x in self.children:
            yield from x.regurgitate()

    def serialize_xml(self):
        yield b'<?xml version="1.0" encoding="UTF-8"?>\n'
        for x in self.children:
            yield from x.serialize_xml()

    def serialize_html(self, duplicate=False, variables=[]):
        yield b'<!DOCTYPE html>\n'
        try:
            title = [x.content for x in self.children if type(x) is Block][0]
        except IndexError:
            title=None
        try:
            lang = [x.language_code for x in self.children if x.language_code is not None][0]
        except IndexError:
            lang=None
        yield b'<html'
        if lang:
            yield ' lang="{}"'.format(lang).encode('utf-8')
        yield b'>\n<head>\n'
        if title:
            yield '<title>{0}</title>\n'.format(title).encode('utf-8')
        yield b'<meta charset = "UTF-8">\n'
        if self.parent.css:
            for c in self.parent.css:
                yield '<link rel="stylesheet" href="{0}">\n'.format(c).encode('utf-8')
        if self.parent.javascript:
            for j in self.parent.javascript:
                yield '<script src="js/all.min.js"></script>\n'.format(j).encode('utf-8')
        yield b'</head>\n<body>\n'
        for x in self.children:
            yield from x.serialize_html(duplicate, variables)
        yield b'</body>\n</html>'

    def _add_child(self, b):
        # This is a test to catch the creation of a second root-level block.
        # It is not foolproof because people can add to the children list without
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


block_pattern_replacements = {
    'comment': '#',
    'remark-start': '!',
    'declaration': '!',
    'block-start': ':',
    'codeblock-start': '`',
    'grid-start': '+',
    'blockquote-start': '"',
    'alt-blockquote-start': "'",
    'fragment-start': '~',
    'line-start': '|',
    'record-start': ':',
    'num-list-item': '.',
    'labeled-list-item': '|',
    'block-insert': '>',
    'include': '<',
    'variable-def': '$'
}


class Flow():
    def __init__(self):
        self.children=[]
        self.parent = None
        self.ID = None
        self.name = None

    def find_all(self, find_function, **kwargs):
        result = []
        x=find_function(self, **kwargs)
        result.extend(x)
        for x in self.children:
            if hasattr(x, 'find_all'):
                result.extend(x.find_all(find_function, **kwargs))
        return result

    def find_first(self, find_function, **kwargs):
        result = None
        result = find_function(self, **kwargs)
        if not result:
            for x in self.children:
                if hasattr(x, 'find_first'):
                    result = x.find_first(find_function, **kwargs)
                    if result:
                        break
        return result



    def object_by_id(self, id):
        """
        Get an object with a given id.
        :return: The object with the specified id or None.
        """
        if self.ID == id:
            return self
        else:
            for x in [y for y in self.children if isinstance(y, Span)]:
                y = x.object_by_id(id)
                if y is not None:
                    return y
        return None

    def object_by_name(self, name):
        """
        Get an object with a given id.
        :return: The object with the specified id or None.
        """
        if self.name == name:
            return self
        else:
            for x in [y for y in self.children if isinstance(y, Span)]:
                y = x.object_by_name(name)
                if y is not None:
                    return y
        return None


    def __str__(self):
        return ''.join(self.regurgitate())

    @property
    def docstructure(self):
        return self.parent.docstructure

    def regurgitate(self):

        for i, x in enumerate(self.children):
            if hasattr(x, 'regurgitate'):
                yield from x.regurgitate()
            elif i == 0:
                # if block_patterns['block-start'].match(x) is not None:
                #     yield escape_for_sam(x).replace(':', '\\:', 1)
                # elif block_patterns['num-list-item'].match(x) is not None:
                #     yield escape_for_sam(x).replace('.', '\\.', 1)
                # Don't need to do this for bulleted list items as escape_for_sam takes care of them

                for key, value in block_pattern_replacements.items():
                    if block_patterns[key].match(x) is not None:
                        yield escape_for_sam(x).replace(value, '\\'+value, 1)
                        break
                else:
                    yield escape_for_sam(x)
            else:
                yield escape_for_sam(x)


    def append(self, thing):
        if type(thing) is not str:
            thing.parent=self
        if isinstance(thing, Annotation):
            if type(self.children[-1]) is Phrase:
                self.children[-1].append(thing)
            else:
                self.children.append(thing)

        elif type(thing) is Citation:
            try:
                if type(self.children[-1]) is Phrase:
                    self.children[-1].citations.append(thing)
                else:
                    self.children.append(thing)
            except IndexError:
                self.children.append(thing)

        elif not thing == '':
            self.children.append(thing)

    def find_last_annotation(self, text, mode):

        try:
            return annotation_lookup_modes[mode](self, text)
        except KeyError:
            raise SAMParserError("Unknown annotation lookup mode: " + mode)

    def serialize_xml(self):
        for x in self.children:
            if type(x) is str:
                yield escape_for_xml(x).encode('utf-8')
            else:
                yield from x.serialize_xml()

    def serialize_html(self, duplicate=False, variables=[]):
        for x in self.children:
            if type(x) is str:
                yield escape_for_xml(x).encode('utf-8')
            else:
                yield from x.serialize_html(duplicate, variables)


# Annotation lookup modes. Third parties can add additional lookup modes
# by extending the annotation_lookup_modes dictionary with new annotation
# matching algorithms.

def _annotation_lookup_case_sensitive(flow, text):
    for i in reversed(flow):
        if type(i) is Phrase:
            if i.annotated and i.text == text:
                return i.global_annotations
    return None


def _annotation_lookup_case_insensitive(flow, text):
    for i in reversed(flow.children):
        if type(i) is Phrase:
            if i.annotated and i.text.lower() == text.lower():
                return i.global_annotations
    return None


def _annotation_lookup_off(flow, text):
    return None



annotation_lookup_modes = {
    'on': _annotation_lookup_case_insensitive,
    'off': _annotation_lookup_off,
    'case sensitive': _annotation_lookup_case_sensitive,
    'case insensitive': _annotation_lookup_case_insensitive
}



class Pre(Flow):
    html_tag = "pre"
    def __init__(self, text_block):
        super().__init__()
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
            yield escape_for_xml(x).encode('utf-8')

    def serialize_html(self, duplicate=False, variables=[]):
        for x in self.lines:
            yield escape_for_xml(x).encode('utf-8')

class DocStructure:
    """
    Class to define a document structure object. The SAM source document is parsed 
    to create a document structure object. The document structured object can then
    be queried directly by programs or can output an XML representation of the 
    SAM document. 
    
    The document structure object is a tree of objects starting with a Root object. 
    Each part of the SAM concrete syntax, such as Grids, RecordSets, and Lines has
    its own object type. Names blocks are represented by a generic Block object.

    :param expand_relative_paths: Tells the parser to expand relative paths when serializing the document. Note
    that this must be set before calling the parse() method. Changing it after the parse method is called will
    not effect the serialization.

    """
    def __init__(self, source_url, ):
        self.source_url = source_url
        self.root = Root(self)
        self.current_block = self.root
        self.default_namespace = None
        self.annotation_lookup = "case insensitive"
        self.ids = []
        self.idrefs = []
        self.parent = None
        # Used by HTML output mode
        self.css = None
        self.javascript = None
        self._xml_serialization = None
        self._etree = None
        self.expand_relative_paths = False

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield from self.root.regurgitate()

    @property
    def xml(self):
        if not self._xml_serialization:
            self._xml_serialization = io.BytesIO(b''.join(self.serialize_xml()))
        return self._xml_serialization

    @property
    def etree(self):
        if not self._etree:
            self._etree = etree.parse(self.xml)
        return self._etree

    @property
    def docstructure(self):
        return self

    def find_all(self, find_function, **kwargs):
        return self.root.find_all(find_function, **kwargs)

    def find_first(self, find_function, **kwargs):
        return self.root.find_first(find_function, **kwargs)

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
                context.append(context_block.block_type)
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
                if block.block_type in ancestor_name:
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

    def object_by_id(self, id):
        """
        Get an object by ID.
        :return: An object with the corresponding ID or none.
        """
        return self.root.object_by_id(id)

    def object_by_name(self, name):
        """
        Get an object by name.
        :return: An object with the corresponding name or none.
        """
        return self.root.object_by_name(name)



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
        if block.ID is not None:
            if block.ID in self.ids:
                raise SAMParserStructureError('Duplicate ID found "{0}".'.format(block.ID))
            self.ids.append(block.ID)

        # Check IDs from included files
        try:
            overlapping_ids = set(block.ids) & set(self.ids)
            if overlapping_ids:
                raise SAMParserStructureError('Duplicate ID found "{0}".'.format(', '.join(overlapping_ids)))
            self.ids.extend(block.ids)
            self.idrefs.extend(block.idrefs)
        except (TypeError, AttributeError):
            pass

        if block.namespace is None and self.default_namespace is not None:
            block.namespace = self.default_namespace

        block.parent=self.current_block

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
        ids = [f.ID for f in flow.children if hasattr(f, 'ID') and f.ID is not None]
        for i in ids:
            if i in self.ids:
                raise SAMParserStructureError('Duplicate ID found "{0}".'.format(ids[0]))
            self.ids.append(i)

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

    def serialize_html(self):
        yield from self.root.serialize_html()

    def serialize_xml(self):
        yield from self.root.serialize_xml()

class Include(Block):
    def __init__(self, doc, content, href, indent):
        super().__init__(block_type="include", indent=indent, attributes={}, content = content, namespace=None)
        self.children=doc.root.children
        for i in doc.root.children:
            i.parent = self

        self.ids = doc.ids
        self.href= href

    def __str__(self):
        return ''.join(self.regurgitate())

    def regurgitate(self):
        yield " " * int(self.indent)
        yield "<<<(" + self.content + ")\n\n"

    def serialize_xml(self):
        for x in self.children:
            yield from x.serialize_xml()

    def serialize_html(self, duplicate=False, variables=[]):
        for x in self.children:
            yield from x.serialize_html()



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

        self.smart_quotes = 'off'
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
        elif char == ">":
            return "INLINE-INSERT", para
        elif char == "&":
            return "CHARACTER-ENTITY", para
        else:
            if self.smart_quotes != 'off':
                try:
                    for r, sub in smart_quote_sets[self.smart_quotes].items():
                        match = r.match(para.para, para.currentCharNumber)
                        if match is not None:
                            self.current_string += sub
                            if len(match.group(0)) > 1:
                                para.advance(len(match.group(0)) - 1)
                            return "PARA", para
                except KeyError:
                    raise SAMParserError("Unknown smart quotes set specified: {0}".format(self.smart_quotes))

            self.current_string += char
            return "PARA", para

    def _phrase_start(self, para):
        match = flow_patterns['phrase'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            text = unescape(match.group("text"))
            if self.smart_quotes != 'off':
                text = multi_replace(text, smart_quote_sets[self.smart_quotes])
            p = Phrase(text)
            self.flow.append(p)
            para.advance(len(match.group(0)))

            if flow_patterns['annotation'].match(para.rest_of_para):
                return "ANNOTATION-START", para
            elif flow_patterns['citation'].match(para.rest_of_para):
                return "CITATION-START", para
            else:
                para.retreat(1)
                return "PHRASE-END", para
        else:
            self.current_string += '{'
            return "PARA", para

    def _phrase_end(self, para):
        phrase = self.flow.children[-1]
        if not phrase.annotated:
            # If there is a phrase with no annotation, look back
            # to see if it has been annotated already, and if so, copy the
            # closest preceding annotation.
            # First look back in the current flow
            # (which is not part of the doc structure yet).
            previous = self.flow.find_last_annotation(phrase.text, self.doc.annotation_lookup)
            if previous is None:
                previous = self.doc.find_last_annotation(phrase.text)
            if previous is not None:
                for a in previous:
                    if a not in phrase.annotations:
                        phrase.add_looked_up_annotation(a)
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
        phrase = self.flow.children[-1]
        if not isinstance(phrase, (Phrase, Code)):
            raise SAMParserError("A {0} cannot have an annotation. At:\n{1}".format(type(phrase).__name__, match.group(0)))
        if match:
            annotation_type = match.group('type')
            is_local = False
            cancel = False
            flag = match.group('flag')
            if flag:
                if flag == '+':
                    is_local = True
                elif flag =='-':
                    cancel = True
                else:
                    raise SAMParserStructureError("Unknown annotation flag '{0}'. At: {1}".format(flag, match.group(0)))


            # Check for link shortcut
            if urlparse(annotation_type, None).scheme is not None:
                specifically = annotation_type
                annotation_type = 'link'
            else:
                specifically = match.group('specifically') if match.group('specifically') is not None else None
            namespace = match.group('namespace').strip() if match.group('namespace') is not None else None

            if cancel and (specifically or namespace):
                raise SAMParserStructureError("A cancel attribute cannot have a specifically or namespace attribute.")

            if annotation_type[0] == '=':
                if type(phrase) is Code:
                    phrase.encoding = unescape(annotation_type[1:])
                else:
                    raise SAMParserStructureError("Only code can have an embed attribute. At: {0}".format(match.group(0)))
            elif annotation_type[0] == '!':
                phrase.language_code = unescape(annotation_type[1:])
            elif annotation_type[0] == '*':
                phrase.ID = unescape(annotation_type[1:])
            elif annotation_type[0] == '#':
                phrase.name = unescape(annotation_type[1:])
            elif annotation_type[0] == '?':
                phrase.conditions.append(unescape(annotation_type[1:]))
            else:
                if type(self.flow.children[-1]) is Code:
                    phrase.code_language = unescape(annotation_type)
                else:
                    phrase.add_annotation(Annotation(annotation_type, unescape(specifically), namespace, is_local, cancel))
            para.advance(len(match.group(0)))
            if flow_patterns['annotation'].match(para.rest_of_para):
                return "ANNOTATION-START", para
            elif flow_patterns['citation'].match(para.rest_of_para):
                return "CITATION-START", para
            else:
                para.retreat(1)
                if type(phrase) is Phrase:
                    return "PHRASE-END", para
                else:
                    return "PARA", para
        else:
            self.current_string += '('
            return "PARA", para

    def _citation_start(self, para):
        match = flow_patterns['citation'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            self.flow.append(Citation(*parse_citation(match.group('citation'))))
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
            p.annotations.append(Annotation('bold', local=True))
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
            p.annotations.append(Annotation('italic', local=True))
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

    def _inline_insert(self, para):
        match = flow_patterns['inline-insert'].match(para.rest_of_para)
        if match:
            self.flow.append(self.current_string)
            self.current_string = ''
            if match.group("attributes"):
                attributes, citations = parse_attributes(match.group("attributes"))
            else:
                attributes, citations = {},[]
            self.flow.append(InlineInsert(parse_insert(match.group("insert")), attributes, citations))
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

class Span(ABC):
    _attribute_serialization_xml = [('conditions', 'conditions'),
                                   ('ID', 'id'),
                                   ('name', 'name'),
                                   ('namespace', 'xmlns'),
                                   ('language_code', 'xml:lang')]

    _attribute_regurgitation = [('conditions', '?'),
                               ('ID', '*'),
                               ('name', '#'),
                               ('language_code', '!')]

    _attribute_serialization_html = [('conditions', 'data-conditions'),
                                    ('ID', 'id'),
                                    ('name', 'data-name'),
                                    ('language_code', 'lang')]

    def __str__(self):
        return ''.join(self.regurgitate())

    def find_all(self, find_function, **kwargs):
        return list(find_function(self, **kwargs))

    def find_first(self, find_function, **kwargs):
        return find_function(self, **kwargs)

    def object_by_id(self, id):
        """
        Get an object with a given id.
        :return: The object with the specified id or None.
        """
        try:
            if self.ID == id:
                return self
            else:
                return None
        except AttributeError:
            return None

    def object_by_name(self, name):
        """
        Get an object with a given name.
        :return: The object with the specified name or None.
        """
        try:
            if self.name == name:
                return self
            else:
                return None
        except AttributeError:
            return None


    def _regurgitate_attributes(self, attribute_dict):
        for attr_name, symbol in attribute_dict:
            try:
                attr_value = getattr(self, attr_name)
                if attr_value:
                    if type(attr_value) is list:
                        for x in attr_value:
                            yield '(%s%s)' % (symbol, x)
                    else:
                        yield '(%s%s)' % (symbol, attr_value)
            except AttributeError:
                pass

    def _serialize_attributes(self, attribute_dict, duplicate = False):
        for attr_name, tag in attribute_dict:
            try:
                attr_value = getattr(self, attr_name)
                if attr_value:
                    if duplicate and attr_name == "ID":
                        yield b' data-copied-from-ID="'
                        yield escape_for_xml_attribute(attr_value).encode('utf-8')
                        yield b'"'
                    elif type(attr_value) is list:
                        yield ' {0}="'.format(tag).encode('utf-8')
                        yield ','.join([escape_for_xml_attribute(x) for x in attr_value]).encode('utf-8')
                        yield b'"'
                    else:
                        yield ' {0}="'.format(tag).encode('utf-8')
                        yield escape_for_xml_attribute(attr_value).encode('utf-8')
                        yield b'"'
            except AttributeError:
                pass

class Phrase(Span):

    def __init__(self, text):
        self.text = text
        self.annotations = []
        self.citations = []
        self.parent=None
        self.language_code = None
        self.ID = None
        self.name = None
        self.conditions = []


    def regurgitate(self):
        yield u'{{{0:s}}}'.format(escape_for_sam(self.text))
        for x in self.annotations:
            yield from x.regurgitate()
        for x in self.citations:
            yield from x.regurgitate()
        yield from self._regurgitate_attributes(self._attribute_regurgitation)

    @property
    def annotated(self):
        return len(self.global_annotations) > 0

    @property
    def global_annotations(self):
        return [x for x in self.annotations if not (x.local or x.cancel)]

    def add_looked_up_annotation(self, annotation):
        cancel_types = [x.type for x in self.annotations if x.cancel]
        if annotation.type in cancel_types and not annotation.local:
            pass
        else:
            self.annotations.append(annotation)


    def add_annotation(self, annotation):
        cancel_types = [x.type for x in self.annotations if x.cancel]

        if annotation.cancel and self.annotated:
            raise SAMParserStructureError("A cancel annotation cannot occur on a phrase that is annotated directly.")

        if not (annotation.cancel or annotation.local) and cancel_types:
            raise SAMParserStructureError("A cancel annotation cannot occur on a phrase that is annotated directly.")

        self.annotations.append(annotation)


    def serialize_xml(self):
        yield b'<phrase'
        yield from self._serialize_attributes(self._attribute_serialization_xml)
        yield b'>'

        #Nest annotations for serialization
        if self.annotations:
            ann, *rest = self.annotations
            yield from ann.serialize_xml(rest, escape_for_xml(self.text))
        else:
            yield escape_for_xml(self.text).encode('utf-8')
        for i in self.citations:
            yield from i.serialize_xml()
        yield b'</phrase>'

    def serialize_html(self, duplicate=False, variables=[]):
        yield b'<span class="phrase"'
        yield from self._serialize_attributes(self._attribute_serialization_html, duplicate)
        yield b'>'

        link_made = False
        for cit in self.citations:
            if len(cit.reference_parts) == 1 and cit.reference_parts[0][0] == 'idref':
                if link_made:
                    SAM_parser_warning('HTML output mode does not support multiple citations by ID on a phrase. '
                                       'Only the first ID was made into a link. At: {0}'.format(str(self).strip()))
                else:
                    link_made = True
                    yield '<a href="#{0}">'.format(cit.reference_parts[0][1]).encode('utf-8')
            else:
                yield from cit.serialize_html()

        #Nest annotations for serialization
        if self.annotations:
            ann, *rest = self.annotations
            yield from ann.serialize_html(rest, escape_for_xml(self.text))
        else:
            yield escape_for_xml(self.text).encode('utf-8')
        if link_made:
            yield b'</a>'
        yield b'</span>'


    # def append(self, thing):
    #     if not self.child:
    #         self.child = thing
    #     else:
    #         self.child.append(thing)

class Code(Phrase):
    attribute_serialization_xml = [('encoding', 'encoding'),
                                   ('conditions', 'conditions'),
                                   ('ID', 'id'),
                                   ('code_language', 'language'),
                                   ('name', 'name'),
                                   ('namespace', 'xmlns'),
                                   ('language_code', 'xml:lang')]

    attribute_regurgitation = [('encoding', '='),
                               ('code_language', ''),
                               ('conditions', '?'),
                               ('ID', '*'),
                               ('name', '#'),
                               ('language_code', '!')]

    attribute_serialization_html = [('conditions', 'data-conditions'),
                                    ('encoding', 'data-encoding'),
                                    ('ID', 'id'),
                                    ('code_language', 'data-language'),
                                    ('name', 'data-name'),
                                    ('language_code', 'lang')]

    def __init__(self, text):
        super().__init__(text)

    def __str__(self):
        return ''.join(self.regurgitate())

    def __setattr__(self, name, value):
        if name=='encoding' and value is not None:
            #Change this to an Embed if it has an encoding attribute
            self.__class__ = Embed
        Phrase.__setattr__(self, name, value)
        try:
            if self.encoding and self.code_language:
                raise SAMParserError(
                    "Code cannot have both a code_langauge attribute and an embed attribute. At: {0}".format(self).strip())
        except AttributeError:
            pass

    def regurgitate(self):
        yield '`{0}`'.format(escape_for_sam_code(self.text))
        yield from self._regurgitate_attributes(self.attribute_regurgitation)
        for x in self.annotations:
            yield from x.regurgitate()

    def serialize_xml(self):
        yield b'<code'
        yield from self._serialize_attributes(self.attribute_serialization_xml)
        yield b'>'
        yield escape_for_xml(self.text).encode('utf-8')
        yield b'</code>'

    def serialize_html(self, duplicate=False, variables=[]):
        yield b'<code class="code"'
        yield from self._serialize_attributes(self.attribute_serialization_html)
        yield b'>'
        yield escape_for_xml(self.text).encode('utf-8')
        yield b'</code>'

    def append(self, thing):
        raise SAMParserStructureError("Inline code cannot have typed annotations.")

class Embed(Code):

    def __init__(self, text):
        super().__init__(text)

    def serialize_xml(self):
        yield b'<embed'
        yield from self._serialize_attributes(self.attribute_serialization_xml)
        yield b'>'
        yield escape_for_xml(self.text).encode('utf-8')
        yield b'</embed>'

    def serialize_html(self, duplicate=False, variables=[]):
        yield b'<span class="embed" hidden'
        yield from self._serialize_attributes(self.attribute_serialization_html)
        yield b'>'
        yield escape_for_xml(self.text).encode('utf-8')
        yield b'</span>'

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


class Annotation:
    def __init__(self, type, specifically='', namespace='', local=False, cancel=False):
        self.type = type.strip()
        self.specifically = specifically
        self.namespace = namespace
        self.local = local
        self.cancel = cancel

    def __str__(self):
        return ''.join(self.regurgitate())

    def __eq__(self, other):
        return [self.type, self.specifically, self.namespace] == [other.type, other.specifically, other.namespace]

    def __ne__(self, other):
        return [self.type, self.specifically, self.namespace] != [other.type, other.specifically, other.namespace]

    def regurgitate(self):
        yield '({0}'.format(self.type)
        yield (' "{0}"'.format(self.specifically.replace('"','\\"')) if self.specifically else '')
        yield (' ({0})'.format(self.namespace) if self.namespace else '')
        yield ')'

    def serialize_xml(self, annotations=None, payload=None):
        if self.cancel:
            # don't serialize the cancel annotation
            if annotations:
                anns, *rest = annotations
                yield from anns.serialize_xml(rest, payload)
            elif payload:
                yield payload.encode('utf-8')
            else:
                pass
        else:
            yield b'<annotation'
            if self.type:
                yield ' type="{0}"'.format(self.type).encode('utf-8')
            if self.specifically:
                yield b' specifically="'
                yield escape_for_xml_attribute(self.specifically).encode('utf-8')
                yield b'"'
            if self.namespace:
                yield ' namespace="{0}"'.format(self.namespace).encode('utf-8')

            #Nest annotations for serialization
            if annotations:
                anns, *rest = annotations
                yield b'>'
                yield from anns.serialize_xml(rest, payload)
                yield b'</annotation>'
            elif payload:
                yield b'>'
                yield payload.encode('utf-8')
                yield b'</annotation>'
            else:
                yield b'/>'

    def serialize_html(self, annotations=None, payload=None):

        def recurse():
            #Nest annotations for serialization
            if annotations:
                anns, *rest = annotations
                yield from anns.serialize_html(rest, payload)
            elif payload:
                yield payload.encode('utf-8')

        if self.type == 'link':
            yield '<a href={0} class="link">'.format(escape_for_xml_attribute(self.specifically)).encode('utf-8')
            yield from recurse()
            yield b'</a>'
        elif self.type == 'bold' :
            yield '<b class="bold">'.format(escape_for_xml_attribute(self.specifically)).encode('utf-8')
            yield from recurse()
            yield b'</b>'
        elif self.type == 'italic':
            yield '<i class="italic">'.format(escape_for_xml_attribute(self.specifically)).encode('utf-8')
            yield from recurse()
            yield b'</i>'
        elif self.cancel:
            # Don't serialize the cancel annotation.
            yield from recurse()
        else:
            yield b'<span'
            if self.type:
                yield ' class="annotation" data-annotation-type="{0}"'.format(self.type).encode('utf-8')
            if self.specifically:
                yield ' data-specifically="{0}"'.format(escape_for_xml_attribute(self.specifically)).encode('utf-8')
            if self.namespace:
                yield ' data-namespace="{0}"'.format(self.namespace).encode('utf-8')
            yield b'>'
            yield from recurse()
            yield b'</span>'

    def append(self, thing):
        if not self.child:
            self.child = thing
        else:
            self.child.append(thing)


class Citation(Span):
    def __init__(self, reference_parts, reference_extra):
        self.reference_parts = reference_parts
        self.reference_extra = None if reference_extra is None else reference_extra.strip()
        self.local=True
        self.child = None
        self.parent=None

    def __str__(self):
        return ''.join(self.regurgitate())

    @property
    def idrefs(self):
        return [x[1] for x in self.reference_parts if x[0] == 'idref']

    def regurgitate(self):
        yield '['
        yield '/'.join(['{0}{1}'.format(citation_reference_symbols[m], v) for m, v in self.reference_parts])
        if self.reference_extra:
            yield ' {0}'.format(self.reference_extra)
        yield ']'

    def serialize_xml(self):
        has_children= False
        yield b'<citation'

        if len(self.reference_parts) > 1:
            has_children = True
            yield b'><reference-elements>'
            for method, value in self.reference_parts:
                yield '<reference-element method="{0}" value="'.format(method).encode('utf-8')
                yield escape_for_xml(value).encode('utf-8')
                yield b'"/>'
            yield b'</reference-elements>'
            if self.reference_extra:
                has_children = True
                yield escape_for_xml(self.reference_extra).encode('utf-8')

        if len(self.reference_parts) == 1:
            if self.reference_parts[0][0] != 'value':
                yield ' {0}="'.format(self.reference_parts[0][0]).encode('utf-8')
                yield escape_for_xml_attribute(self.reference_parts[0][1]).encode('utf-8')
                yield b'"'
                if self.reference_extra:
                    has_children = True
                    yield b'>'
                    yield escape_for_xml(self.reference_extra).encode('utf-8')
            else:
                has_children = True
                yield b'>'
                yield escape_for_xml(self.reference_parts[0][1]).encode('utf-8')

        if has_children:
            yield b'</citation>'
        else:
            yield b'/>'

    def serialize_html(self, duplicate=False, variables=[]):

        if len(self.reference_parts) == 1:
            citation_method, citation_value = self.reference_parts[0]

            if citation_method == 'value':
                yield '<cite>{0}</cite>'.format(citation_value).encode('utf-8')
            else:
                SAM_parser_warning("HTML output mode does not support citations by reference except for citations "
                                   "by ID that are attached to a phrase. "
                                   "They will be omitted. At: " + str(self).strip())
        else:
            SAM_parser_warning("HTML output mode does not support reference citations using compound identifiers. "
                               "They will be omitted. At: " + str(self).strip())

    def append(self, thing):
        if not self.child:
            self.child = thing
        else:
            self.child.append(thing)


class InlineInsert(Span):
    def __init__(self, reference_parts, attributes={}, citations=[]):
        self.reference_parts = reference_parts
        self.citations = citations
        self.parent=None
        self.namespace = None
        self.ID = None
        self.name = None
        self.conditions = []
        self.language_code = None
        for key, value in attributes.items():
            setattr(self, key, value)

    @property
    def docstructure(self):
        return self.parent.docstructure

    def __str__(self):
        return ''.join(self.regurgitate())

    @property
    def idrefs(self):
        return [x[1] for x in self.reference_parts if x[0] == 'idref']

    def regurgitate(self):
        if self.reference_parts[0][0] in insert_reference_symbols:
            yield '>('
            yield '/'.join(['{0}{1}'.format(insert_reference_symbols[m], v) for m, v in self.reference_parts])
            yield ')'
        else:
            yield '>({0} {1})'.format(self.reference_parts[0][0], self.reference_parts[0][1])
        yield from self._regurgitate_attributes(self._attribute_regurgitation)

    def serialize_xml(self):
        attributes = {}
        if len(self.reference_parts) == 1:
            if self.reference_parts[0][0] in insert_reference_symbols:
                attributes[self.reference_parts[0][0]] = self.reference_parts[0][1]
            else:
                attributes['type'] = self.reference_parts[0][0]
                if self.docstructure.expand_relative_paths:
                    attributes['item'] = urllib.parse.urljoin(self.docstructure.source_url, self.reference_parts[0][1])
                else:
                    attributes['item'] = self.reference_parts[0][1]

        if self.conditions:
            attributes['conditions'] =','.join(self.conditions)
        if self.ID:
            attributes['id'] = self.ID
        if self.name:
            attributes['name'] = self.name
        if self.namespace is not None:
            if type(self.parent) is Root or self.namespace != self.parent.namespace:
                attributes['xmlns']= self.namespace
        if self.language_code:
            attributes['xml:lang']= self.language_code

        yield b'<inline-insert'

        for key, value in sorted(attributes.items()):
            yield ' {0}="'.format(key).encode('utf-8')
            yield escape_for_xml_attribute(value).encode('utf-8')
            yield b'"'

        if len(self.reference_parts) > 1:
            yield b'><reference-elements>'
            for method, value in self.reference_parts:
                yield '<reference-element method="{0}" '.format(method).encode('utf-8')
                yield escape_for_xml(value).encode('utf-8')
                yield b'"/>'
            yield b'</reference-elements>'

        if self.citations:
            yield b'>'
            for c in self.citations:
                yield from c.serialize_xml()
            yield b'</inline-insert>'
        else:
            yield b'/>'

    def serialize_html(self, duplicate=False, variables=[]):

        if len(self.reference_parts) == 1:
            reference_method, reference_value = self.reference_parts[0]

            if reference_method in insert_reference_symbols:
                if reference_method == 'variableref':
                    variable_content = get_variable_def(reference_value, self, variables)
                    if variable_content:
                        yield from variable_content.serialize_html()
                    else:
                        SAM_parser_warning('Variable reference "{0}" could not be resolved. '
                                           'It will be omitted from HTML output.'.format(self.item))
                elif reference_method == 'idref':
                    ob = self.docstructure.object_by_id(reference_value)
                    if ob:
                        yield from ob.serialize_html(duplicate=True)
                    else:
                        SAM_parser_warning(
                            'ID reference "{0}" could not be resolved. It will be omitted from HTML output. At: {1}'.format(
                                reference_value, str(self).strip()))
                elif reference_method == 'nameref':
                    ob = self.docstructure.object_by_name(reference_value)
                    if ob:
                        yield from ob.serialize_html(duplicate=True)
                    else:
                        SAM_parser_warning(
                            'Name reference "{0}" could not be resolved. It will be omitted from HTML output. At: {1}'.format(
                                reference_value, str(self).strip()))
                else:
                    SAM_parser_warning("HTML output mode does not support inline inserts that use key references. "
                                       "They will be omitted. At: {0}".format(self))

            else:
                yield b'<span class="insert"'
                if self.conditions:
                    yield ' data-conditions="{0}"'.format(','.join(self.conditions)).encode('utf-8')
                if self.ID:
                    if duplicate:
                        yield ' data-copied-from-id="{0}"'.format(self.ID).encode('utf-8')
                    else:
                        yield ' id="{0}"'.format(self.ID).encode('utf-8')
                if self.name:
                    yield ' data-name="{0}"'.format(self.name).encode('utf-8')
                if self.namespace is not None:
                    SAM_parser_warning("Namespaces are ignored in HTML output mode.")
                if self.language_code:
                    yield ' lang="{0}"'.format(self.language_code).encode('utf-8')
                yield b">"
                if self.citations:

                    for cit in self.citations:
                        yield from cit.serialize_html()

                _, item_extension = os.path.splitext(reference_value)
                if reference_method in known_insert_types and item_extension.lower() in known_file_types:
                    yield '<object data="{0}"></object>'.format(reference_value).encode('utf-8')
                else:
                    if not reference_method in known_insert_types:
                        SAM_parser_warning('HTML output mode does not support the "{0}" insert type. '
                                           'They will be omitted.'.format(reference_method))
                    if not item_extension.lower() in known_file_types:
                        SAM_parser_warning('HTML output mode does not support the "{0}" file type. '
                                           'They will be omitted.'.format(item_extension))

                yield b'</span>\n'

        else:
            SAM_parser_warning("HTML output mode does not support inline inserts that use compound identifiers. "
                           "They will be omitted. At: {0}".format(str(self).strip()))


class SAMParserError(Exception):
    """
    Raised if the SAM parser encounters an error.
    """
class SAMParserFileError:
    """
    Raised if the SAM parser cannot find a file.
    """

class SAMXSLTError(Exception):
    """
    Raised if the SAM parser encounters an error.
    """

class SAMParserStructureError(Exception):
    """
    Raised if the DocStructure encounters an invalid structure.
    """

def parse_attributes(attributes_string, flagged="?#*!", unflagged=None):
    attributes = {}
    citations =[]
    attributes_list=[]
    citations_list=[]

    re_all = re.compile(r'(\((?P<att>.*?(?<!\\))\))|(\[((?P<cit>.*?(?<!\\))\])|(?P<bad>.))')

    for x in re_all.finditer(attributes_string.rstrip()):
        if x.group('att') is not None:
            attributes_list.append(x.group('att').strip())
        elif x.group("cit") is not None:
            citations_list.append(x.group("cit").strip())
        else:
            raise SAMParserStructureError('Unrecognized character "{0}" found in attributes list.'.format(
                x.group('bad')))

    unflagged_attributes = [x for x in attributes_list if not (x[0] in '?#*!=')]
    if unflagged_attributes:
        if unflagged is None:
            raise SAMParserStructureError("Unexpected attribute(s). Found: {0}".format(', '.join(unflagged_attributes)))
        elif len(unflagged_attributes) > 1:
            raise SAMParserStructureError("More than one {0} attribute specified. Found: {1}".format(
                unflagged, ', '.join(unflagged_attributes)))
        else:
            attributes[unflagged] = unescape(unflagged_attributes[0])
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
        raise SAMParserStructureError('Language tag not allowed in this context. Found: !{0}'.format(
            ', !'.join(language_tag)))
    if len(language_tag) > 1:
        raise SAMParserStructureError('More than one language tag specified. Found: !{0}'.format(
            ", !".join(language_tag)))
    embed = [x[1:] for x in attributes_list if x[0] == '=']
    if embed and not '=' in flagged:
        raise SAMParserStructureError('Embeded encoding specification not allowed in this context. Found: !{0}'.format(
            ', !'.join(embed)))
    if len(embed) > 1:
        raise SAMParserStructureError('More than one embedded encoding specified. Found: {0}.',format(", ".join(embed)))
    conditions = [unescape(x[1:]) for x in attributes_list if x[0] == '?']
    if embed:
        attributes["encoding"] = unescape(embed[0])
    if language_tag:
        attributes["language_code"] = unescape(language_tag[0])
    if ids:
        attributes["ID"] = unescape(ids[0])
    if names:
        attributes["name"] = unescape(names[0])
    if conditions:
        attributes["conditions"] = conditions

    for c in citations_list:
        citations.append(Citation(*parse_citation(c)))

    return attributes, citations

def parse_citation(c):
    reference_parts=[]
    extra = None
    if c[0] in citation_reference_methods:
        try:
            ref, extra = c.split(None, 1)
        except ValueError:
            ref = c
        for x in ref.split('/'):
            if x[0] not in citation_reference_methods:
                raise SAMParserError('Invalid compound identifier at: {0}'.format(c))
            reference_method = citation_reference_methods[x[0]]
            reference_value = x[1:]
            reference_parts.append((reference_method, reference_value))
    else:
        reference_parts.append(('value', c))

    return reference_parts, extra


def parse_insert(insert):
    reference_parts=[]
    if insert[0] in insert_reference_methods:
        if len(insert.split()) > 1:
            raise SAMParserError("Extraneous characters in insert at: {0}".format(insert))
        for x in insert.split('/'):
            if x[0] not in insert_reference_methods:
                raise SAMParserError('Invalid compound identifier at: {0}'.format(c))
            reference_method = insert_reference_methods[x[0]]
            reference_value = x[1:]
            reference_parts.append((reference_method, reference_value))
    else:
        try:
            reference_method, reference_value = insert.split(None, 1)
        except ValueError:
            raise SAMParserStructureError("Insert item not specified in: {0}".format(insert))
        # strip unnecessary quotes from insert item
        reference_value = re.sub(r'^(["\'])|(["\'])$', '', reference_value.strip())
        reference_parts.append((reference_method, reference_value))
    if len(reference_value.split())>1:
        raise SAMParserStructureError("Extraneous content in insert: {0}".format(insert))
    return reference_parts


def escape_for_sam(s):
    t = dict(zip([ord('['), ord('{'), ord('&'), ord('\\'), ord('*'), ord('_'), ord('`')],
                 ['\\[', '\\{', '\\&', '\\\\', '\\*', '\\_', '\\`']))
    try:
        return s.translate(t)
    except AttributeError:
        return s

def escape_for_sam_code(s):
    try:
        return s.translate({ord('`'): '``'})
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
    for r, sub in subs.items():
        string= r.sub(sub, string)
    return string


def SAM_parser_warning(warning):
    print("SAM parser warning: {0}".format(warning), file=sys.stderr)

def SAM_parser_info(info, blank_line = False):
    if blank_line:
        print('\n', file=sys.stderr)
    print("SAM parser information: {0}".format(info), file=sys.stderr)

def SAM_parser_debug(message):
    print("SAM parser debug: {0}".format(message), file=sys.stderr)


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

def get_variable_def(name, context, before_variables=[], after_variables=[]):
    """
    Get a variable definition with a given name.
    :return: The closest definition to the given context up the tree
    """
    if before_variables:
        for x in before_variables:
            if x.block_type == name:
                return x.content
    if context.parent and type(context.parent) is not DocStructure:
        starting_point = context.parent.children.index(context)
        for x in reversed(context.parent.children[:starting_point]):
            if type(x) is VariableDef and x.block_type == name:
                return x.content
        return get_variable_def(name, context.parent)
    if after_variables:
        for x in after_variables:
            if x.block_type == name:
                return x.content
    return None


if __name__ == "__main__":

    import glob
    import os.path

    transformed = None
    parser_error_count = 0
    xsd_error_count = 0
    xslt_error_count = 0
    samParser = SamParser()

    def get_input_list():
        inputfiles=glob.glob(args.infile)
        if not inputfiles:
            raise SAMParserError("No input file(s) found.")
        return inputfiles

    def write_output(input_file, default_output_extension, source_func, mode="binary"):
        """
        Calculates the name of the output file using the input file name
        and the output file extension, then writes the output file by
        calling the output generating function passed to it.

        The output directory name is read from the arguments.

        :param input_file: The name of the input file.
        :param default_output_extension: The extension to be used on the output file unless overridden on the command line.
        :param source_func: The output function to call.
        :return: The name of the output file (in case the caller needs to read it).
        """
        if not args.outputextension:
            output_extension = default_output_extension
        else:
            if args.outputextension[0] == '.':
                output_extension = args.outputextension
            else:
                output_extension = '.' + args.outputextension

        if args.outdir:
            output_file = os.path.join(args.outdir,
                                      os.path.splitext(
                                          os.path.basename(input_file))[0] + output_extension)
        else:
            output_file = args.outfile

        if mode=="binary":
            if output_file:
                os.makedirs(os.path.dirname(output_file), exist_ok=True)
                with open(output_file, "wb") as outf:
                    for i in source_func():
                        outf.write(i)
            else:
                for i in source_func():
                    sys.stdout.buffer.write(i.decode("utf-8"))
        else:
            if output_file:
                os.makedirs(os.path.dirname(output_file), exist_ok=True)
                with open(output_file, "wt", encoding="utf-8") as outf:
                    for i in source_func():
                        outf.write(i)
            else:
                for i in source_func():
                    sys.stdout.buffer.write(i)

        return output_file


    def xml_output():
        global xsd_error_count, parser_error_count, xslt_error_count

        for inputfile in get_input_list():

            try:
                samParser.parse_file(inputfile)
                outputfile = write_output(inputfile, '.xml', samParser.doc.serialize_xml)

                if args.xsd:
                    SAM_parser_info("Validating XML output using " + args.xsd)
                    xmlschema = etree.XMLSchema(file=args.xsd)
                    try:
                        xmlschema.assertValid(samParser.doc.etree)
                    except etree.DocumentInvalid as e:
                        print('XSD SCHEMA ERROR {0} in {1}'.format(str(e), outputfile), file=sys.stderr)
                        xsd_error_count += 1
                    else:
                        SAM_parser_info("Validation successful.")

                if args.xslt:
                    if not (args.transformedoutputfile or args.transformedoutputdir):
                        raise SAMParserError(
                            "A transformed output file or directory must be specified if an XSLT file is specified.")

                    if args.transformedoutputdir:
                        transformedfile = os.path.join(args.transformedoutputdir, os.path.splitext(
                            os.path.basename(inputfile))[0] + args.transformedextension)
                    else:
                        transformedfile = args.transformedoutputfile
                    try:
                        transformer = etree.XSLT(etree.parse(args.xslt))
                        try:
                            if samParser.doc.expand_relative_paths:
                                # We can use the internal tree because all paths have been expanded.
                                transformed = transformer(samParser.doc.etree)
                            else: # May be local paths so have to parse from disk.
                                transformed = transformer(etree.parse(outputfile))
                        except etree.XSLTError as e:
                            print('XSLT TRANSFORMER ERROR {0} in {1}'.format(str(e), outputfile), file=sys.stderr)
                            if transformer.error_log:
                                SAM_parser_warning("Messages from the XSLT transformation of {0}:".format(outputfile))
                                for entry in transformer.error_log:
                                    print('message from line %s, col %s: %s' % (
                                        entry.line, entry.column, entry.message), file=sys.stderr)
                                    print('domain: %s (%d)' % (entry.domain_name, entry.domain), file=sys.stderr)
                                    print('type: %s (%d)' % (entry.type_name, entry.type), file=sys.stderr)
                                    print('level: %s (%d)' % (entry.level_name, entry.level), file=sys.stderr)
                            raise SAMXSLTError(e)
                        # For XSLT warnings that don't cause an exception
                        if transformer.error_log:
                            SAM_parser_warning("Messages from the XSLT transformation:")
                            for entry in transformer.error_log:
                                print('message from line %s, col %s: %s' % (
                                    entry.line, entry.column, entry.message), file=sys.stderr)
                                print('domain: %s (%d)' % (entry.domain_name, entry.domain), file=sys.stderr)
                                print('type: %s (%d)' % (entry.type_name, entry.type), file=sys.stderr)
                                print('level: %s (%d)' % (entry.level_name, entry.level), file=sys.stderr)
                        if transformedfile:
                            with open(transformedfile, "wb") as tf:
                                tf.write(str(transformed).encode(encoding='utf-8'))

                    except FileNotFoundError as e:
                        raise SAMParserError(e.strerror + ' ' + e.filename)


            except SAMParserError as e:
                sys.stderr.write('SAM parser ERROR: ' + str(e) + "\n")
                parser_error_count += 1
                continue

            except SAMXSLTError as e:
                sys.stderr.write('XSLT ERROR: ' + str(e) + "\n")
                xslt_error_count += 1
                continue


    def html_output():
        global parser_error_count
        for inputfile in get_input_list():
            try:
                samParser = SamParser()
                samParser.parse_file(inputfile)
                samParser.doc.css = args.css
                samParser.doc.javascript = args.javascript
                write_output(inputfile, '.html', samParser.doc.serialize_html)
            except SAMParserError as e:
                sys.stderr.write('SAM parser ERROR: ' + str(e) + "\n")
                parser_error_count += 1
                continue


    def regurgitate_output():
        global parser_error_count
        for inputfile in get_input_list():
            try:
                samParser = SamParser()
                samParser.parse_file(inputfile)
                write_output(inputfile, '.sam', samParser.doc.regurgitate, mode='text')
            except SAMParserError as e:
                sys.stderr.write('SAM parser ERROR: ' + str(e) + "\n")
                parser_error_count += 1
                continue

    # Main parser
    argparser = argparse.ArgumentParser()
    subparsers = argparser.add_subparsers(title="subcommands")

    # I/O parser
    io_parser = argparse.ArgumentParser(add_help=False)
    io_parser.add_argument("infile", help="the SAM file to be parsed")
    io_parser.add_argument("-smartquotes", "-sq",
                           help="the path to a file containing smartquote patterns and substitutions")
    io_parser.add_argument("-expandrelativepaths", '-xrp', action="store_true", help="expand relative paths on serialization")
    outputgroup = io_parser.add_mutually_exclusive_group()
    outputgroup.add_argument("-outfile", "-o", help="the name of the output file")
    outputgroup.add_argument("-outdir", "-od", help="the name of output directory")
    io_parser.add_argument("-outputextension", "-oext", nargs='?')


    # XML sub
    xml_parser = subparsers.add_parser("xml", parents=[io_parser])
    xml_parser.add_argument("-xslt", "-x", help="name of xslt file for postprocessing output")
    xml_parser.add_argument("-xsd", help="Specify an XSD schema to validate generated XML")
    transform_output_group = xml_parser.add_mutually_exclusive_group()
    transform_output_group.add_argument("-transformedoutputfile", "-to",
                                   help="Name of the output file for output transformed using -xslt")
    transform_output_group.add_argument("-transformedoutputdir", "-tod",
                                   help="Name of the output directory for output transformed using -xslt")
    xml_parser.add_argument("-transformedextension", "-toext", nargs='?', const='.xml', default='.xml')
    xml_parser.set_defaults(func=xml_output)

    # Regurgitate
    regurgitate_parser = subparsers.add_parser("regurgitate", parents=[io_parser])
    regurgitate_parser.set_defaults(func=regurgitate_output)

    # HTML
    html_parser = subparsers.add_parser("html", parents=[io_parser])
    html_parser.add_argument("-css",  nargs='+', help="Add a call to a CSS stylesheet in HTML output mode.")
    html_parser.add_argument("-javascript", nargs='+', help="Add a call to a script in HTML output mode.")
    html_parser.set_defaults(func=html_output)

    args = argparser.parse_args()
    
    # If no subcommand was chosen
    if not hasattr(args, "func"):
        argparser.print_help()
        sys.exit(1)

    if args.infile == args.outfile:
        raise SAMParserError('Input and output files cannot have the same name.')

    if args.expandrelativepaths:
        samParser.expand_relative_paths = True

    if args.smartquotes:
        with open(args.smartquotes, encoding="utf8") as sqf:
            try:
                substitution_sets = etree.parse(sqf)
            except etree.XMLSyntaxError as e:
                raise SAMParserError("Smart quotes file {0} contains XML error {1}: " + str(e))

            for x in substitution_sets.iterfind(".//subset"):
                subs = {}
                for y in x.iterfind("sub"):
                    r = re.compile(y.find("pattern").text)
                    subs.update({r: y.find("replace").text})
                smart_quote_sets.update({x.find("name").text: subs})

    args.func()

    error_count_total = parser_error_count + xsd_error_count + xslt_error_count
    if error_count_total == 0:
        print ("Process completed with 0 errors.", file=sys.stderr)
        sys.exit(0)
    else:
        print('Process completed with {0} errors.\n'
              '{1} SAM parser errors.\n{2} XSD schema errors.\n{3} XSLT Errors.'.format(error_count_total,
                                                                                        parser_error_count,
                                                                                        xsd_error_count,
                                                                                        xslt_error_count
                                                                                        ), file=sys.stderr)
        if error_count_total > 0:
            sys.exit(1)
