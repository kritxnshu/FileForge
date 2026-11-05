import type { Metadata } from "next";
import { HistoryPanel } from "@/components/History";
import { PageHeader } from "@/components/PageHeader";
import { Workspace } from "@/components/Workspace";

export const metadata: Metadata = { title: "Convert files", description: "Upload files and convert them to another format." };

export default function ConvertPage() {
  return (
    <>
      <PageHeader eyebrow="Workspace" title="Convert files"
        description="Stage your files, pick what each type should become, then convert. Mixed batches work." />
      <Workspace />
      <div className="mt-10"><HistoryPanel /></div>
    </>
  );
}
