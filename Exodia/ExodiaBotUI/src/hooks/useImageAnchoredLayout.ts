import { useCallback, useEffect, useState, type DependencyList, type RefObject } from 'react';

/** Recompute overlay layout when the displayed img resizes, loads, or inputs change. */
export function useImageAnchoredLayout<T>(
  imageRef: RefObject<HTMLImageElement | null>,
  computeLayout: (img: HTMLImageElement) => T | null,
  deps: DependencyList,
): T | null {
  const [layout, setLayout] = useState<T | null>(null);

  const update = useCallback(() => {
    const img = imageRef.current;
    if (!img) {
      setLayout(null);
      return;
    }
    setLayout(computeLayout(img));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- caller-owned deps
  }, [imageRef, computeLayout, ...deps]);

  useEffect(() => {
    update();
    const img = imageRef.current;
    if (!img) return undefined;

    const onLoad = () => update();
    img.addEventListener('load', onLoad);

    const ro = new ResizeObserver(() => update());
    ro.observe(img);
    if (img.parentElement) ro.observe(img.parentElement);

    return () => {
      img.removeEventListener('load', onLoad);
      ro.disconnect();
    };
  }, [update]);

  return layout;
}
