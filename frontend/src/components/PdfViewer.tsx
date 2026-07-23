import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Button, Space, Spin, message } from 'antd';
import {
  ZoomInOutlined,
  ZoomOutOutlined,
  ExpandOutlined,
  ColumnWidthOutlined,
} from '@ant-design/icons';
import * as pdfjsLib from 'pdfjs-dist/build/pdf';

pdfjsLib.GlobalWorkerOptions.workerSrc =
  `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjsLib.version}/pdf.worker.min.js`;

const CMAKE_URL = '/cmaps/';
const STANDARD_FONTS_URL = '/standard_fonts/';

interface PdfViewerProps {
  literatureId: string | null;
  defaultScale?: number;
  maxHeight?: string;
}

const MIN_SCALE = 0.5;
const MAX_SCALE = 3.0;
const SCALE_STEP = 0.2;
const RENDER_BUFFER = 2; // 当前可视区域外额外渲染的页数

const PdfViewer: React.FC<PdfViewerProps> = ({
  literatureId,
  defaultScale = 1.0,
  maxHeight = 'calc(100vh - 280px)',
}) => {
  const [numPages, setNumPages] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scale, setScale] = useState(defaultScale);
  const [loading, setLoading] = useState(false);
  const [pageDims, setPageDims] = useState<{ w: number; h: number }[]>([]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const pdfRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null);
  const firstPageWidthRef = useRef<number>(0);
  const canvasMapRef = useRef<Map<number, HTMLCanvasElement>>(new Map());
  const observerRef = useRef<IntersectionObserver | null>(null);
  const renderTasksRef = useRef<Map<number, pdfjsLib.RenderTask>>(new Map());
  const visibleRangeRef = useRef<{ start: number; end: number }>({ start: 1, end: 1 });
  const allDimsRef = useRef<{ w: number; h: number }[]>([]);

  // 计算适合宽度的缩放比例
  const calcFitWidthScale = useCallback(() => {
    if (!scrollRef.current || firstPageWidthRef.current === 0) return null;
    const containerWidth = scrollRef.current.clientWidth - 24;
    if (containerWidth <= 0) return null;
    const fit = containerWidth / firstPageWidthRef.current;
    return Math.max(MIN_SCALE, Math.min(MAX_SCALE, Math.round(fit * 10) / 10));
  }, []);

  // 渲染单页
  const renderPage = useCallback(async (pageNum: number, pdf: pdfjsLib.PDFDocumentProxy, currentScale: number) => {
    // 取消之前的同页渲染任务
    const oldTask = renderTasksRef.current.get(pageNum);
    if (oldTask) { try { oldTask.cancel(); } catch { /* ignore */ } }

    const canvas = canvasMapRef.current.get(pageNum) || document.createElement('canvas');
    canvasMapRef.current.set(pageNum, canvas);

    const pdfPage = await pdf.getPage(pageNum);
    const pixelRatio = window.devicePixelRatio || 1;
    const viewport = pdfPage.getViewport({ scale: currentScale * pixelRatio });

    canvas.width = viewport.width;
    canvas.height = viewport.height;
    canvas.style.width = `${viewport.width / pixelRatio}px`;
    canvas.style.height = `${viewport.height / pixelRatio}px`;
    canvas.style.display = 'block';
    canvas.style.marginBottom = '8px';
    canvas.style.boxShadow = '0 2px 12px rgba(0,0,0,0.12)';
    canvas.setAttribute('data-page', String(pageNum));

    const ctx = canvas.getContext('2d')!;
    const renderTask = pdfPage.render({ canvasContext: ctx, viewport });
    renderTasksRef.current.set(pageNum, renderTask);
    await renderTask.promise;
    renderTasksRef.current.delete(pageNum);

    return canvas;
  }, []);

  // 挂载 canvas 到对应的 placeholder
  const mountCanvas = useCallback((pageNum: number, canvas: HTMLCanvasElement) => {
    const placeholder = document.getElementById(`pdf-placeholder-${pageNum}`);
    if (placeholder && placeholder.firstChild !== canvas) {
      placeholder.innerHTML = '';
      placeholder.appendChild(canvas);
    }
  }, []);

  // 渲染可见范围内的页面
  const renderVisiblePages = useCallback(async (rangeStart: number, rangeEnd: number) => {
    const pdf = pdfRef.current;
    if (!pdf) return;

    const totalPages = pdf.numPages;
    const start = Math.max(1, rangeStart - RENDER_BUFFER);
    const end = Math.min(totalPages, rangeEnd + RENDER_BUFFER);

    // 取消不在范围内的渲染任务
    renderTasksRef.current.forEach((task, p) => {
      if (p < start || p > end) { try { task.cancel(); } catch { /* ignore */ } }
    });

    // 渲染范围内的页面
    const toRender: number[] = [];
    for (let i = start; i <= end; i++) {
      const canvas = canvasMapRef.current.get(i);
      // 如果已经有 canvas 且尺寸匹配当前缩放，跳过
      if (canvas) {
        const px = window.devicePixelRatio || 1;
        const dim = allDimsRef.current[i - 1];
        if (dim && Math.abs(canvas.width - dim.w * scale * px) < 2) {
          continue;
        }
      }
      toRender.push(i);
    }

    // 并行渲染（限制并发数）
    const batchSize = 4;
    for (let i = 0; i < toRender.length; i += batchSize) {
      const batch = toRender.slice(i, i + batchSize);
      const results = await Promise.allSettled(
        batch.map((p) => renderPage(p, pdf, scale)),
      );
      results.forEach((r, idx) => {
        if (r.status === 'fulfilled' && r.value) {
          mountCanvas(batch[idx], r.value);
        }
      });
    }
  }, [scale, renderPage, mountCanvas]);

  // 设置 IntersectionObserver
  const setupObserver = useCallback(() => {
    if (!scrollRef.current) return;

    // 清除旧 observer
    if (observerRef.current) {
      observerRef.current.disconnect();
    }

    observerRef.current = new IntersectionObserver(
      (entries) => {
        const visible: number[] = [];
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            const page = parseInt(entry.target.getAttribute('data-page') || '1', 10);
            visible.push(page);
          }
        });
        if (visible.length > 0) {
          const newStart = Math.min(...visible);
          const newEnd = Math.max(...visible);
          const old = visibleRangeRef.current;
          // 只在可见范围明显变化时重新渲染
          if (Math.abs(newStart - old.start) > 1 || Math.abs(newEnd - old.end) > 1) {
            visibleRangeRef.current = { start: newStart, end: newEnd };
            renderVisiblePages(newStart, newEnd);
          }
        }
      },
      {
        root: scrollRef.current,
        rootMargin: '200px 0px 200px 0px',
        threshold: 0.01,
      },
    );

    // 观察所有页面占位符
    for (let i = 1; i <= numPages; i++) {
      const el = document.getElementById(`pdf-placeholder-${i}`);
      if (el) observerRef.current.observe(el);
    }

    // 初始渲染第一页附近
    renderVisiblePages(1, Math.min(RENDER_BUFFER * 2 + 1, numPages));
  }, [numPages, renderVisiblePages]);

  const loadPdf = useCallback(async () => {
    if (!literatureId) return;
    setLoading(true);
    try {
      // 清理之前的状态
      renderTasksRef.current.forEach((t) => { try { t.cancel(); } catch { /* ignore */ } });
      renderTasksRef.current.clear();
      if (observerRef.current) { observerRef.current.disconnect(); observerRef.current = null; }
      canvasMapRef.current.clear();
      pdfRef.current?.destroy();

      const url = `/api/v1/literatures/${literatureId}/file`;
      const loadingTask = pdfjsLib.getDocument({
        url,
        cMapUrl: CMAKE_URL,
        cMapPacked: true,
        useSystemFonts: true,
        standardFontDataUrl: STANDARD_FONTS_URL,
      });
      const pdf = await loadingTask.promise;
      pdfRef.current = pdf;
      setNumPages(pdf.numPages);
      setCurrentPage(1);
      visibleRangeRef.current = { start: 1, end: 1 };

      // 预计算所有页面的1.0比例尺寸（用于占位符）
      const dims: { w: number; h: number }[] = [];
      for (let i = 1; i <= pdf.numPages; i++) {
        const page = await pdf.getPage(i);
        const view = page.getViewport({ scale: 1.0 });
        dims.push({ w: view.width, h: view.height });
      }
      allDimsRef.current = dims;
      firstPageWidthRef.current = dims[0]?.w || 0;
      setPageDims(dims);

      // 计算适合宽度的缩放
      const fit = calcFitWidthScale();
      const useScale = fit || defaultScale;
      setScale(useScale);

      setLoading(false);

      // 延迟设置 observer（等待 React 渲染出占位符）
      setTimeout(() => setupObserver(), 100);
    } catch {
      message.error('PDF 加载失败，请确认文件是否存在');
      setLoading(false);
    }
  }, [literatureId, defaultScale, calcFitWidthScale, setupObserver]);

  useEffect(() => {
    if (literatureId) {
      loadPdf();
    }
    return () => {
      renderTasksRef.current.forEach((t) => { try { t.cancel(); } catch { /* ignore */ } });
      renderTasksRef.current.clear();
      if (observerRef.current) { observerRef.current.disconnect(); observerRef.current = null; }
      pdfRef.current?.destroy();
      pdfRef.current = null;
      canvasMapRef.current.clear();
    };
  }, [literatureId]);

  // 缩放变化时重新渲染
  useEffect(() => {
    if (pdfRef.current && !loading) {
      // 清除所有已渲染的 canvas
      canvasMapRef.current.clear();
      renderTasksRef.current.forEach((t) => { try { t.cancel(); } catch { /* ignore */ } });
      renderTasksRef.current.clear();
      // 重新渲染可见范围
      const range = visibleRangeRef.current;
      renderVisiblePages(range.start, range.end);
    }
  }, [scale]);

  const handleScroll = useCallback(() => {
    const container = scrollRef.current;
    if (!container) return;

    const rect = container.getBoundingClientRect();
    const containerTop = rect.top + 10;
    const containerHeight = rect.height;

    let bestPage = 1;
    let bestRatio = 0;

    canvasMapRef.current.forEach((canvas, pageNum) => {
      const cr = canvas.getBoundingClientRect();
      const visibleTop = Math.max(cr.top, containerTop);
      const visibleBottom = Math.min(cr.bottom, containerTop + containerHeight);
      const visibleHeight = Math.max(0, visibleBottom - visibleTop);
      const ratio = cr.height > 0 ? visibleHeight / cr.height : 0;

      if (ratio > bestRatio) {
        bestRatio = ratio;
        bestPage = pageNum;
      }
    });

    setCurrentPage(bestPage);
  }, []);

  const handleZoomIn = () => setScale((s) => Math.min(s + SCALE_STEP, MAX_SCALE));
  const handleZoomOut = () => setScale((s) => Math.max(s - SCALE_STEP, MIN_SCALE));
  const handleFitPage = () => setScale(defaultScale);
  const handleFitWidth = () => {
    const fit = calcFitWidthScale();
    if (fit) setScale(fit);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 400 }}>
      {/* 工具栏 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 10,
          padding: '6px 12px',
          background: '#f5f5f5',
          borderRadius: 6,
          flexWrap: 'wrap',
          border: '1px solid #e8e8e8',
          marginBottom: 8,
          flexShrink: 0,
        }}
      >
        <span style={{ fontWeight: 500, fontSize: 13, minWidth: 100, textAlign: 'center' }}>
          第 {currentPage} 页 / 共 {numPages} 页
        </span>
        <Space size="small">
          <Button
            size="small"
            icon={<ZoomOutOutlined />}
            disabled={scale <= MIN_SCALE}
            onClick={handleZoomOut}
          />
          <span style={{ minWidth: 38, textAlign: 'center', fontWeight: 500, fontSize: 12 }}>
            {Math.round(scale * 100)}%
          </span>
          <Button
            size="small"
            icon={<ZoomInOutlined />}
            disabled={scale >= MAX_SCALE}
            onClick={handleZoomIn}
          />
          <Button size="small" icon={<ExpandOutlined />} onClick={handleFitPage}>
            适合
          </Button>
          <Button size="small" icon={<ColumnWidthOutlined />} onClick={handleFitWidth}>
            适应宽度
          </Button>
        </Space>
      </div>

      {/* 滚动浏览区域 */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        style={{
          overflow: 'auto',
          flex: 1,
          background: '#e0e0e0',
          borderRadius: 6,
          position: 'relative',
          minHeight: 200,
          maxHeight,
        }}
      >
        {loading && (
          <Spin size="large" style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)' }} />
        )}
        {/* 内层容器：居中显示，超出时横向滚动 */}
        <div
          style={{
            minWidth: 'fit-content',
            margin: '0 auto',
            padding: '12px 12px',
          }}
        >
          {pageDims.map((dim, idx) => {
            const pageNum = idx + 1;
            const displayW = dim.w * scale;
            const displayH = dim.h * scale;
            return (
              <div
                key={pageNum}
                id={`pdf-placeholder-${pageNum}`}
                data-page={pageNum}
                style={{
                  width: `${displayW}px`,
                  height: `${displayH}px`,
                  marginBottom: 8,
                  backgroundColor: '#fff',
                  boxShadow: '0 2px 12px rgba(0,0,0,0.12)',
                  lineHeight: 0,
                  overflow: 'hidden',
                }}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default PdfViewer;
