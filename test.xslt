<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">

    <xsl:output method="html"/>
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

    <xsl:template match="case">
        <xsl:apply-templates/>
    </xsl:template>

    <xsl:template match="case/title">
        <h3><xsl:apply-templates/></h3>
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
</xsl:stylesheet>