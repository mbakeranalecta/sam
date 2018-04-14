sam
===

Semantic Authoring Markdown

XML was designed to be human readable, but not human writable. Graphical editors help, though they have their issues
(like trying to find the right insertion point to add permitted elements). But graphical editors have a problem: when 
they hide the tags, they also hide the structure.

Semantic Authoring Markdown brings the ideas behind Markdown -- a natural syntax for writing HTML documents -- to 
structured writing. It creates a syntax that captures structure, like XML, but is easy to write in a text editor
-- like markdown.

### Documentation

See the documentation at https://mbakeranalecta.github.io/sam/.

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

    samparser <output_mode> <options>
    
Three output modes are available:

* `xml` outputs a version of the document in XML. You can use an XSD schema to validate the output file and/or an XSLT 1.0 stylesheet to transform it into another format. 
* `html` outputs a version of the document in HTML with embedded semantic markup. You can supply one of more CSS stylesheets and/or one or more JavaScrip files to include. 
* `regurgitate` outputs a version of the document in SAM with various references resolved and normalized. 

All output modes take the following options:

* `<infile>` The path the SAM file or files to be processed. (required)
* `[-outfile <output file>]|[-outdir <output directory> [-outputextension <output extension>]]` Specifies either an output file or a directory to place output files and the file extension to apply those files. (optional, defaults to the console)
* `-smartquotes <smartquote_rules>` The path to a file containing smartquote rules. 

XML output mode takes the following options: 
 
* `[-xslt <xslt-file> [-transformedoutputfile <transformed file>]\[-transformedoutputdir <tansformed ouput dir> [-transformedextension <transformed files extension]]` Specifies an XSL 1.0 stylesheet to use to transform the XML output into a final format, along with the file name or directory and extension to use for the transformed output. 
* `[-xsd <XSD schema file>]` Specifies an XSD schema file to use to validate the XML output file. 

HTML output mode takes the follow options:

* `-css <css file location>` Specifies the path to a CSS file to include in the HTML output file. (optional, repeatable)
* `-javascipt <javascript file location>` Specifies the path to a JavaScript file to include in the HTML output file. (optional, repeatable)

Regurgitate mode does not take any additional options. 
       
Short forms of the options are available as follows

|-outfile|-o|
|-outdir|-od|
|-outputextension|-oext|
|-smartquotes|-sq|
|-xslt|-x|
|-xsd||
|-transformedoutputfile|-to|
|-transformedoutputdir|-tod|
|-transformedextension|-toext|
|-css||
|-javascript|

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
* Annotation lookups will be performed and any `!annotation-lookup` declaration
  will be removed.
* Smart quote processing will be performed and any `!smart-quotes` declaration
  will be removed. 

To regurgitate, use the `regurgitate` output mode. 

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

### HTML Output Mode

Normally SAM is serialized to XML which you can then process to produce HTML or any other 
output you want. However, the parser also supports outputting HTML directly. The attraction
of this is that it allows you to have a semantically constrained input format that can
be validated with a schema but which can still output to HTML5 directly. 

SAM structures are output to HTML as follows:

* Named blocks are output as HTML `<div>` elements. The SAM block
name is output as the `class` attribute of the DIV elements, allowing you to attach 
specific CSS styling to each type of block. 

* Codeblocks are output as `pre` elements with the language attribute output as a `data-language`
and the `class` as `codeblock`. Code is wrapped in `code` tags, also with `class` as `codeblock`.

* Embedded data is ignored and a warning is issued.  

* Paragraphs, ordered lists, and unordered lists are output as their HTML equivalents.

* Labelled lists are output as definition lists. 

* Grids are output as tables.

* Record sets are output as tables with the field names as table headers.

* Inserts by URL become `object` elements. String inserts are resolved if the named string is available. 
Inserts by ID are resolved by inserting the object with the specified ID. A warning will be raised and
the insert will be ignored if you try to insert a block element with an inline insert or and inline
element with a block insert. All other inserts are ignored and a warning is raised.

* Phrases are output as spans with the `class` attribute `phrase`.

* Annotations are output as spans nested within the phrase spans they annotate. The specifically and 
namespace attributes of an annotation are output as `data-*` attributes.

* Attributes are output as HTML attributes. ID attributes are output as HTML `id` attributes. Language-code 
attributes are ouput as HTML `lang` attributes. Other attributes are output as HTML `data-*` attributes. 

* An HTML `head` element is generated which includes the `title` elements if the root block of the 
SAM document has a title. It also includes `<meta charset = "UTF-8">`.

To generate HTML output, use the `html` output mode the command line.

To specify a stylesheet to be imported by the resulting HTML file, use the `-css` option with the 
URL of the css file to be included (relative to the location of the HTML file). You can specify the
`-css` option more than once.

To specify a javascript file to be imported by the resulting HTML file, use the `-javascript` option 
with the URL of the javascript file to be included (relative to the location of the HTML file). You 
can specify the `-javascript` option more than once.




### Running SAM Parser on Windows

To run SAM Parser on Windows, use the `samparser` batch file:

    samparser xml foo.sam -o foo.xml -x foo2html.xslt -to foo.html
    
### Running SAM Parser on Xnix and Mac

To run SAM Parser on Xnix or Mac, invoke Python 3 as appropriate on your system. For example:

    python3 samparser.py xml foo.sam -o foo.xml -x foo2html.xslt -to foo.html



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

* Starting with revision dd07a4b798fcaa14a722a345b5ab8e07c3df42a1 the way attributes were modeled internally
changed. Instead of using as separate Attribute object, attributes became Python attributes on the relevant
block or phrase object. This does not affect command line use but would affect programmatic access to 
the document structure. 

* Starting with revision dd07a4b798fcaa14a722a345b5ab8e07c3df42a1, the use of fragment references 
with the syntax `[~foo]` was removed (see issue #166). Fragments can be inserted by name or ID just
like any other block type. 

* From revision 3e9b8f6fd8cddf9cbedb25c44ab48323216ce71e 

   * The change to insert by reference in b4ca40baa03233ff306ed20a59da92668e4e0872
   is reversed. It caused slightly more confusion than the old version. 
   
   * The `~` symbol or referencing an fragment is removed. Fragments should
   be referenced by name or id.
   
   * The strings feature has been renamed "variable". This chiefly affects
   the serialization of variable definitions and references. 
   
* In revision 1f20902624d29dab002353df8374952c63fff81d the serialization of citations has been changed to support 
compound identifiers and to support easier processing of citations. See the
language docs for details. 

* In revision defbc97c9bd592ab454296852c3d9a65e1007996 the command line options changed to support three different 
output modes as subcommands. Other options changed as well. See above for the new command line options. 

Please report any other backward incompatibilities you find so they can be added to this list.

