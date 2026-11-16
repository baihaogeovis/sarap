
import type Map from "ol/Map";

/** Stub: compose the map viewport canvases into a PNG download. */
export function exportMapPng(map: Map, filename = "sarap-map.png"): void {
  map.once("rendercomplete", () => {
    const mapCanvas = document.createElement("canvas");
    const size = map.getSize();
    if (!size) return;
    mapCanvas.width = size[0];
    mapCanvas.height = size[1];
    const ctx = mapCanvas.getContext("2d");
    if (!ctx) return;
    const node = map.getViewport();
    if (!node) return;
    node.querySelectorAll("canvas").forEach((canvas) => {
      if (canvas.width > 0) ctx.drawImage(canvas, 0, 0);
    });
    const link = document.createElement("a");
    link.download = filename;
    link.href = mapCanvas.toDataURL("image/png");
    link.click();
  });
  map.renderSync();
}
