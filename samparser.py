from statemachine import StateMachine
import re
from collections import OrderedDict


patterns = {
    'comment': re.compile('\s*#.*'),
    'block-start': re.compile('(\s*)([a-zA-Z0-9-_]+):(.*)'),
    'codeblock-start': re.compile('(\s*)```(.*)'),
    'codeblock-end': re.compile('(\s*)```\s*$'),
    'paragraph-start': re.compile('\w*'),
    'blank-line': re.compile('^\s*$'),
    'record-start': re.compile('\s*[a-zA-Z0-9-_]+::(.*)'),
    'annotation': re.compile('(\[[^\[]+\]\([^\(]+\))'),
    'annotation-split': re.compile('\[([^\[]+)\]\(([^\(]+)\)'),
    'list-item': re.compile('(\s*)\*\s(.*)')
}


class Element:
    def __init__(self, name, attributes={}):
        self.name = name
        assert isinstance(attributes, dict)
        self.attributes = attributes


class DocStructure:
    def __init__(self):
        self.elements = []
        self.fields = []
        self.currentParagraph = ""

    def pushElement(self, element, indent):
        self.elements.append({'element': element, 'indent': indent})
        tag = "<" + element.name
        for key, value in element.attributes.items():
            tag += " " + key + '="' + value + '"'
        tag += '>'
        return tag

    @property
    def popElement(self):
        tag = "</" + self.elements[-1]['element'].name + ">"
        self.elements.pop()
        return tag

    @property
    def currentElement(self):
        if not self.elements:
            return None
        else:
            return self.elements[-1]['element']

    @property
    def currentIndent(self):
        if not self.elements:
            return -1
        else:
            return self.elements[-1]["indent"]

    def paragraphStart(self, line):
        self.currentParagraph = line.strip()

    def paragraphAppend(self, line):
        self.currentParagraph += " " + line.strip()

class Source:
    def __init__(self, filename):
        """

        :param filename: The filename of the source to parse.
        """
        self.sourceFile = open(filename, encoding='utf-8')
        self.currentLine = None

    @property
    def nextLine(self):
        self.currentLine = self.sourceFile.readline()
        return self.currentLine


def new_file(source):
    line = source.nextLine
    if line[:4] == 'sam:':
        print('<?xml version="1.0" encoding="UTF-8"?>')
        return "SAM", source
    else:
        raise Exception("Not a SAM file!")


def block(source):
    line = source.currentLine
    match = patterns['block-start'].match(line)
    localIndent = len(match.group(1))
    localElement = Element(match.group(2))
    localContent = match.group(3).strip()

    if localIndent > docStructure.currentIndent:
        if docStructure.currentElement:
            print()

        docStructure.pushElement(localElement, localIndent)

        if localContent[:1] == ':':
            return "RECORD-START", source
        else:
            print("<" + docStructure.currentElement.name + ">", end="")
            print(localContent, end="")
            return "SAM", source
    else:
        while localIndent <= docStructure.currentIndent:
            print(docStructure.popElement)
        print(docStructure.pushElement(localElement, localIndent))
        return "SAM", source


def codeblockStart(source):
    line = source.currentLine
    match = patterns['codeblock-start'].match(line)
    language = match.group(2).strip()
    print(docStructure.pushElement(Element('codeblock',{'language' : language}), 0) + '<![CDATA[')
    return "CODEBLOCK", source


def codeblock(source):
    line = source.nextLine
    if patterns['codeblock-end'].match(line):
        print("]]>" + docStructure.popElement)
        return "SAM", source
    else:
        print(line, end='')
        return "CODEBLOCK", source


def paragraphStart(source):
    line = source.currentLine
    print(docStructure.pushElement(Element('p'), 0), end="")
    docStructure.paragraphStart(line)
    return "PARAGRAPH", source


def paragraph(source):
    line = source.nextLine
    if patterns['blank-line'].match(line):
        processParagraph(docStructure.currentParagraph)
        print(docStructure.popElement)
        return "SAM", source
    else:
        docStructure.paragraphAppend(line)
        return "PARAGRAPH", source

def listStart(source):
    line = source.currentLine
    print(docStructure.pushElement(Element('ul'), 0))
    match = patterns['list-item'].match(line)
    print('<li>' + match.group(2).strip() + '</li>')
    return "LIST", source


def listContinue(source):
    line = source.nextLine
    if patterns['blank-line'].match(line):
        print(docStructure.popElement)
        return "SAM", source
    elif patterns['list-item'].match(line):
        match = patterns['list-item'].match(line)
        print('<li>' + match.group(2).strip() + '</li>')
        return "LIST", source
    else:
        raise Exception("Broken list")


def recordStart(source):
    line = source.currentLine
    fieldNames = [x.strip() for x in patterns['record-start'].match(line).group(1).split(',')]
    docStructure.fields = fieldNames
    return "RECORD", source


def record(source):
    line = source.nextLine
    if patterns['blank-line'].match(line):
        docStructure.popElement
        return "SAM", source
    else:
        print("<" + docStructure.currentElement.name + ">")
        fieldValues = [x.strip() for x in line.split(',')]
        record = OrderedDict(zip(docStructure.fields, fieldValues))
        for key, value in record.items():
            print('<' + key + '>' + value + '</' + key + '>')
        print("</" + docStructure.currentElement.name + ">")
        return "RECORD", source


def sam(source):
    line = source.nextLine
    if line == "":
        while True:
            try:
                print(docStructure.popElement)
            except IndexError:
                break
        return "END", source
    elif patterns['comment'].match(line):
        print('<!--' + line.strip() + '-->')
        return "SAM", source
    elif patterns['block-start'].match(line):
        return "BLOCK", source
    elif patterns['blank-line'].match(line):
        print()
        return "SAM", source
    elif patterns['codeblock-start'].match(line):
        return "CODEBLOCK-START", source
    elif patterns['list-item'].match(line):
        return "LIST-START", source
    elif patterns['paragraph-start'].match(line):
        return "PARAGRAPH-START", source
    elif line != "":
        print('*NOT MATCHED* ' + line, end='')
        return "SAM", source
    else:
        raise Exception("I'm confused")

def processParagraph (paragraph):
    parts = patterns['annotation'].split(paragraph)
    for part in parts:
        p = patterns['annotation-split'].match(part)
        if p is None:
            print(part, end="")
        else:
            print('<annotation type="' + p.group(2).strip() + '">' + p.group(1) + '</annotation>', end="")


if __name__ == "__main__":
    samSource = Source('test1.sam')
    docStructure = DocStructure()
    stateMachine = StateMachine()
    stateMachine.add_state("NEW", new_file)
    stateMachine.add_state("SAM", sam)
    stateMachine.add_state("BLOCK", block)
    stateMachine.add_state("CODEBLOCK-START", codeblockStart)
    stateMachine.add_state("CODEBLOCK", codeblock)
    stateMachine.add_state("PARAGRAPH-START", paragraphStart)
    stateMachine.add_state("PARAGRAPH", paragraph)
    stateMachine.add_state("RECORD-START", recordStart)
    stateMachine.add_state("RECORD", record)
    stateMachine.add_state("LIST-START", listStart)
    stateMachine.add_state("LIST", listContinue)
    stateMachine.add_state("END", None, end_state=1)
    stateMachine.set_start("NEW")

    stateMachine.run(samSource)


