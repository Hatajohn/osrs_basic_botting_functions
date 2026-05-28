import type { ReactNode, RefObject } from 'react';

type StreamViewportProps = {
  baseSrc: string;
  imageRef: RefObject<HTMLImageElement | null>;
  alt: string;
  children?: ReactNode;
};

/** Base game view + absolutely stacked overlay children. Only the parent updates baseSrc. */
export function StreamViewport({ baseSrc, imageRef, alt, children }: StreamViewportProps) {
  return (
    <div className="panel__image-wrap panel__image-wrap--with-overlay">
      <img
        ref={imageRef}
        className="panel__debug-image"
        src={baseSrc}
        alt={alt}
        draggable={false}
      />
      {children}
    </div>
  );
}
