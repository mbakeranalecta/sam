sam
===

Semantic Authoring Markdown

XML was designed to be human readable, but not human writable. Graphical editors help, though they have their issues
(like trying to find the right insertion point to add permitted elements). But graphical editors have a problem: when 
they hide the tags, they also hide the structure.

Semantic Authoring Markdown brings the ideas behind Markdown -- a natural syntax for writing HTML documents -- to 
structured writing. It creates a syntax that captures structure, like XML, but is easy to write in a text editor
-- like markdown.

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
    
 * infile: The path of the SAM file to be parsed.
 
 * -outfile: (optional) The name and path of the output file to be created. If `-xslt` is 
   specified, this will be the output of the XSLT stylesheet. Otherwise, it will 
   be the default XML representation of the SAM document. (short form: `-o`)
 
 * -xslt: (optional) The name of an XSLT 1.0 stylesheet to be used to post process the 
   normal SAM XML output. (short form: `-x`)
   
 * -intermediate: (optional, requires that `-xslt` be specified) The name and path of 
   a file to which the default XML representation of the SAM file will be written if
   `xslt-file` is specified. This may be useful for debugging purposes. (short form `-i`)
   
 * -smartquotes: Turns on smart quotes processing. (short form `-q`)
   
### Running SAM Parser on Windows

To run SAM Parser on Windows, use the `samparser` batch file:

    samparser foo.sam -o foo.html -x foo2html.xslt -i foo.xml
    
### Running SAM Parser on Xnix and Mac

To run SAM Parser on Xnix or Mac, invoke Python 3 as appropriate on your system. For example:

    python3 samparser.py foo.sam -o foo.html -x foo2html.xslt -i foo.xml
