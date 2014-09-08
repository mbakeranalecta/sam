from statemachine import StateMachine
import re
from collections import OrderedDict


class SamParser:
    def __init__(self):

        self.stateMachine = StateMachine()
        self.stateMachine.add_state("NEW", self.__new_file)
        self.stateMachine.add_state("SAM", self.__sam)
        self.stateMachine.add_state("BLOCK", self.__block)
        self.stateMachine.add_state("CODEBLOCK-START", self.__codeblockStart)
        self.stateMachine.add_state("CODEBLOCK", self.__codeblock)
        self.stateMachine.add_state("PARAGRAPH-START", self.__paragraphStart)
        self.stateMachine.add_state("PARAGRAPH", self.__paragraph)
        self.stateMachine.add_state("RECORD-START", self.__recordStart)
        self.stateMachine.add_state("RECORD", self.__record)
        self.stateMachine.add_state("LIST-START", self.__listStart)
        self.stateMachine.add_state("LIST", self.__listContinue)
        self.stateMachine.add_state("NUM-LIST-START", self.__numListStart)
        self.stateMachine.add_state("NUM-LIST", self.__numListContinue)
        self.stateMachine.add_state("END", None, end_state=1)
        self.stateMachine.set_start("NEW")

        self.docStructure = DocStructure()

        self.patterns = {
                    'comment': re.compile('\s*#.*'),
                    'block-start': re.compile('(\s*)([a-zA-Z0-9-_]+):(.*)'),
                    'codeblock-start': re.compile('(\s*)```(.*)'),
                    'codeblock-end': re.compile('(\s*)```\s*$'),
                    'paragraph-start': re.compile('\w*'),
                    'blank-line': re.compile('^\s*$'),
                    'record-start': re.compile('\s*[a-zA-Z0-9-_]+::(.*)'),
                    'annotation': re.compile('(\[[^\[]+\]\([^\(]+\))'),
                    'annotation-split': re.compile('\[([^\[]+)\]\(([^\(]+)\)'),
                    'list-item': re.compile('(\s*)\*\s(.*)'),
                    'num-list-item': re.compile('(\s*)[0-9]+\.\s(.*)')
                }


    def parse (self, source):
        self.source = Source(source)
        self.stateMachine.run(self.source)

    def __new_file(self, source):
        line = source.nextLine
        if line[:4] == 'sam:':
            print('<?xml version="1.0" encoding="UTF-8"?>')
            return "SAM", source
        else:
            raise Exception("Not a SAM file!")

    def __block(self, source):
        line = source.currentLine
        match = self.patterns['block-start'].match(line)
        localIndent = len(match.group(1))
        localElement = Element(match.group(2))
        localContent = match.group(3).strip()

        if localIndent > self.docStructure.currentIndent:
            if self.docStructure.currentElement:
                print()

            self.docStructure.pushElement(localElement, localIndent)

            if localContent[:1] == ':':
                return "RECORD-START", source
            else:
                print("<" + self.docStructure.currentElement.name + ">", end="")
                print(localContent, end="")
                return "SAM", source
        else:
            while localIndent <= self.docStructure.currentIndent:
                print(self.docStructure.popElement)
            print(self.docStructure.pushElement(localElement, localIndent))
            return "SAM", source


    def __codeblockStart(self, source):
        line = source.currentLine
        match = self.patterns['codeblock-start'].match(line)
        language = match.group(2).strip()
        print(self.docStructure.pushElement(Element('codeblock',{'language' : language}), 0) + '<![CDATA[')
        return "CODEBLOCK", source


    def __codeblock(self, source):
        line = source.nextLine
        if self.patterns['codeblock-end'].match(line):
            print("]]>" + self.docStructure.popElement)
            return "SAM", source
        else:
            print(line, end='')
            return "CODEBLOCK", source


    def __paragraphStart(self, source):
        line = source.currentLine
        print(self.docStructure.pushElement(Element('p'), 0), end="")
        self.docStructure.paragraphStart(line)
        return "PARAGRAPH", source


    def __paragraph(self, source):
        line = source.nextLine
        if self.patterns['blank-line'].match(line):
            self.__processParagraph(self.docStructure.currentParagraph)
            print(self.docStructure.popElement)
            return "SAM", source
        else:
            self.docStructure.paragraphAppend(line)
            return "PARAGRAPH", source

    def __listStart(self, source):
        line = source.currentLine
        print(self.docStructure.pushElement(Element('ul'), 0))
        match = self.patterns['list-item'].match(line)
        print('<li>' + match.group(2).strip() + '</li>')
        return "LIST", source


    def __listContinue(self, source):
        line = source.nextLine
        if self.patterns['blank-line'].match(line):
            print(self.docStructure.popElement)
            return "SAM", source
        elif self.patterns['list-item'].match(line):
            match = self.patterns['list-item'].match(line)
            print('<li>' + match.group(2).strip() + '</li>')
            return "LIST", source
        else:
            raise Exception("Broken list at line " + str(source.currentLineNumber) + " " + source.filename)

    def __numListStart(self, source):
        line = source.currentLine
        print(self.docStructure.pushElement(Element('ol'), 0))
        match = self.patterns['num-list-item'].match(line)
        print('<li>' + match.group(2).strip() + '</li>')
        return "NUM-LIST", source


    def __numListContinue(self, source):
        line = source.nextLine
        if self.patterns['blank-line'].match(line):
            print(self.docStructure.popElement)
            return "SAM", source
        elif self.patterns['num-list-item'].match(line):
            match = self.patterns['num-list-item'].match(line)
            print('<li>' + match.group(2).strip() + '</li>')
            return "NUM-LIST", source
        else:
            raise Exception("Broken num list at line " + str(source.currentLineNumber) + " " + source.filename)


    def __recordStart(self, source):
        line = source.currentLine
        fieldNames = [x.strip() for x in self.patterns['record-start'].match(line).group(1).split(',')]
        self.docStructure.fields = fieldNames
        return "RECORD", source


    def __record(self, source):
        line = source.nextLine
        if self.patterns['blank-line'].match(line):
            self.docStructure.popElement
            return "SAM", source
        else:
            print("<" + self.docStructure.currentElement.name + ">")
            fieldValues = [x.strip() for x in line.split(',')]
            record = OrderedDict(zip(self.docStructure.fields, fieldValues))
            for key, value in record.items():
                print('<' + key + '>' + value + '</' + key + '>')
            print("</" + self.docStructure.currentElement.name + ">")
            return "RECORD", source


    def __sam(self, source):
        line = source.nextLine
        if line == "":
            while True:
                try:
                    print(self.docStructure.popElement)
                except IndexError:
                    break
            return "END", source
        elif self.patterns['comment'].match(line):
            print('<!--' + line.strip() + '-->')
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

    def __processParagraph (self, paragraph):
        parts = self.patterns['annotation'].split(paragraph)
        for part in parts:
            p = self.patterns['annotation-split'].match(part)
            if p is None:
                print(part, end="")
            else:
                print('<annotation type="' + p.group(2).strip() + '">' + p.group(1) + '</annotation>', end="")



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
        self.filename = filename
        self.sourceFile = open(filename, encoding='utf-8')
        self.currentLine = None
        self.currentLineNumber = 0

    @property
    def nextLine(self):
        self.currentLine = self.sourceFile.readline()
        self.currentLineNumber += 1
        return self.currentLine


if __name__ == "__main__":
    samParser = SamParser()
    samParser.parse('test1.sam')




