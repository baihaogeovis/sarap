
import type Map from "ol/Map";
import type Layer from "ol/layer/Layer";

/**
 * Clip the right-hand layer at `ratio` (0–1) during render.
 * Used for baseline / event compare. Returns a disposer.
 */
export function attachSwipe(map: Map, layer: Layer, getRatio: () => number): () => void {
  const pre = layer.on("prerender", (event) => {
    const ctx = event.context as CanvasRenderingContext2D;
    const width = ctx.canvas.width * getRatio();
    ctx.save();
    ctx.beginPath();
    ctx.rect(width, 0, ctx.canvas.width - width, ctx.canvas.height);
    ctx.clip();
  });
  const post = layer.on("postrender", (event) => {
    const ctx = event.context as CanvasRenderingContext2D;
    ctx.restore();
  });
  map.render();
  return () => {
    layer.un("prerender", pre.listener);
    layer.un("postrender", post.listener);
    map.render();
  };
}
