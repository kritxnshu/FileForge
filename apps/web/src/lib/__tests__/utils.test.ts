import { decode as decodePng } from "fast-png";
import jsQR from "jsqr";
import { describe, expect, it } from "vitest";
import { TOOLS } from "../tools";
import { contrast, parseColor, toHsl, toOklch } from "../tools/utils";

const run = async (op: string, text: string, source: string, target: string, options: Record<string, unknown> = {}, bytes?: Uint8Array) =>
  TOOLS[op]({ text, bytes, source, target, options });

const PNG_1x1 = Uint8Array.from(atob("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="), (c) => c.charCodeAt(0));

describe("image to Base64", () => {
  for (const fmt of ["png", "jpg", "gif", "webp", "svg", "avif", "bmp", "ico"])
    it(`util.image_base64:${fmt}->txt produces a decodable data URI`, async () => {
      const r = await run("util.image_base64", "", fmt, "txt", {}, PNG_1x1);
      expect(r.output.startsWith("data:image/")).toBe(true);
      const b64 = r.output.split(",")[1];
      expect(Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))).toEqual(PNG_1x1);
    });
  it("util.image_base64:png->txt css and html forms", async () => {
    expect((await run("util.image_base64", "", "png", "txt", { output: "css" }, PNG_1x1)).output).toMatch(/^background-image: url\("data:image\/png;base64,/);
    expect((await run("util.image_base64", "", "png", "txt", { output: "html" }, PNG_1x1)).output).toMatch(/^<img src="data:image\/png/);
  });
  it("neg:util.image_base64 needs a file", async () => {
    await expect(run("util.image_base64", "", "png", "txt")).rejects.toThrow(/Open an image/);
  });
});

describe("color converter", () => {
  it("util.color:txt->txt round-trips between notations", async () => {
    for (const c of ["#3366ff", "rgb(51 102 255)", "rgb(51, 102, 255)", "hsl(225 100% 60%)", "#36f"]) expect(parseColor(c).rgb).toEqual([51, 102, 255]);
    const ok = toOklch([51, 102, 255]);
    expect(parseColor(`oklch(${ok[0] * 100}% ${ok[1]} ${ok[2]})`).rgb).toEqual([51, 102, 255]);
    expect(toHsl([255, 0, 0])).toEqual([0, 100, 50]);
    const r = await run("util.color", "#777777", "txt", "txt", { contrast_with: "#ffffff" });
    expect(r.output).toContain("Contrast with #ffffff: 4.48:1 (passes AA for large text only)");
  });
  it("util.color:txt->txt matches WCAG reference ratios", () => {
    expect(contrast([0, 0, 0], [255, 255, 255])).toBeCloseTo(21, 5);
    expect(contrast([255, 255, 255], [255, 255, 255])).toBeCloseTo(1, 5);
  });
  it("neg:util.color rejects nonsense", async () => {
    await expect(run("util.color", "blurple", "txt", "txt")).rejects.toThrow(/Enter a color/);
    await expect(run("util.color", "rgb(300 0 0)", "txt", "txt")).rejects.toThrow(/between 0 and 255/);
  });
});

describe("units and bytes", () => {
  it("util.units:txt->txt converts with DPI", async () => {
    const r = await run("util.units", "96", "txt", "txt", { from_unit: "px", dpi: 96 });
    expect(r.output).toBe("96 px\n1 in\n2.54 cm\n25.4 mm\n72 pt\n");
    expect((await run("util.units", "2.54cm", "txt", "txt", { dpi: 300 })).output.split("\n")[0]).toBe("300 px");
  });
  it("neg:util.units rejects bad input", async () => {
    await expect(run("util.units", "twelve", "txt", "txt")).rejects.toThrow(/Enter a number/);
  });
  it("util.bytes:txt->txt shows decimal and binary", async () => {
    const r = await run("util.bytes", "1 GiB", "txt", "txt");
    expect(r.output).toContain("1,073,741,824 B");
    expect(r.output).toMatch(/1\.07374 GB\s+1 GiB/);
    expect((await run("util.bytes", "1500", "txt", "txt", { from_unit: "MB" })).output).toMatch(/1\.5 GB\s+1\.39698 GiB/);
  });
  it("neg:util.bytes rejects bad input", async () => {
    await expect(run("util.bytes", "lots", "txt", "txt")).rejects.toThrow(/Enter a size/);
  });
});

describe("QR codes", () => {
  it("util.qr:txt->png decodes back to the input", async () => {
    const text = "https://example.com/?q=Ünïcode & more";
    for (const level of ["L", "H"]) {
      const r = await run("util.qr", text, "txt", "png", { error_correction: level, size: 300 });
      const img = decodePng(r.bytes!);
      const rgba = new Uint8ClampedArray(img.data.buffer, img.data.byteOffset, img.data.byteLength);
      expect(jsQR(rgba, img.width, img.height)?.data).toBe(text);
    }
  });
  it("util.qr:txt->svg is a valid vector QR that decodes", async () => {
    const r = await run("util.qr", "HELLO 123", "txt", "svg", { margin: 2 });
    expect(r.output).toMatch(/^<svg xmlns="http:\/\/www.w3.org\/2000\/svg" viewBox="0 0 \d+ \d+"/);
    // rasterize the SVG path ourselves and decode it
    const [, n] = r.output.match(/viewBox="0 0 (\d+)/)!.map(Number) as unknown as [string, number];
    const scale = 8;
    const px = Number(n) * scale;
    const rgba = new Uint8ClampedArray(px * px * 4).fill(255);
    for (const [, x, y] of r.output.matchAll(/M(\d+) (\d+)h1v1h-1z/g))
      for (let dy = 0; dy < scale; dy++) for (let dx = 0; dx < scale; dx++) {
        const i = ((Number(y) * scale + dy) * px + Number(x) * scale + dx) * 4;
        rgba[i] = rgba[i + 1] = rgba[i + 2] = 0;
      }
    expect(jsQR(rgba, px, px)?.data).toBe("HELLO 123");
  });
  it("neg:util.qr rejects unreadable colours and too much data", async () => {
    await expect(run("util.qr", "x", "txt", "png", { foreground: "#eeeeee", background: "#ffffff" })).rejects.toThrow(/too similar/);
    await expect(run("util.qr", "x".repeat(5000), "txt", "png", { error_correction: "H" })).rejects.toThrow(/too much data/);
  });
});
