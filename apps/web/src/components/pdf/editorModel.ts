// The page editor's data model. Coordinates are normalised to the page as displayed (0..1 from the top-left), the
// same space the server's pdfgeom.PageFrame maps into PDF user space, so placement is identical on rotated pages.

export type EditorMode = "edit" | "sign" | "redact" | "crop" | "form";

export type Font = "helvetica" | "helvetica-bold" | "helvetica-italic" | "times" | "times-bold" | "times-italic" | "courier" | "courier-bold";

export interface TextItem { type: "text"; page: number; x: number; y: number; text: string; font: Font; size: number; color: string; opacity: number }
export interface ImageItem { type: "image"; page: number; x: number; y: number; w: number; h: number; data: string; opacity: number }
export interface BoxItem { type: "rect" | "ellipse" | "highlight" | "whiteout"; page: number; x: number; y: number; w: number; h: number; stroke: string | null; fill: string | null; width: number; opacity: number }
export interface LineItem { type: "line" | "arrow"; page: number; x1: number; y1: number; x2: number; y2: number; color: string; width: number; opacity: number }
export interface PathItem { type: "path"; page: number; points: [number, number][]; color: string; width: number; opacity: number }
export interface AreaItem { type: "redact" | "crop"; page: number; x: number; y: number; w: number; h: number }
export interface FieldItem { type: "field"; kind: "text" | "checkbox" | "dropdown"; page: number; x: number; y: number; w: number; h: number; name: string; options: string[]; multiline: boolean; required: boolean }

export type Item = TextItem | ImageItem | BoxItem | LineItem | PathItem | AreaItem | FieldItem;
export type Boxy = ImageItem | BoxItem | AreaItem | FieldItem;

export const isBoxy = (it: Item): it is Boxy => "w" in it && "h" in it;

/** The option value a mode stores (what the server receives) → editor items. */
export function toItems(mode: EditorMode, value: unknown): Item[] {
  if (mode === "crop") {
    const a = value as { x: number; y: number; w: number; h: number } | null | undefined;
    return a ? [{ type: "crop", page: 1, ...a }] : [];
  }
  const list = Array.isArray(value) ? value : [];
  if (mode === "redact") return list.map((a) => ({ type: "redact", ...a }));
  if (mode === "form") return list.map((f) => ({ ...f, type: "field", kind: f.type, options: f.options ?? [], multiline: !!f.multiline, required: !!f.required }));
  return list as Item[];
}

/** Editor items → the option value for this mode. */
export function fromItems(mode: EditorMode, items: Item[]): unknown {
  const r = (n: number) => Math.round(n * 100000) / 100000;
  if (mode === "crop") {
    const a = items.find((i) => i.type === "crop") as AreaItem | undefined;
    return a ? { x: r(Math.max(0, a.x)), y: r(Math.max(0, a.y)), w: r(a.w), h: r(a.h) } : null;
  }
  if (mode === "redact") return items.filter((i): i is AreaItem => i.type === "redact").map(({ page, x, y, w, h }) => ({ page, x: r(x), y: r(y), w: r(w), h: r(h) }));
  if (mode === "form") {
    return items.filter((i): i is FieldItem => i.type === "field").map((f) => ({
      type: f.kind, page: f.page, x: r(f.x), y: r(f.y), w: r(f.w), h: r(f.h), name: f.name,
      ...(f.kind === "dropdown" ? { options: f.options } : {}), ...(f.kind === "text" && f.multiline ? { multiline: true } : {}),
      ...(f.required ? { required: true } : {}),
    }));
  }
  return items;
}

/** Bounding box (normalised). `pw`/`ph` are the page's displayed size in points (text is sized in points). */
export function bbox(it: Item, pw: number, ph: number): { x: number; y: number; w: number; h: number } {
  if (isBoxy(it)) return { x: it.x, y: it.y, w: it.w, h: it.h };
  if (it.type === "line" || it.type === "arrow") {
    return { x: Math.min(it.x1, it.x2), y: Math.min(it.y1, it.y2), w: Math.abs(it.x2 - it.x1), h: Math.abs(it.y2 - it.y1) };
  }
  if (it.type === "path") {
    const xs = it.points.map((p) => p[0]);
    const ys = it.points.map((p) => p[1]);
    return { x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) };
  }
  if (it.type !== "text") return { x: 0, y: 0, w: 0, h: 0 };
  // text: estimated from its size in points
  const lines = it.text.split("\n");
  const longest = Math.max(...lines.map((l) => l.length), 1);
  return { x: it.x, y: it.y, w: (longest * it.size * 0.55) / pw, h: (lines.length * it.size * 1.2) / ph };
}

export function hit(it: Item, u: number, v: number, pw: number, ph: number, slop = 0.012): boolean {
  const b = bbox(it, pw, ph);
  return u >= b.x - slop && u <= b.x + b.w + slop && v >= b.y - slop && v <= b.y + b.h + slop;
}

export function moved(it: Item, du: number, dv: number): Item {
  if (it.type === "line" || it.type === "arrow") return { ...it, x1: it.x1 + du, y1: it.y1 + dv, x2: it.x2 + du, y2: it.y2 + dv };
  if (it.type === "path") return { ...it, points: it.points.map(([a, b]) => [a + du, b + dv] as [number, number]) };
  return { ...it, x: (it as Boxy | TextItem).x + du, y: (it as Boxy | TextItem).y + dv } as Item;
}

export function label(it: Item): string {
  switch (it.type) {
    case "text": return `Text “${it.text.split("\n")[0].slice(0, 24) || "…"}”`;
    case "image": return "Image";
    case "rect": return "Rectangle";
    case "ellipse": return "Ellipse";
    case "highlight": return "Highlight";
    case "whiteout": return "White-out";
    case "line": return "Line";
    case "arrow": return "Arrow";
    case "path": return "Drawing";
    case "redact": return "Redaction";
    case "crop": return "Crop area";
    case "field": return `${it.kind === "text" ? "Text box" : it.kind === "checkbox" ? "Checkbox" : "Dropdown"} “${it.name}”`;
  }
}

export const CSS_FONT: Record<Font, { family: string; weight: number; style: string }> = {
  helvetica: { family: "Helvetica, Arial, sans-serif", weight: 400, style: "normal" },
  "helvetica-bold": { family: "Helvetica, Arial, sans-serif", weight: 700, style: "normal" },
  "helvetica-italic": { family: "Helvetica, Arial, sans-serif", weight: 400, style: "italic" },
  times: { family: "'Times New Roman', Times, serif", weight: 400, style: "normal" },
  "times-bold": { family: "'Times New Roman', Times, serif", weight: 700, style: "normal" },
  "times-italic": { family: "'Times New Roman', Times, serif", weight: 400, style: "italic" },
  courier: { family: "'Courier New', Courier, monospace", weight: 400, style: "normal" },
  "courier-bold": { family: "'Courier New', Courier, monospace", weight: 700, style: "normal" },
};

/** Downscale an image file in the browser and return a data URL small enough to send (PNG keeps transparency). */
export async function imageFileToData(file: File, maxSide = 1600): Promise<{ data: string; width: number; height: number }> {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise<HTMLImageElement>((res, rej) => {
      const i = new Image();
      i.onload = () => res(i);
      i.onerror = () => rej(new Error("This image couldn't be read."));
      i.src = url;
    });
    const s = Math.min(1, maxSide / Math.max(img.width, img.height));
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(img.width * s));
    c.height = Math.max(1, Math.round(img.height * s));
    c.getContext("2d")!.drawImage(img, 0, 0, c.width, c.height);
    const png = file.type === "image/png" || file.type === "image/webp" || file.type === "image/gif";
    return { data: png ? c.toDataURL("image/png") : c.toDataURL("image/jpeg", 0.88), width: c.width, height: c.height };
  } finally {
    URL.revokeObjectURL(url);
  }
}
