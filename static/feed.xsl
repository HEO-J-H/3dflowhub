<?xml version="1.0" encoding="UTF-8"?>
<!-- 브라우저에서 feed.xml 을 열었을 때 원문 XML 대신 보여줄 구독 안내 화면 (RSS 리더는 이 파일을 무시) -->
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
<xsl:output method="html" encoding="UTF-8" indent="yes"/>
<xsl:template match="/">
<html lang="ko">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RSS 구독 · <xsl:value-of select="/rss/channel/title"/></title>
<link rel="icon" href="favicon.svg" type="image/svg+xml"/>
<style>
:root{--bg:#fbfbfd;--card:#fff;--fg:#1d1d1f;--mute:#6e6e73;--line:#e5e5ea;--acc:#0071e3;--tip:#eef5ff}
@media (prefers-color-scheme:dark){:root{--bg:#000;--card:#1c1c1e;--fg:#f5f5f7;--mute:#a1a1a6;--line:#38383a;--acc:#2997ff;--tip:#0b2340}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard","Malgun Gothic",sans-serif}
main{max-width:760px;margin:0 auto;padding:32px 16px 64px}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
.tip{background:var(--tip);border-radius:16px;padding:18px 20px;margin:0 0 28px}
.tip b{display:block;margin-bottom:4px}
.url{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.url code{flex:1;min-width:0;overflow-wrap:anywhere;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 12px;font-size:14px}
.url button{border:0;border-radius:10px;background:var(--acc);color:#fff;padding:8px 14px;font:inherit;cursor:pointer}
h1{font-size:28px;margin:0 0 6px}
.desc{color:var(--mute);margin:0 0 24px}
.item{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px 18px;margin:0 0 12px}
.item h2{font-size:17px;margin:0 0 6px;line-height:1.4}
.meta{color:var(--mute);font-size:13px}
.item p{margin:8px 0 0;color:var(--mute);font-size:14px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
</style>
</head>
<body><main>
<div class="tip">
<b>📡 RSS 구독 주소입니다</b>
이 주소를 Feedly·Inoreader·NetNewsWire 같은 RSS 리더에 추가하면 새 글을 자동으로 받아볼 수 있습니다.
<div class="url"><code id="u"><xsl:value-of select="/rss/channel/atom:link/@href" xmlns:atom="http://www.w3.org/2005/Atom"/></code>
<button type="button" onclick="navigator.clipboard.writeText(document.getElementById('u').textContent);this.textContent='복사됨'">주소 복사</button></div>
</div>
<h1><a href="{/rss/channel/link}"><xsl:value-of select="/rss/channel/title"/></a></h1>
<p class="desc"><xsl:value-of select="/rss/channel/description"/></p>
<xsl:for-each select="/rss/channel/item">
<div class="item">
<h2><a href="{link}"><xsl:value-of select="title"/></a></h2>
<div class="meta"><xsl:value-of select="category"/> · <xsl:value-of select="substring(pubDate,1,16)"/></div>
<p><xsl:value-of select="description"/></p>
</div>
</xsl:for-each>
</main></body>
</html>
</xsl:template>
</xsl:stylesheet>
