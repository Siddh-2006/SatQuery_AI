/**
 * components/chat/ReportDownloadButton.tsx
 * ==========================================
 * Downloads the per-answer report the backend prepared (DESIGN.md §6.8).
 *
 * A plain anchor, not a fetch: the endpoint returns file bytes, so letting
 * the browser handle it gives the researcher their own download UI,
 * progress and retry for free — and means a large report never sits in a
 * JS buffer.
 */
import { reportUrl } from "../../api/client";
import { useToastStore } from "../../state/useToastStore";

interface ReportDownloadButtonProps {
  url: string;
}

export function ReportDownloadButton({ url }: ReportDownloadButtonProps) {
  const showToast = useToastStore((s) => s.show);

  return (
    <a
      href={reportUrl(url)}
      download
      onClick={() => showToast("Report requested")}
      className="btn btn-secondary text-[12px] no-underline"
    >
      <i className="ph ph-download-simple text-[12px]" aria-hidden="true" />
      Download report
    </a>
  );
}
