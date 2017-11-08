sam
===

Semantic Authoring Markdown

XML was designed to be human readable, but not human writable. Graphical editors help, though they have their issues
(like trying to find the right insertion point to add permitted elements). But graphical editors have a problem: when 
they hide the tags, they also hide the structure.

Semantic Authoring Markdown brings the ideas behind Markdown -- a natural syntax for writing HTML documents -- to 
structured writing. It creates a syntax that captures structure, like XML, but is easy to write in a text editor
-- like markdown.

### NOTE

The SAM Language is still being defined and both the language itself and the way it is serialized and represented internally by the parser is subject to change. I hope to stabilize the language definition soon.

SAM Parser
=========

SAM Parser is an application to process SAM files into an equivalent XML representation which 
you can then further process in any desired form of output. 

SAM Parser allows to specify an XSLT 1.0 stylesheet to post-process the output XML into a 
desired output format. In particular, it only allows for processing individual SAM files to
individual output files. It does not support any kind of assembly or linking of multiple source files. 
This facility is not intended to meet all output needs, but it 
provides a simple way to create basic outputs. 

SAM Parser is a Python 3 program that requires the regex and libxml libraries that are not 
distributed with the default Python distribution. If you don't already have a Python 3 install, 
the easiest way to get one with the required libraries installed is to install 
[Anaconda](https://www.continuum.io/downloads).  

SAM Parser is invoked as follows:

    samparser <infile> [-outfile <output-file>] [-xslt <xslt-file> [-intermediate <intermediate-file>]] -smartquotes
    
    
The meaning of each parameter is as follows:
    
 * `<infile>`: The path of the SAM file to be parsed.
 
 * `-outfile <output-file>`: (optional) The name and path of the output file to be created. If `-xslt` is 
   specified, this will be the output of the XSLT stylesheet. Otherwise, it will 
   be the default XML representation of the SAM document. (short form: `-o`)
 
 * `-xslt <xslt-file>`: (optional) The name of an XSLT 1.0 stylesheet to be used to post process the 
   normal SAM XML output. (short form: `-x`)
   
 * `-intermediate <intermediate-file>`: (optional, requires that `-xslt` be specified) The name and path of 
   a file to which the default XML representation of the SAM file will be written if
   `xslt-file` is specified. This may be useful for debugging purposes. (short form `-i`)

### Validating with an XML schema

Eventually, SAM is going to have its own schema language, but until that is available 
(and probably afterward) you can validate your document against an XML schema. 
Schema validation is done on the XML output format, not the input (because it is an XML 
schema, not a SAM schema). To invoke schema validation, use the `-xsd` option 
on the command line:

     -xsd <scehma.xsd>

### Regurgitating the SAM document

The parser can also regurgitate the SAM document (that is, create a SAM serialization of 
the structure defined by the original SAM document). The regurgitated 
version may be different in small ways from the input document but will
create the same structures internally and will serialize the same
way as the original. Some of the difference are:

* Character entities will be replaced by Unicode characters.
* Paragraphs will be all on one line
* Bold and italic decorations will be replaced with equivalent 
  annotations.
* Some non-essential character escapes may be included.
* Annoation lookups will be performed and any `!annotation-lookup` declaration
  will be removed.
* Smart quote processing will be performed and any `!smart-quotes` declaration
  will be removed. 

To regurgitate, use the `-regurgitate` option, which may be abbreviated as `-r`. 

### Smart quotes

The parser incorporates a smart quotes feature. The writer can specify 
that they want smartquotes processing for their document by including 
the smartquotes declaration at the start of their document. 

    !smart-quotes: on 
    
By default, the parser supports two values for the smart quotes declaration, `on` 
and `off` (the default). The built-in `on` setting supports the following
translations: 

* single quotes to curly quotes 
* double quotes to curly double quotes
* single quotes as apostrophe to curly quotes
* <space>--<space> to en-dash
* --- to em-dash

Note that no smart quote algorithm is perfect. This option will miss some 
instances and may get some wrong. To ensure you always get the characters you 
want, enter the unicode characters directly or use a character entity. 

Smart quote processing is not applied to code phrases or to codeblocks 
or embedded markup.

Because different writers may want different smart quote rules, or different
rules may be appropriate to different kinds of materials. the parser lets 
you specify your own sets of smart quote rules. Essentially this lets you
detect any pattern in the text and define a substitution for it. You can use
it for any characters substitutions that you find useful, even those having 
nothing to do with quotes. 

To define a set of smart quote substitutions, create a XML file like the
`sq.xml` file included with the parser. This file includes two alternate 
sets of smart quote rules, `justquotes` and `justdashes`, which contains 
rulesets which process just quotes and just dashes respectively. The dashes 
and quotes rules in this file are the same as those built in to the parser.
Note, however, that the parser does not use these files by default. 

To invoke the `justquotes` rule set:

1. Add the declaration `!smart-quotes: justquotes` to the document. 

2. Use the command line parameter `-sq <path-to-sam-directory>/sq.xml`.

To add a custom rule set, create your own rule set file and invoke it 
in the same way. 

Note that the rules in each rule set are represented by regular expressions. 
The rules detect characters based on their surroundings. They do not detect 
quotations by finding the opening and closing quotes as a pair. They find them
separately. This means that the order of rules in the rule file may be 
important. In the default rules, close quote rules are listed first. 
Reversing the order might result in some close quotes being detected as 
open quotes. 



### Running SAM Parser on Windows

To run SAM Parser on Windows, use the `samparser` batch file:

    samparser foo.sam -o foo.html -x foo2html.xslt -i foo.xml
    
### Running SAM Parser on Xnix and Mac

To run SAM Parser on Xnix or Mac, invoke Python 3 as appropriate on your system. For example:

    python3 samparser.py foo.sam -o foo.html -x foo2html.xslt -i foo.xml



### Backward-incompatible changes

Since SAM is under active development, there may be backward-incompatible changes in the language. They will be noted here as they occur, up until we get to the point where the language or its serialization are considered final.

* Revision 227cb3dd7bb322f5579858806071c1ff8456c0b6 introduced a change in the 
way the XML representation of a record is generate. A record
used to output as "row". It is now output as "record".

* Revision 3fdd6528d88b1a7f0a72c10ce5b5e768433eaf19 introduced a change in how inline code is  serialized. It is now serialized as a `<code>` element rather than as a `<phrase>` element with an `<annotation type="code">` nested element.

* Revision 8e8c6a0b4c9c41bd72fab5fd53e3d967e9688110 removed the `===` flag for a block of embedded code, which had been briefly introduced in an earlier revision. Blocks of embed code should now be represented as regular code blocks using an encoding attribute `(=svg)` rather than a language attribute `(svg)`.

* Revision fac3fea6a9570a20c825369417ab2eaf94d34d2b made annotation lookup case insensitive. Case sensitive lookup can be turned on using the declaration `!annotation-lookup: case sensitive`

* Revision 828ef33d291f1364a6edf036588ac5f21fac0abb addressed issue #142 by detecting recursive includes. This had the side effect of changing the behavior when the parser encounters an error in an included file. Previously this error was demoted to a warning (not sure why). Now it is treated as an error and stops the parser. Without this change, the error would not get noted in the error count for batch processing, which is clearly not a good idea. To allow for more lenient error handling while retaining appropriate error reporting, we would need to introduce a reportable non-fatal error type. Issue #148 has been raised to consider this. 

* Revision e0fa711d14219cbad19636515e2dc2bbe3a82f28:

   * Changed the format of error messages to report the original line on which the error occurred rather than a representation of the object created.
   
   * Changed the format produced by the `__str__()` method on doc structure objects to a normalized representation of the input text generated by the new `regurgitate()` method.
   
   * Changed the serialization of citations on a block so they come before the title, not after it.
   
   * Changed the object model of Blockinsert and Inlineinsert object to make the type and item value separate fields of the object rather than simple attributes.

   * Changed serialization of block embed from "embed" to "embedblock" to be consistent with "codeblock".
   
   * Changed type of embedded blocks from Codeblock to Embedblock.
   
   * Removed support for embeded XML fragments per the discussion of issue #145. SAM has outgrown this feature, which is incompatible with the plan to introduce SAM Schemas.

* Revision 1d16fd6d0544c32fa23930f303989b1b4a82c477 addressed #157 by changing the serialization of citations as described in #157 and adding support of the use of keys in citations.

* Revision ad4365064bdfe61fa43228991a31b3174feb2957 removes the smart quotes parser option (the flag that turned smart quotes on and off on the command line) and introduced the `!smart-quotes` document declaration and the option to add custom smart quotes rules to the parser.

* Revision b4ca40baa03233ff306ed20a59da92668e4e0872 changes the syntax for inserting a value by reference. 
It used to be `>(#foo)` but this was confusing because parenthese are used to create names and ids, not
to reference them. The syntax for referencing a name or id is [#foo]. So, the syntax for inserting a value by
reference is now `>[#foo]`. This applies to strings, ids, names, fragments, and keys. Note that the syntax for
inserting a value by URI still uses parentheses, since this is new information, not a reference to another
internal value. Also note the difference between `[#foo]` which means generate a reference to the content with 
the name `foo` and `>[#foo]` which means insert the content with the name foo at the current location. (These are 
of course, operations performed at application layer, not by the parser.)

Please report any other backward incompatibilities you find so they can be added to this list.

