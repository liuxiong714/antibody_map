// content-script.js
// 在学术文献/网页上下文中提取元数据，供 popup 通过 background 调用
// 支持：PubMed、PMC、知网（CNKI）、万方、维普、Nature、Science、Cell、Springer、Wiley、Lancet、BMJ、medRxiv/bioRxiv、arXiv、DOI 直接页面、通用 HTML

(function () {
  'use strict';

  /**
   * 从当前页面提取文献元数据
   * @returns {Object} 元数据对象
   */
  function extractMetadata() {
    const meta = {
      url: location.href,
      title: '',
      authors: [],
      journal: '',
      pub_year: null,
      doi: '',
      pmid: '',
      abstract: '',
      keywords: [],
      is_pdf: false,
      page_type: detectPageType(),
      pdf_links: [],
    };

    // 1. PDF 检测
    if (document.contentType === 'application/pdf' || location.pathname.toLowerCase().endsWith('.pdf')) {
      meta.is_pdf = true;
      meta.title = decodeURIComponent(location.pathname.split('/').pop() || '').replace(/\.pdf$/i, '') || document.title;
      return finalize(meta);
    }

    // 2. 通用标题
    meta.title = (document.querySelector('meta[name="dc.title"]')?.content
      || document.querySelector('meta[name="citation_title"]')?.content
      || document.querySelector('meta[property="og:title"]')?.content
      || document.title || '').trim();

    // 3. 作者（优先 citation_author，其次 dc.creator）
    const authorNodes = document.querySelectorAll('meta[name="citation_author"], meta[name="dc.Creator"]');
    authorNodes.forEach((n) => {
      const v = (n.content || '').trim();
      if (v) meta.authors.push(v);
    });
    // PubMed 特殊：作者在 .full-author-name a / .authors-list-item
    if (meta.authors.length === 0) {
      document.querySelectorAll('.full-author-name a, .authors-list a, .author-name').forEach((a) => {
        const v = (a.textContent || '').trim();
        if (v && v.length < 80 && !v.match(/^(View|Affiliations|ORCID)/i)) meta.authors.push(v);
      });
    }

    // 4. 期刊
    meta.journal = (document.querySelector('meta[name="citation_journal_title"]')?.content
      || document.querySelector('meta[name="dc.Source"]')?.content
      || document.querySelector('meta[property="og:site_name"]')?.content
      || '').trim();

    // 5. 年份
    const dateStr = document.querySelector('meta[name="citation_publication_date"]')?.content
      || document.querySelector('meta[name="dc.Date"]')?.content
      || document.querySelector('meta[name="citation_date"]')?.content
      || document.querySelector('meta[name="prism.publicationDate"]')?.content
      || '';
    if (dateStr) {
      const m = dateStr.match(/(\d{4})/);
      if (m) meta.pub_year = parseInt(m[1], 10);
    }
    if (!meta.pub_year) {
      const text = document.body?.innerText?.slice(0, 5000) || '';
      const m = text.match(/\b(19|20)\d{2}\b/);
      if (m) meta.pub_year = parseInt(m[0], 10);
    }

    // 6. DOI
    meta.doi = (document.querySelector('meta[name="citation_doi"]')?.content
      || document.querySelector('meta[name="dc.Identifier"]')?.content
      || document.querySelector('meta[name="prism.doi"]')?.content
      || '').trim();
    if (!meta.doi) {
      // 从页面文本或链接中提取
      const doiMatch = document.body?.innerText?.match(/10\.\d{4,9}\/[-._;()/:A-Z0-9]+/i);
      if (doiMatch) meta.doi = doiMatch[0].replace(/[.;,)]$/, '');
    }

    // 7. PMID
    const pmidMatch = document.body?.innerText?.match(/PMID:\s*(\d+)/i);
    if (pmidMatch) meta.pmid = pmidMatch[1];
    if (!meta.pmid) {
      const pm = document.querySelector('meta[name="citation_pmid"]')?.content;
      if (pm) meta.pmid = pm;
    }

    // 8. 摘要
    meta.abstract = (document.querySelector('meta[name="citation_abstract"]')?.content
      || document.querySelector('meta[name="dc.Description"]')?.content
      || '').trim();
    if (!meta.abstract) {
      const absEl = document.querySelector('.abstract-content, .abstract, #abstract, .article-abstract, [class*="abstract"]');
      if (absEl) {
        // 移除子元素中的标题、按钮
        absEl.querySelectorAll('h1,h2,h3,h4,h5,h6,.abstract-title,button').forEach((e) => e.remove());
        meta.abstract = (absEl.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 3000);
      }
    }

    // 9. 关键词
    const kwNodes = document.querySelectorAll('meta[name="citation_keywords"], meta[name="keywords"], meta[name="dc.Subject"]');
    kwNodes.forEach((n) => {
      const v = (n.content || '').trim();
      if (v) meta.keywords.push(...v.split(/[;,、]/).map((s) => s.trim()).filter(Boolean));
    });

    // 10. PDF 链接（学术站点的 PDF 下载入口）
    const pdfLinkSelectors = [
      'meta[name="citation_pdf_url"]',
      'a.pdf-download',
      'a[href$=".pdf"]',
      'a[title*="PDF" i]',
      'a.article-pdfLink',
    ];
    const seenPdf = new Set();
    pdfLinkSelectors.forEach((sel) => {
      const el = document.querySelector(sel);
      if (!el) return;
      let href = el.tagName === 'META' ? el.content : el.href;
      if (!href) return;
      try {
        href = new URL(href, location.href).href;
      } catch (e) { /* ignore */ }
      if (href && !seenPdf.has(href)) {
        seenPdf.add(href);
        meta.pdf_links.push(href);
      }
    });

    return finalize(meta);
  }

  function detectPageType() {
    const host = location.hostname.toLowerCase();
    const path = location.pathname.toLowerCase();
    if (path.endsWith('.pdf')) return 'pdf';
    if (host.includes('pubmed') || host.includes('ncbi.nlm.nih.gov')) return 'pubmed';
    if (host.includes('pmc.ncbi.nlm.nih.gov') || host.includes('ncbi.nlm.nih.gov/pmc')) return 'pmc';
    if (host.includes('cnki.net') || host.includes('cnki.com.cn')) return 'cnki';
    if (host.includes('wanfangdata.com.cn')) return 'wanfang';
    if (host.includes('cqvip.com')) return 'vip';
    if (host.includes('nature.com')) return 'nature';
    if (host.includes('science.org')) return 'science';
    if (host.includes('cell.com')) return 'cell';
    if (host.includes('springer.com') || host.includes('link.springer.com')) return 'springer';
    if (host.includes('wiley.com')) return 'wiley';
    if (host.includes('thelancet.com')) return 'lancet';
    if (host.includes('bmj.com')) return 'bmj';
    if (host.includes('medrxiv.org') || host.includes('biorxiv.org')) return 'biorxiv';
    if (host.includes('arxiv.org')) return 'arxiv';
    if (host.includes('doi.org')) return 'doi';
    return 'generic';
  }

  function finalize(meta) {
    // 截断超长字段
    if (meta.abstract.length > 3000) meta.abstract = meta.abstract.slice(0, 3000);
    if (meta.authors.length > 50) meta.authors = meta.authors.slice(0, 50);
    if (meta.pdf_links.length > 5) meta.pdf_links = meta.pdf_links.slice(0, 5);
    return meta;
  }

  // 监听来自 background/popup 的提取请求
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg && msg.type === 'EXTRACT_METADATA') {
      try {
        const data = extractMetadata();
        sendResponse({ success: true, data });
      } catch (e) {
        sendResponse({ success: false, error: String(e && e.message || e) });
      }
      return true; // 保持消息通道
    }
  });

  // 控制台标记
  console.log('[AntibodyMap Helper] content-script loaded on', location.href);
})();
