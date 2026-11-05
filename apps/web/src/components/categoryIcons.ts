import { Archive, AudioLines, Braces, FileSpreadsheet, FileText, Image, Presentation, Video, Wrench, type LucideIcon } from "lucide-react";

/** One icon per registry category. A plain module, so server pages can read it too. */
export const CATEGORY_ICON: Record<string, LucideIcon> = {
  images: Image, documents: FileText, spreadsheets: FileSpreadsheet, presentations: Presentation,
  audio: AudioLines, video: Video, archives: Archive, developer: Braces, utilities: Wrench,
};
