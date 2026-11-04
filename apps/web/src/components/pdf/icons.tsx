import { createElement } from "react";
import {
  Archive, Braces, Camera, Code, Combine, Crop, Eraser, FileMinus, FileOutput, FileText, FormInput, GitCompare,
  Grid2x2, Hash, Image, ImagePlus, Images, Info, Layers, LayoutGrid, ListOrdered, Lock, LockOpen, Minimize2,
  PencilLine, Presentation, RotateCw, Scaling, ScanText, Sheet, Signature, Split, Stamp, TextCursorInput, Type, Wrench,
  type LucideIcon,
} from "lucide-react";

/** Icon names used by the API's hub definitions (engine/hubs.py) → components. Unknown names fall back to a file. */
const ICONS: Record<string, LucideIcon> = {
  archive: Archive, braces: Braces, camera: Camera, code: Code, combine: Combine, crop: Crop, eraser: Eraser,
  "file-minus": FileMinus, "file-output": FileOutput, "file-text": FileText, "form-input": FormInput,
  "git-compare": GitCompare, "grid-2x2": Grid2x2, hash: Hash, image: Image, "image-plus": ImagePlus, images: Images,
  info: Info, layers: Layers, "layout-grid": LayoutGrid, "list-ordered": ListOrdered, lock: Lock, "lock-open": LockOpen,
  "minimize-2": Minimize2, "pencil-line": PencilLine, presentation: Presentation, "rotate-cw": RotateCw, scaling: Scaling,
  "scan-text": ScanText, sheet: Sheet, signature: Signature, split: Split, stamp: Stamp,
  "text-cursor-input": TextCursorInput, type: Type, wrench: Wrench,
};

/** A hub tool's icon by name (looked up in a static map, so no component is created during render). */
export function HubIcon({ name, size = 22, strokeWidth = 2 }: { name: string; size?: number; strokeWidth?: number }) {
  return createElement(ICONS[name] ?? FileText, { size, strokeWidth, "aria-hidden": true });
}
