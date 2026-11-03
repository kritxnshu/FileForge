// Utilities that run entirely in the browser: image → Base64, colours, length units, byte sizes, QR codes.

import { encode as encodePng } from "fast-png";
import QRCode from "qrcode";
import { bytesToBase64 } from "./text";
import { ToolError, type ToolInput, type ToolResult } from "./types";

// ---------------------------------------------------------------------------
// image → Base64

const MIME: Record<string, string> = {
  png: "image/png", jpg: "image/jpeg", gif: "image/gif", webp: "image/webp", svg: "image/svg+xml", avif: "image/avif",
  bmp: "image/bmp", ico: "image/vnd.microsoft.icon",
};

export function imageBase64({ bytes, source, options }: ToolInput): ToolResult {
  if (!bytes?.length) throw new ToolError("Open an image file to encode.");
  const b64 = bytesToBase64(bytes);
  const uri = `data:${MIME[source] ?? "application/octet-stream"};base64,${b64}`;
  const out = { data_uri: uri, base64: b64, css: `background-image: url("${uri}");`, html: `<img src="${uri}" alt="">` }[
    (options.output as string) ?? "data_uri"] ?? uri;
  const notices = [`${bytes.length.toLocaleString()} bytes became ${out.length.toLocaleString()} characters (Base64 adds about 33%).`];
  return { output: out, notices, data: { preview: uri } };
}

// ---------------------------------------------------------------------------
// colours

type RGB = [number, number, number];

const clamp = (v: number, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
const toLin = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const fromLin = (c: number) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);

export function parseColor(input: string): { rgb: RGB; alpha: number } {
  const s = input.trim().toLowerCase();
  let m = s.match(/^#?([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/);
  if (m) {
    let h = m[1];
    if (h.length <= 4) h = [...h].map((c) => c + c).join("");
    const n = (i: number) => parseInt(h.slice(i, i + 2), 16);
    return { rgb: [n(0), n(2), n(4)], alpha: h.length === 8 ? n(6) / 255 : 1 };
  }
  const nums = (body: string) => body.split(/[\s,/]+/).filter(Boolean);
  m = s.match(/^rgba?\(([^)]*)\)$/);
  if (m) {
    const p = nums(m[1]);
    if (p.length < 3) throw new ToolError("rgb() needs three values, like rgb(51, 102, 255).");
    const ch = (v: string) => (v.endsWith("%") ? (parseFloat(v) / 100) * 255 : parseFloat(v));
    const rgb = p.slice(0, 3).map(ch) as RGB;
    if (rgb.some((v) => Number.isNaN(v) || v < 0 || v > 255)) throw new ToolError("RGB values must be between 0 and 255.");
    return { rgb: rgb.map(Math.round) as RGB, alpha: p[3] ? (p[3].endsWith("%") ? parseFloat(p[3]) / 100 : parseFloat(p[3])) : 1 };
  }
  m = s.match(/^hsla?\(([^)]*)\)$/);
  if (m) {
    const [h, sat, l, a] = nums(m[1]);
    const H = (((parseFloat(h) % 360) + 360) % 360) / 360;
    const S = clamp(parseFloat(sat) / 100);
    const L = clamp(parseFloat(l) / 100);
    if ([H, S, L].some(Number.isNaN)) throw new ToolError("hsl() needs a hue and two percentages, like hsl(220 100% 60%).");
    const q = L < 0.5 ? L * (1 + S) : L + S - L * S;
    const pp = 2 * L - q;
    const hue = (t: number) => {
      t = (t + 1) % 1;
      if (t < 1 / 6) return pp + (q - pp) * 6 * t;
      if (t < 1 / 2) return q;
      if (t < 2 / 3) return pp + (q - pp) * (2 / 3 - t) * 6;
      return pp;
    };
    return { rgb: [hue(H + 1 / 3), hue(H), hue(H - 1 / 3)].map((v) => Math.round(v * 255)) as RGB, alpha: a ? parseFloat(a) : 1 };
  }
  m = s.match(/^oklch\(([^)]*)\)$/);
  if (m) {
    const [Ls, Cs, hs] = nums(m[1]);
    const L = Ls.endsWith("%") ? parseFloat(Ls) / 100 : parseFloat(Ls);
    const C = parseFloat(Cs);
    const h = (parseFloat(hs) * Math.PI) / 180;
    const a = C * Math.cos(h);
    const b = C * Math.sin(h);
    const l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
    const m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
    const s_ = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
    const lin = [
      4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
      -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
      -0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_,
    ];
    if ([L, C, h].some(Number.isNaN)) throw new ToolError("oklch() needs lightness, chroma and hue, like oklch(62% 0.2 264).");
    return { rgb: lin.map((v) => Math.round(clamp(fromLin(v)) * 255)) as RGB, alpha: 1 };
  }
  throw new ToolError("Enter a color like #3366ff, rgb(51 102 255), hsl(225 100% 60%) or oklch(58% 0.22 264).");
}

export function toHsl([r, g, b]: RGB): [number, number, number] {
  const [R, G, B] = [r / 255, g / 255, b / 255];
  const max = Math.max(R, G, B);
  const min = Math.min(R, G, B);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, Math.round(l * 100)];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  const h = max === R ? (G - B) / d + (G < B ? 6 : 0) : max === G ? (B - R) / d + 2 : (R - G) / d + 4;
  return [Math.round(h * 60), Math.round(s * 100), Math.round(l * 100)];
}

export function toOklch([r, g, b]: RGB): [number, number, number] {
  const [R, G, B] = [r, g, b].map((v) => toLin(v / 255));
  const l = Math.cbrt(0.4122214708 * R + 0.5363325363 * G + 0.0514459929 * B);
  const m = Math.cbrt(0.2119034982 * R + 0.6806995451 * G + 0.1073969566 * B);
  const s = Math.cbrt(0.0883024619 * R + 0.2817188376 * G + 0.6299787005 * B);
  const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
  const a = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const bb = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
  const C = Math.sqrt(a * a + bb * bb);
  const h = C < 1e-4 ? 0 : ((Math.atan2(bb, a) * 180) / Math.PI + 360) % 360;
  return [L, C, h];
}

export function luminance([r, g, b]: RGB): number {
  const [R, G, B] = [r, g, b].map((v) => toLin(v / 255));
  return 0.2126 * R + 0.7152 * G + 0.0722 * B;
}

export function contrast(a: RGB, b: RGB): number {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

const hex = (rgb: RGB) => "#" + rgb.map((v) => v.toString(16).padStart(2, "0")).join("");

export function color({ text, options }: ToolInput): ToolResult {
  if (!text.trim()) throw new ToolError("Enter a color, like #3366ff.");
  const { rgb, alpha } = parseColor(text);
  const [h, s, l] = toHsl(rgb);
  const [L, C, H] = toOklch(rgb);
  const other = parseColor((options.contrast_with as string) ?? "#ffffff").rgb;
  const ratio = contrast(rgb, other);
  const grade = ratio >= 7 ? "passes AAA" : ratio >= 4.5 ? "passes AA" : ratio >= 3 ? "passes AA for large text only" : "fails WCAG AA";
  const lines = [
    `HEX:    ${hex(rgb)}${alpha < 1 ? Math.round(alpha * 255).toString(16).padStart(2, "0") : ""}`,
    `RGB:    rgb(${rgb.join(" ")}${alpha < 1 ? ` / ${+alpha.toFixed(3)}` : ""})`,
    `HSL:    hsl(${h} ${s}% ${l}%)`,
    `OKLCH:  oklch(${(L * 100).toFixed(1)}% ${C.toFixed(3)} ${H.toFixed(1)})`,
    `Contrast with ${hex(other)}: ${ratio.toFixed(2)}:1 (${grade})`,
  ];
  return { output: lines.join("\n") + "\n", data: { swatch: hex(rgb), against: hex(other), ratio } };
}

// ---------------------------------------------------------------------------
// length units

const PER_INCH: Record<string, number> = { in: 1, cm: 2.54, mm: 25.4, pt: 72 };

export function units({ text, options }: ToolInput): ToolResult {
  const m = text.trim().match(/^(-?\d*\.?\d+)\s*(px|in|cm|mm|pt)?$/i);
  if (!m) throw new ToolError("Enter a number, optionally with a unit, like 12 or 2.5cm.");
  const value = parseFloat(m[1]);
  const from = (m[2]?.toLowerCase() ?? (options.from_unit as string) ?? "px");
  const dpi = Number(options.dpi ?? 96);
  const inches = from === "px" ? value / dpi : value / PER_INCH[from];
  const fmt = (v: number) => String(+v.toFixed(4));
  const rows: [string, number][] = [["px", inches * dpi], ["in", inches], ["cm", inches * 2.54], ["mm", inches * 25.4], ["pt", inches * 72]];
  return { output: rows.map(([u, v]) => `${fmt(v)} ${u}`).join("\n") + "\n", notices: [`Pixels assume ${dpi} DPI.`] };
}

// ---------------------------------------------------------------------------
// byte sizes

const FACTOR: Record<string, number> = { B: 1, KB: 1e3, MB: 1e6, GB: 1e9, TB: 1e12, KIB: 1024, MIB: 1024 ** 2, GIB: 1024 ** 3, TIB: 1024 ** 4 };

export function byteSizes({ text, options }: ToolInput): ToolResult {
  const m = text.trim().replace(/,/g, "").match(/^(\d*\.?\d+)\s*([kmgt]i?b|b)?$/i);
  if (!m) throw new ToolError("Enter a size like 1.5 GB, 500 MiB or 1048576.");
  const unit = (m[2] ?? (options.from_unit as string) ?? "B").toUpperCase();
  const bytes = parseFloat(m[1]) * FACTOR[unit];
  const f = (v: number) => (v >= 1000 ? v.toLocaleString("en-US", { maximumFractionDigits: 2 }) : +v.toPrecision(6)).toString();
  const dec = ["B", "KB", "MB", "GB", "TB"].map((u) => `${f(bytes / FACTOR[u])} ${u}`);
  const bin = ["B", "KiB", "MiB", "GiB", "TiB"].map((u) => `${f(bytes / FACTOR[u.toUpperCase()])} ${u}`);
  const w = Math.max(...dec.map((d) => d.length)) + 4;
  const lines = ["Decimal (1000)".padEnd(w) + "Binary (1024)", ...dec.map((d, i) => d.padEnd(w) + bin[i])];
  return { output: lines.join("\n") + "\n", data: { bytes } };
}

// ---------------------------------------------------------------------------
// QR codes

const rgbOf = (h: string): RGB => parseColor(h).rgb;

export function qrMatrix(text: string, level: string): { size: number; get: (r: number, c: number) => boolean } {
  if (!text) throw new ToolError("Enter the text or link to encode.");
  try {
    const q = QRCode.create(text, { errorCorrectionLevel: level as QRCode.QRCodeErrorCorrectionLevel });
    return { size: q.modules.size, get: (r, c) => Boolean(q.modules.get(r, c)) };
  } catch (e) {
    throw new ToolError(`That's too much data for a QR code at this error-correction level (${(e as Error).message}).`);
  }
}

export function qr({ text, target, options }: ToolInput): ToolResult {
  const level = (options.error_correction as string) ?? "M";
  const margin = Number(options.margin ?? 4);
  const fg = (options.foreground as string) ?? "#000000";
  const bg = (options.background as string) ?? "#ffffff";
  const m = qrMatrix(text, level);
  const n = m.size + margin * 2;
  if (contrast(rgbOf(fg), rgbOf(bg)) < 3) {
    throw new ToolError("The colors are too similar for scanners to read. Use a dark color on a light background.");
  }
  if (target === "svg") {
    let path = "";
    for (let r = 0; r < m.size; r++) for (let c = 0; c < m.size; c++) if (m.get(r, c)) path += `M${c + margin} ${r + margin}h1v1h-1z`;
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${n} ${n}" shape-rendering="crispEdges">` +
      `<rect width="${n}" height="${n}" fill="${bg}"/><path d="${path}" fill="${fg}"/></svg>\n`;
    return { output: svg, data: { preview: `data:image/svg+xml;base64,${bytesToBase64(new TextEncoder().encode(svg))}` } };
  }
  const scale = Math.max(1, Math.floor(Number(options.size ?? 512) / n));
  const px = n * scale;
  const data = new Uint8Array(px * px * 4);
  const [F, B] = [rgbOf(fg), rgbOf(bg)];
  for (let y = 0; y < px; y++) {
    const r = Math.floor(y / scale) - margin;
    for (let x = 0; x < px; x++) {
      const c = Math.floor(x / scale) - margin;
      const on = r >= 0 && c >= 0 && r < m.size && c < m.size && m.get(r, c);
      const col = on ? F : B;
      const i = (y * px + x) * 4;
      data[i] = col[0]; data[i + 1] = col[1]; data[i + 2] = col[2]; data[i + 3] = 255;
    }
  }
  const png = encodePng({ width: px, height: px, data, channels: 4, depth: 8 });
  return { output: "", bytes: png, mime: "image/png", data: { preview: `data:image/png;base64,${bytesToBase64(png)}` },
    notices: [`${px}×${px} pixels, ${m.size}×${m.size} modules.`] };
}
