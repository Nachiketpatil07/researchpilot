"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Turn [3] into a markdown link we can render as a clickable citation chip. */
function linkCitations(text: string) {
  return text.replace(/\[(\d{1,2})\](?!\()/g, "[$1](#cite-$1)");
}

export default function AnswerMarkdown({
  text,
  streaming,
  onCite,
}: {
  text: string;
  streaming: boolean;
  onCite: (n: number) => void;
}) {
  return (
    <div className={`md text-[15px] leading-relaxed ${streaming ? "caret" : ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            const m = href?.match(/^#cite-(\d+)$/);
            if (m) {
              const n = Number(m[1]);
              return (
                <button
                  type="button"
                  onClick={() => onCite(n)}
                  title={`Show source ${n}`}
                  className="mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded bg-indigo-100 px-1 align-middle font-mono text-[11px] font-semibold text-indigo-700 hover:bg-indigo-200 dark:bg-indigo-900/60 dark:text-indigo-200 dark:hover:bg-indigo-800"
                >
                  {n}
                </button>
              );
            }
            return (
              <a href={href} target="_blank" rel="noreferrer" className="text-indigo-600 underline dark:text-indigo-400">
                {children}
              </a>
            );
          },
        }}
      >
        {linkCitations(text)}
      </ReactMarkdown>
    </div>
  );
}
