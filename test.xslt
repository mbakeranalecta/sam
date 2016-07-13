<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform" xmlns:my="my:my">

    <xsl:output method="html" omit-xml-declaration="no" />

    <xsl:preserve-space elements="codeblock markup"/>

  <xsl:template match="@*|node()">
    <xsl:copy>
      <xsl:apply-templates select="@*|node()"/>
    </xsl:copy>
  </xsl:template>



  <xsl:template match="*" mode="reproduce-markup">
    <xsl:text>&lt;</xsl:text>
    <xsl:value-of select="name()"/>
      <xsl:for-each select="@*">
          <xsl:text> </xsl:text>
          <xsl:value-of select="name()"/>
          <xsl:text>="</xsl:text>
          <xsl:call-template name="multiReplace">
              <xsl:with-param name="pRep" select="$attribute-reps"/>
          </xsl:call-template>

          <xsl:text>"</xsl:text>
      </xsl:for-each>
      <xsl:choose>
          <xsl:when test="not(*) and not(normalize-space())">
              <xsl:text>/&gt;</xsl:text>
          </xsl:when>
          <xsl:otherwise>
              <xsl:text>&gt;</xsl:text>
              <xsl:apply-templates mode="reproduce-markup"/>
              <xsl:text>&lt;/</xsl:text>
              <xsl:value-of select="name()"/>
              <xsl:text>&gt;</xsl:text>
          </xsl:otherwise>
      </xsl:choose>
  </xsl:template>

    <xsl:template match="*/text()" mode="reproduce-markup">
        <xsl:call-template name="multiReplace">
            <xsl:with-param name="pRep" select="$element-reps"/> 
        </xsl:call-template>

    </xsl:template>

    <xsl:template match="tests">
        <html>
            <head>
                <meta charset="UTF-8"/>
            </head>
            <body>
                <a name="top"/>
                <xsl:apply-templates select="title"/>
                <xsl:apply-templates select="description"/>
                <h2>Contents</h2>
                <ul>
                    <xsl:for-each select="test">
                        <li>
                            <a href="#{generate-id()}">
                                <xsl:value-of select="title"/>
                            </a>
                            <ul>
                                 <xsl:for-each select="case">
                                     <li>
                                         <a href="#{generate-id()}">
                                             <xsl:value-of select="title"/>
                                         </a>
                                     </li>
                                 </xsl:for-each>
                            </ul>
                        </li>
                    </xsl:for-each>
                </ul>
                <xsl:apply-templates select="test"/>
            </body>
        </html>
    </xsl:template>

    <xsl:template match="tests/title">
        <h1><xsl:apply-templates/></h1>
    </xsl:template>

    <xsl:template match="test">
        <xsl:apply-templates/>
        <a href="#top">^top</a>
    </xsl:template>

    <xsl:template match="test/title">
        <h2 id="{generate-id(..)}">Test: <xsl:apply-templates/></h2>
    </xsl:template>

    <xsl:template match="case">
        <xsl:apply-templates/>
    </xsl:template>

    <xsl:template match="case/title">
        <h3 id="{generate-id(..)}">Case: <xsl:apply-templates/></h3>
    </xsl:template>

    <xsl:template match="case/source">
        <h4>Source</h4>
        <xsl:apply-templates/>
    </xsl:template>

    <xsl:template match="case/markup">
        <h4>Formatted output (not necessarily supported for all tests)</h4>
        <xsl:apply-templates/>
    </xsl:template>

    <xsl:template match="case/result">
        <xsl:variable name="actual">
            <xsl:for-each select="../markup">
                <xsl:apply-templates  mode="reproduce-markup"/>
            </xsl:for-each>
        </xsl:variable>
        <xsl:variable name="intended" select="string(codeblock/text())"/>

        <h4>Intended output (space normalized)</h4>
        <pre><xsl:value-of select="normalize-space($intended)"/></pre>
        <h4>Actual output  (space normalized)</h4>
        <pre><xsl:value-of select="normalize-space($actual)"/></pre>


        <h4>Test result</h4>
        <xsl:choose>
            <xsl:when test="normalize-space($actual) = normalize-space($intended)">
                <p style="color: green; font-weight: bold">PASS</p>
            </xsl:when>
            <xsl:otherwise>
                <p style="color: red; font-weight: bold">**** FAIL ****</p>
            </xsl:otherwise>
        </xsl:choose>
    </xsl:template>


    <xsl:template match="codeblock">
        <pre><xsl:apply-templates/></pre>
    </xsl:template>

    <xsl:template match="annotation[@type='bold']">
        <b><xsl:apply-templates/></b>
    </xsl:template>

    <xsl:template match="annotation[@type='italic']">
        <i><xsl:apply-templates/></i>
    </xsl:template>

    <xsl:template match="annotation[@type='code']">
        <tt><xsl:apply-templates/></tt>
    </xsl:template>

    <xsl:template match="annotation[@type='link']">
        <a href="{@specifically}"><xsl:apply-templates/></a>
    </xsl:template>

    <xsl:template match="annotation[@type='if']">
        [<xsl:apply-templates/>]?
    </xsl:template>

    <xsl:template match="phrase">
        <span style="color: green">
            <xsl:apply-templates/>
        </span>
    </xsl:template>

    <xsl:template match="annotation">
        <span style="color: red">
            <xsl:apply-templates/>
        </span>
    </xsl:template>

    <xsl:template match="citation">
        <xsl:apply-templates/>
        <span style="color: brown">
            <xsl:text>[</xsl:text>
            <xsl:value-of select="@value"/>
            <xsl:text>]</xsl:text>
        </span>
    </xsl:template>


    <xsl:template match="grid">
        <table border="1">
            <xsl:apply-templates/>
        </table>
    </xsl:template>

    <xsl:template match="grid/row">
        <tr>
            <xsl:apply-templates/>
        </tr>
    </xsl:template>

    <xsl:template match="grid/row/cell">
        <td>
            <xsl:apply-templates/>
        </td>
    </xsl:template>

    <xsl:template match="line">
        <xsl:apply-templates/>
        <br/>
    </xsl:template>
    
    <xsl:template match="ll">
        <xsl:apply-templates/>
    </xsl:template>
    
    <xsl:template match="ll/li">
        <xsl:apply-templates/>
    </xsl:template>
    
    <xsl:template match="ll/li/label"/>
    
    <xsl:template match="ll/li/p[1]">
        <p>
           <b>
               <xsl:value-of select="../label"/>
               <xsl:text>: </xsl:text>
           </b>
            <xsl:apply-templates/>
        </p>
    </xsl:template>

    

    <xsl:template name="string-replace-all">
        <xsl:param name="text" />
        <xsl:param name="replace" />
        <xsl:param name="by" />
        <xsl:choose>
            <xsl:when test="$text = '' or $replace = ''or not($replace)" >
                <!-- Prevent this routine from hanging -->
                <xsl:value-of select="$text" />
            </xsl:when>
            <xsl:when test="contains($text, $replace)">
                <xsl:value-of select="substring-before($text,$replace)" />
                <xsl:value-of select="$by" />
                <xsl:call-template name="string-replace-all">
                    <xsl:with-param name="text" select="substring-after($text,$replace)" />
                    <xsl:with-param name="replace" select="$replace" />
                    <xsl:with-param name="by" select="$by" />
                </xsl:call-template>
            </xsl:when>
            <xsl:otherwise>
                <xsl:value-of select="$text" />
            </xsl:otherwise>
        </xsl:choose>
    </xsl:template>

  <my:attribute-reps>
  <rep>
    <old>&amp;</old>
    <new>&amp;amp;</new>
  </rep>
  <rep>
    <old>&quot;</old>
    <new>&amp;quot;</new>
  </rep>
  <rep>
    <old>&lt;</old>
    <new>&amp;lt;</new>
  </rep>
  <rep>
    <old>&gt;</old>
    <new>&amp;gt;</new>
  </rep>
 </my:attribute-reps>
    
<my:element-reps>
    <rep>
        <old>&amp;</old>
        <new>&amp;amp;</new>
    </rep>
    <rep>
        <old>&lt;</old>
        <new>&amp;lt;</new>
    </rep>
    <rep>
        <old>&gt;</old>
        <new>&amp;gt;</new>
    </rep>
    
</my:element-reps>

    <xsl:variable name="element-reps" select="document('')/*/my:element-reps/*"/>
    <xsl:variable name="attribute-reps" select="document('')/*/my:attribute-reps/*"/>
    
 <xsl:template name="multiReplace">
  <xsl:param name="pText" select="."/>
  <xsl:param name="pRep"/>

  <xsl:choose>
    <xsl:when test="not($pRep)"><xsl:value-of select="$pText"/></xsl:when>
      <xsl:otherwise>
        <xsl:variable name="vReplaced">
            <xsl:call-template name="replace">
              <xsl:with-param name="pText" select="$pText"/>
              <xsl:with-param name="pOld" select="$pRep/old"/>
              <xsl:with-param name="pNew" select="$pRep/new"/>
            </xsl:call-template>
        </xsl:variable>

        <xsl:call-template name="multiReplace">
         <xsl:with-param name="pText" select="$vReplaced"/>
         <xsl:with-param name="pRep" select="$pRep/following-sibling::*[1]"/>
        </xsl:call-template>
      </xsl:otherwise>
  </xsl:choose>
 </xsl:template>

 <xsl:template name="replace">
   <xsl:param name="pText"/>
   <xsl:param name="pOld"/>
   <xsl:param name="pNew"/>

   <xsl:if test="$pText">
     <xsl:value-of select="substring-before(concat($pText,$pOld), $pOld)"/>
       <xsl:if test="contains($pText, $pOld)">
         <xsl:value-of select="$pNew"/>
             <xsl:call-template name="replace">
               <xsl:with-param name="pText" select="substring-after($pText, $pOld)"/>
               <xsl:with-param name="pOld" select="$pOld"/>
               <xsl:with-param name="pNew" select="$pNew"/>
             </xsl:call-template>
       </xsl:if>
   </xsl:if>
 </xsl:template>
    
    <xsl:template match="description">
        <xsl:apply-templates/>
    </xsl:template>
</xsl:stylesheet>