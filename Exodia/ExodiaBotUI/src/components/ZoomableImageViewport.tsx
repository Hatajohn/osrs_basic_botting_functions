import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from 'react';
import './ZoomableImageViewport.css';

const MIN_SCALE = 0.25;
const MAX_SCALE = 8;
const ZOOM_STEP = 1.25;
const DOUBLE_CLICK_SCALE = 2;

export type ZoomViewportInfo = {
  scale: number;
  fitScale: number;
  naturalWidth: number;
  naturalHeight: number;
};

export type ZoomViewportHandle = {
  zoomIn: () => void;
  zoomOut: () => void;
  zoomFit: () => void;
  zoom100: () => void;
};

type ZoomableImageViewportProps = {
  baseSrc: string;
  imageRef: RefObject<HTMLImageElement | null>;
  alt: string;
  children?: ReactNode;
  /** When this value changes, zoom/pan reset to fit. Omit for continuous streams. */
  resetKey?: string | number;
  onZoomChange?: (info: ZoomViewportInfo) => void;
};

function clampScale(value: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, value));
}

function zoomPercent(scale: number, fitScale: number): number {
  if (fitScale <= 0) return Math.round(scale * 100);
  return Math.round((scale / fitScale) * 100);
}

export const ZoomableImageViewport = forwardRef<ZoomViewportHandle, ZoomableImageViewportProps>(
  function ZoomableImageViewport(
    { baseSrc, imageRef, alt, children, resetKey, onZoomChange },
    ref,
  ) {
    const viewportRef = useRef<HTMLDivElement>(null);
    const [scale, setScale] = useState(1);
    const [panX, setPanX] = useState(0);
    const [panY, setPanY] = useState(0);
    const [fitScale, setFitScale] = useState(1);
    const [naturalSize, setNaturalSize] = useState({ w: 0, h: 0 });
    const [spaceHeld, setSpaceHeld] = useState(false);
    const [isPanning, setIsPanning] = useState(false);
    const panRef = useRef<{ active: boolean; startX: number; startY: number; panX: number; panY: number } | null>(
      null,
    );
    const lastNonFitScale = useRef(DOUBLE_CLICK_SCALE);
    const atFitRef = useRef(true);

    const emitZoom = useCallback(
      (nextScale: number, nextFit: number, nw: number, nh: number) => {
        onZoomChange?.({
          scale: nextScale,
          fitScale: nextFit,
          naturalWidth: nw,
          naturalHeight: nh,
        });
      },
      [onZoomChange],
    );

    const centerAtScale = useCallback(
      (nextScale: number, nw: number, nh: number) => {
        const vp = viewportRef.current;
        if (!vp || nw <= 0 || nh <= 0) {
          setPanX(0);
          setPanY(0);
          return;
        }
        const cw = vp.clientWidth;
        const ch = vp.clientHeight;
        setPanX((cw - nw * nextScale) / 2);
        setPanY((ch - nh * nextScale) / 2);
      },
      [],
    );

    const applyFit = useCallback(
      (nw: number, nh: number, fit: number) => {
        setScale(fit);
        centerAtScale(fit, nw, nh);
        atFitRef.current = true;
        emitZoom(fit, fit, nw, nh);
      },
      [centerAtScale, emitZoom],
    );

    const recomputeFit = useCallback(() => {
      const vp = viewportRef.current;
      const img = imageRef.current;
      if (!vp || !img) return;

      const nw = img.naturalWidth;
      const nh = img.naturalHeight;
      if (nw <= 0 || nh <= 0) return;

      setNaturalSize({ w: nw, h: nh });
      const cw = Math.max(1, vp.clientWidth);
      const ch = Math.max(1, vp.clientHeight);
      const fit = clampScale(Math.min(cw / nw, ch / nh));
      setFitScale(fit);

      if (atFitRef.current) {
        applyFit(nw, nh, fit);
      } else {
        emitZoom(scale, fit, nw, nh);
      }
    }, [applyFit, emitZoom, imageRef, scale]);

    const zoomTo = useCallback(
      (nextScale: number, anchorX?: number, anchorY?: number) => {
        const vp = viewportRef.current;
        const img = imageRef.current;
        if (!vp || !img) return;

        const nw = img.naturalWidth;
        const nh = img.naturalHeight;
        if (nw <= 0 || nh <= 0) return;

        const clamped = clampScale(nextScale);
        const ax = anchorX ?? vp.clientWidth / 2;
        const ay = anchorY ?? vp.clientHeight / 2;
        const contentX = (ax - panX) / scale;
        const contentY = (ay - panY) / scale;

        setPanX(ax - contentX * clamped);
        setPanY(ay - contentY * clamped);
        setScale(clamped);
        atFitRef.current = Math.abs(clamped - fitScale) < 0.001;
        if (!atFitRef.current) {
          lastNonFitScale.current = clamped;
        }
        emitZoom(clamped, fitScale, nw, nh);
      },
      [emitZoom, fitScale, imageRef, panX, panY, scale],
    );

    const zoomIn = useCallback(() => {
      zoomTo(scale * ZOOM_STEP);
    }, [scale, zoomTo]);

    const zoomOut = useCallback(() => {
      zoomTo(scale / ZOOM_STEP);
    }, [scale, zoomTo]);

    const zoomFit = useCallback(() => {
      const img = imageRef.current;
      if (!img || img.naturalWidth <= 0) return;
      applyFit(img.naturalWidth, img.naturalHeight, fitScale);
    }, [applyFit, fitScale, imageRef]);

    const zoom100 = useCallback(() => {
      zoomTo(1);
      atFitRef.current = false;
      lastNonFitScale.current = 1;
    }, [zoomTo]);

    useImperativeHandle(ref, () => ({ zoomIn, zoomOut, zoomFit, zoom100 }), [
      zoomIn,
      zoomOut,
      zoomFit,
      zoom100,
    ]);

    useEffect(() => {
      if (resetKey === undefined) return;
      atFitRef.current = true;
      recomputeFit();
    }, [resetKey, recomputeFit]);

    useEffect(() => {
      const vp = viewportRef.current;
      if (!vp) return undefined;

      const ro = new ResizeObserver(() => recomputeFit());
      ro.observe(vp);
      return () => ro.disconnect();
    }, [recomputeFit]);

    useEffect(() => {
      const onKeyDown = (e: KeyboardEvent) => {
        if (e.code === 'Space' && !e.repeat) {
          setSpaceHeld(true);
        }
      };
      const onKeyUp = (e: KeyboardEvent) => {
        if (e.code === 'Space') {
          setSpaceHeld(false);
          panRef.current = null;
          setIsPanning(false);
        }
      };
      window.addEventListener('keydown', onKeyDown);
      window.addEventListener('keyup', onKeyUp);
      return () => {
        window.removeEventListener('keydown', onKeyDown);
        window.removeEventListener('keyup', onKeyUp);
      };
    }, []);

    const onImageLoad = () => {
      recomputeFit();
    };

    const onWheel = (e: React.WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const rect = viewportRef.current?.getBoundingClientRect();
      if (!rect) return;
      const anchorX = e.clientX - rect.left;
      const anchorY = e.clientY - rect.top;
      const factor = e.deltaY > 0 ? 1 / ZOOM_STEP : ZOOM_STEP;
      zoomTo(scale * factor, anchorX, anchorY);
    };

    const onDoubleClick = (e: React.MouseEvent) => {
      if (atFitRef.current) {
        zoomTo(Math.max(lastNonFitScale.current, DOUBLE_CLICK_SCALE), e.nativeEvent.offsetX, e.nativeEvent.offsetY);
      } else {
        zoomFit();
      }
    };

    const startPan = (clientX: number, clientY: number) => {
      panRef.current = { active: true, startX: clientX, startY: clientY, panX, panY };
      setIsPanning(true);
    };

    const onPointerDown = (e: React.PointerEvent) => {
      const middle = e.button === 1;
      const spaceDrag = spaceHeld && e.button === 0;
      if (!middle && !spaceDrag) return;
      e.preventDefault();
      viewportRef.current?.setPointerCapture(e.pointerId);
      startPan(e.clientX, e.clientY);
    };

    const onPointerMove = (e: React.PointerEvent) => {
      const pan = panRef.current;
      if (!pan?.active) return;
      setPanX(pan.panX + (e.clientX - pan.startX));
      setPanY(pan.panY + (e.clientY - pan.startY));
    };

    const onPointerUp = (e: React.PointerEvent) => {
      if (panRef.current?.active) {
        panRef.current = null;
        setIsPanning(false);
        viewportRef.current?.releasePointerCapture(e.pointerId);
      }
    };

    const viewportClass = [
      'zoomable-viewport',
      isPanning ? 'zoomable-viewport--panning' : '',
      spaceHeld && !isPanning ? 'zoomable-viewport--space-pan' : '',
    ]
      .filter(Boolean)
      .join(' ');

    return (
      <div
        ref={viewportRef}
        className={viewportClass}
        onWheel={onWheel}
        onDoubleClick={onDoubleClick}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <div
          className="zoomable-viewport__content"
          style={{ transform: `translate(${panX}px, ${panY}px) scale(${scale})` }}
        >
          <div className="zoomable-viewport__image-layer">
            <img
              ref={imageRef}
              className="zoomable-viewport__image"
              src={baseSrc}
              alt={alt}
              draggable={false}
              onLoad={onImageLoad}
            />
            {children ? <div className="zoomable-viewport__overlay-root">{children}</div> : null}
          </div>
        </div>
      </div>
    );
  },
);

export { zoomPercent };
