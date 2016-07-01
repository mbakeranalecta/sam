<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:template match="@*|node()">
    <xsl:copy>
      <xsl:apply-templates select="@*|node()"/>
    </xsl:copy>
  </xsl:template>

    <xsl:template match="tests">
        <html>
            <head>
                <meta charset="UTF-8"/>
            </head>
            <body>
                <xsl:apply-templates/>
            </body>
        </html>
    </xsl:template>

    <xsl:template match="tests/title">
        <h2><xsl:apply-templates/></h2>
    </xsl:template>

    <xsl:template match="test">
        <xsl:apply-templates/>
    </xsl:template>

    <xsl:template match="test/title">
        <h2><xsl:apply-templates/></h2>
    </xsl:template>

    <xsl:template match="codeblock">
        <pre><xsl:apply-templates/></pre>
    </xsl:template>

    <xsl:template match="annotation[@type='bold']">
        <b><xsl:apply-templates/></b>
    </xsl:template>

    <xsl:template match="annotation[@type='code']">
        <tt><xsl:apply-templates/></tt>
    </xsl:template>
</xsl:stylesheet>