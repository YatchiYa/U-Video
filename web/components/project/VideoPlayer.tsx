"use client";

import { useEffect, useRef, type Ref } from "react";
import type { Aspect } from "@/lib/api";
import { cx } from "../ui";

/**
 * The project video (served by the API through the /api proxy, with Range requests: seeking works).
 * Reports its time smoothly (requestAnimationFrame while playing) through `onTime`.
 */
export function VideoPlayer({
  src,
  aspect,
  onTime,
  ref,
  className,
  maxHeight = "70vh",
}: {
  src: string;
  aspect: Aspect;
  onTime?: (t: number) => void;
  ref?: Ref<HTMLVideoElement>;
  className?: string;
  maxHeight?: string;
}) {
  const inner = useRef<HTMLVideoElement | null>(null);
  const cb = useRef(onTime);
  useEffect(() => {
    cb.current = onTime;
  });

  useEffect(() => {
    const v = inner.current;
    if (!v) return;
    let raf = 0;
    const tick = () => {
      cb.current?.(v.currentTime);
      if (!v.paused) raf = requestAnimationFrame(tick);
    };
    const onPlay = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(tick);
    };
    const onUpdate = () => cb.current?.(v.currentTime);
    v.addEventListener("play", onPlay);
    v.addEventListener("seeked", onUpdate);
    v.addEventListener("timeupdate", onUpdate);
    v.addEventListener("loadedmetadata", onUpdate);
    return () => {
      cancelAnimationFrame(raf);
      v.removeEventListener("play", onPlay);
      v.removeEventListener("seeked", onUpdate);
      v.removeEventListener("timeupdate", onUpdate);
      v.removeEventListener("loadedmetadata", onUpdate);
    };
  }, [src]);

  const setRefs = (el: HTMLVideoElement | null) => {
    inner.current = el;
    if (typeof ref === "function") ref(el);
    else if (ref) (ref as { current: HTMLVideoElement | null }).current = el;
  };

  const vertical = aspect === "9:16" || aspect === "4:5";
  return (
    <div className={cx("overflow-hidden rounded-2xl bg-black shadow-[var(--shadow-lift)]", className)}>
      <video
        ref={setRefs}
        src={src}
        controls
        playsInline
        preload="auto"
        className={cx("mx-auto block bg-black", vertical ? "h-auto w-auto" : "w-full")}
        style={{ maxHeight }}
      />
    </div>
  );
}
