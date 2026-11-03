import type { Metadata } from "next";
import { HistoryPanel } from "@/components/History";
import { Workspace } from "@/components/Workspace";

export const metadata: Metadata = { title: "Convert files", description: "Upload files and convert them to another format." };

export default function ConvertPage() {
  return (
    <div className="pb-10 pt-4">
      <h1 className="mb-6 font-display text-4xl font-bold sm:text-5xl">Convert files</h1>
      <Workspace />
      <HistoryPanel />
    </div>
  );
}
